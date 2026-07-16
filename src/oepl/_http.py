"""Low-level async HTTP client for the OpenEPaperLink AP."""

from __future__ import annotations

import asyncio
from typing import Any, Callable, cast
from urllib.parse import quote
from uuid import uuid4

import aiohttp

from .exceptions import (
    OEPLConnectionError,
    OEPLNotFoundError,
    OEPLResponseError,
    OEPLTimeoutError,
)

_DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=10)
_UPLOAD_TIMEOUT = aiohttp.ClientTimeout(total=30)
_MAX_UPLOAD_RETRIES = 3
_UPLOAD_BACKOFF = 2  # seconds; doubles on each retry


def quote_query_value(value: str) -> str:
    """URL-encode a value for interpolation into a query string.

    Applied uniformly to every query-string value this library builds by hand
    (``f"edit?list={...}"``-style interpolation, not ``aiohttp``'s own
    ``params=``). Most values (MACs, hex hashes) are already URL-safe, but
    ``files.*`` deals with arbitrary filesystem paths, so a name containing a
    space, ``&``, ``#``, or ``?`` would otherwise corrupt the query string.
    Uses ``quote``'s default ``safe="/"``: these values are themselves
    filesystem-style paths (``files.list``/``download``/``check`` always
    prepend a leading ``/``), and ``/`` needs no escaping inside a query
    string component, so leaving it unescaped keeps URLs readable without
    changing the AP's parsed result (ESPAsyncWebServer URL-decodes params).
    """
    return quote(value)


def _raise_if_error_body(body: str) -> None:
    """Raise OEPLResponseError if an HTTP-200 body is actually an AP-reported error.

    The AP firmware reports some failures as ``200`` with an error string body
    (e.g. ``/save_cfg`` with an unknown MAC returns ``200 "Error while saving:
    mac not found"``). Any body that, once stripped, starts with "Error" or
    "error" is treated as a failure even though the HTTP status was 200. Only
    ever called after the 200 gate in :meth:`_HTTPClient._request`, so the
    status is always 200 — no need to thread it through as a parameter.
    """
    stripped = body.strip()
    if stripped.startswith("Error") or stripped.startswith("error"):
        raise OEPLResponseError(200, body)


