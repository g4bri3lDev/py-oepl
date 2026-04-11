"""Low-level async HTTP client for the OpenDisplay AP."""
from __future__ import annotations

import asyncio
from typing import Any

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


class _HTTPClient:
    """Wraps aiohttp.ClientSession with AP-specific error mapping."""

    def __init__(self, host: str, session: aiohttp.ClientSession) -> None:
        self._base = f"http://{host}"
        self._session = session

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
        try:
            resp = await self._session.request(
                method, self._url(path), timeout=timeout, **kwargs
            )
        except aiohttp.ClientError as exc:
            raise OEPLConnectionError(str(exc)) from exc
        except asyncio.TimeoutError as exc:
            raise OEPLTimeoutError(f"Request to {path} timed out") from exc

        if resp.status == 404:
            raise OEPLNotFoundError(f"AP returned 404 for {path}")
        if resp.status != 200:
            body = await resp.text()
            raise OEPLResponseError(resp.status, body)

        return resp

    async def get_json(self, path: str) -> dict[str, Any]:
        resp = await self._request("GET", path)
        return await resp.json(content_type=None)

    async def get_text(self, path: str) -> str:
        resp = await self._request("GET", path)
        return await resp.text()

    async def get_raw(self, path: str) -> bytes | None:
        """Return raw response bytes, or None on 404."""
        try:
            resp = await self._request("GET", path)
            return await resp.read()
        except OEPLNotFoundError:
            return None

    async def post_form(self, path: str, data: dict[str, Any]) -> str:
        resp = await self._request("POST", path, data=data)
        return await resp.text()

    async def post_multipart(self, path: str, fields: dict[str, Any]) -> None:
        """POST multipart/form-data; retries up to 3× on timeout with exponential backoff."""
        backoff = _UPLOAD_BACKOFF
        for attempt in range(1, _MAX_UPLOAD_RETRIES + 1):
            form = aiohttp.FormData()
            for key, value in fields.items():
                if isinstance(value, tuple):
                    # (filename, data, content_type)
                    form.add_field(key, value[1], filename=value[0], content_type=value[2])
                else:
                    form.add_field(key, str(value))

            try:
                await self._request(
                    "POST", path, data=form, timeout=_UPLOAD_TIMEOUT
                )
                return
            except OEPLTimeoutError:
                if attempt >= _MAX_UPLOAD_RETRIES:
                    raise
                await asyncio.sleep(backoff)
                backoff *= 2