class _HTTPClient:
    """Wraps aiohttp.ClientSession with AP-specific error mapping."""

    def __init__(self, host: str, session_provider: Callable[[], aiohttp.ClientSession]) -> None:
        self._base = f"http://{host}"
        self._session_provider = session_provider

    def _url(self, path: str) -> str:
        return f"{self._base}/{path.lstrip('/')}"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        timeout: aiohttp.ClientTimeout = _DEFAULT_TIMEOUT,
        **kwargs: Any,
    ) -> aiohttp.ClientResponse:
        session = self._session_provider()
        try:
            resp = await session.request(method, self._url(path), timeout=timeout, **kwargs)
        except aiohttp.ClientError as exc:
            raise OEPLConnectionError(str(exc)) from exc
        except asyncio.TimeoutError as exc:
            raise OEPLTimeoutError(f"Request to {path} timed out") from exc

        if resp.status == 404:
            resp.release()
            raise OEPLNotFoundError(f"AP returned 404 for {path}")
        if resp.status != 200:
            try:
                body = await resp.text()
                raise OEPLResponseError(resp.status, body)
            finally:
                resp.release()

        return resp

    async def get_json(self, path: str) -> dict[str, Any]:
        resp = await self._request("GET", path)
        return cast(dict[str, Any], await resp.json(content_type=None))

    async def get_text(self, path: str) -> str:
        resp = await self._request("GET", path)
        body = await resp.text()
        _raise_if_error_body(body)
        return body

    async def get_raw(self, path: str) -> bytes | None:
        """Return raw response bytes, or None on 404."""
        try:
            resp = await self._request("GET", path)
            return await resp.read()
        except OEPLNotFoundError:
            return None

    async def get_bytes(self, path: str) -> bytes:
        """Return raw response bytes. Raises OEPLNotFoundError on 404 (unlike :meth:`get_raw`).

        For endpoints where a 404 is a genuine failure rather than an
        expected "not found yet" outcome (e.g. ``/backup_db``).
        """
        resp = await self._request("GET", path)
        return await resp.read()

    async def post_form(
        self,
        path: str,
        data: dict[str, Any],
        *,
        timeout: aiohttp.ClientTimeout | None = None,
    ) -> str:
        resp = await self._request("POST", path, data=data, timeout=timeout or _DEFAULT_TIMEOUT)
        body = await resp.text()
        _raise_if_error_body(body)
        return body

    async def delete_form(self, path: str, data: dict[str, Any]) -> str:
        """DELETE with a form-encoded body (SPIFFSEditor's ``/edit`` delete)."""
        resp = await self._request("DELETE", path, data=data)
        body = await resp.text()
        _raise_if_error_body(body)
        return body

    async def post_json(self, path: str, payload: dict[str, Any]) -> str:
        resp = await self._request("POST", path, json=payload)
        body = await resp.text()
        _raise_if_error_body(body)
        return body

    async def get_json_any(self, path: str) -> Any:
        """Like :meth:`get_json`, but for endpoints whose body is not a JSON object

        (e.g. ``/edit?list=`` returns a bare JSON array).
        """
        resp = await self._request("GET", path)
        return await resp.json(content_type=None)

    async def post_multipart(self, path: str, fields: dict[str, Any], *, check_body: bool = False) -> None:
        """POST multipart/form-data; retries up to 3x on timeout with exponential backoff.

        Builds the body by hand instead of using ``aiohttp.FormData``. The AP's
        ESPAsyncWebServer multipart parser treats *any* part carrying a
        Content-Type header as a file part; ``aiohttp.FormData`` emits a
        ``Content-Type: text/plain; charset=utf-8`` header on every text field,
        so none of them register via ``hasParam()`` on the AP and the request is
        silently discarded (bare 200, empty body). Text fields here therefore get
        exactly one header line (``Content-Disposition``, no Content-Type); only
        file parts (tuple values) carry a Content-Type. Callers must order
        *fields* with text fields first and file fields last, since the AP parses
        params before the file part completes.

        Args:
            check_body: When ``True``, apply the same "200 + Error... body is
                actually a failure" heuristic used by :meth:`post_form`/
                :meth:`get_text` (see :func:`_raise_if_error_body`). Defaults
                to ``False`` since ``/imgupload`` returns an empty body on
                success and would need no check at all; callers whose
                endpoint can return a 200-with-error-text body (e.g.
                ``/restore_db``, ``/littlefs_put``) should opt in.
        """
        boundary = uuid4().hex
        body = self._encode_multipart(fields, boundary)
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}

        backoff = _UPLOAD_BACKOFF
        for attempt in range(1, _MAX_UPLOAD_RETRIES + 1):
            try:
                resp = await self._request("POST", path, data=body, headers=headers, timeout=_UPLOAD_TIMEOUT)
                if check_body:
                    _raise_if_error_body(await resp.text())
                return
            except OEPLTimeoutError:
                if attempt >= _MAX_UPLOAD_RETRIES:
                    raise
                await asyncio.sleep(backoff)
                backoff *= 2

    @staticmethod
    def _encode_multipart(fields: dict[str, Any], boundary: str) -> bytes:
        parts: list[bytes] = []
        for key, value in fields.items():
            if isinstance(value, tuple):
                # (filename, data, content_type)
                filename, data, content_type = value
                parts.append(
                    f"--{boundary}\r\n"
                    f'Content-Disposition: form-data; name="{key}"; filename="{filename}"\r\n'
                    f"Content-Type: {content_type}\r\n\r\n".encode()
                    + data
                    + b"\r\n"
                )
            else:
                parts.append(
                    (f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n').encode()
                )
        parts.append(f"--{boundary}--\r\n".encode())
        return b"".join(parts)
