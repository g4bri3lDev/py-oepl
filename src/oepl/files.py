"""Files namespace — filesystem access on the AP.

Wraps two independent firmware handlers that both operate on the AP's LittleFS
content filesystem:

- ``/edit`` (``SPIFFSEditor.cpp``): a generic file manager (list/download/delete
  + its own upload/edit verbs, unused here — see :meth:`Files.upload`).
- ``/check_file`` and ``/littlefs_put`` (``ota.cpp``): a minimal hash-check +
  raw-upload pair, originally meant for OTA-adjacent file staging but usable
  for arbitrary files.

Path handling is **not** consistent between the two halves (verified against
firmware source, not docs):

- ``/edit``'s GET (``list``/``download``) and DELETE handlers all prepend a
  ``/`` to whatever path you give them internally
  (``_fs.open("/" + request->arg(...))``, ``SPIFFSEditor.cpp``). Passing an
  already-rooted path (e.g. ``"/foo.bin"``) would double it to ``"//foo.bin"``,
  so :meth:`list`, :meth:`download`, and :meth:`delete` strip a leading slash
  before building the query/form value.
- ``/check_file`` and ``/littlefs_put`` use the path exactly as given, with
  **no** normalization (``ota.cpp`` opens ``request->getParam("path")->value()``
  verbatim). :meth:`check` and :meth:`upload` therefore add a leading slash if
  one isn't already present, so paths from :meth:`list` (which are unrooted)
  work interchangeably across all four methods.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ._http import _HTTPClient


def _strip_leading_slash(path: str) -> str:
    return path[1:] if path.startswith("/") else path


def _ensure_leading_slash(path: str) -> str:
    return path if path.startswith("/") else f"/{path}"


@dataclass
class FileEntry:
    """One entry from a ``/edit?list=`` directory listing.

    Built from ``SPIFFSEditor::listFilesRecursively`` (non-recursive mode):
    directory entries are serialized as ``{"type":"dir","name":...}`` with no
    ``size`` key at all (hence ``size`` defaults to ``None``); file entries
    always carry ``size``.
    """

    type: str
    name: str
    size: int | None = None
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FileEntry":
        return cls(
            type=str(data.get("type", "")),
            name=str(data.get("name", "")),
            size=data.get("size"),
            raw=dict(data),
        )


class Files:
    """Filesystem access on the AP. Use :attr:`OEPLClient.files`, don't construct directly.

    Holds no session of its own — it's a thin wrapper around the client's
    shared :class:`~oepl._http._HTTPClient`.
    """

    def __init__(self, http: _HTTPClient) -> None:
        self._http = http

    async def list(self, dir: str = "/") -> list[FileEntry]:
        """List files/directories directly under *dir* via ``/edit?list=``.

        Non-recursive (the AP also supports a ``recursive`` flag, not exposed
        here since its recursion silently skips ``/www``, ``/tagtypes``, and
        ``/current`` — see ``listFilesRecursively``, ``SPIFFSEditor.cpp:46``).
        """
        items = await self._http.get_json_any(f"edit?list={dir}")
        return [FileEntry.from_dict(item) for item in items]

    async def download(self, path: str) -> bytes | None:
        """Download raw file bytes via ``/edit?download=``.

        Returns ``None`` if the AP 404s (the file doesn't exist, or is a
        directory — ``SPIFFSEditor::canHandle`` refuses both before the
        request ever reaches a response, so the built-in ``onNotFound`` 404
        handler answers instead).
        """
        return await self._http.get_raw(f"edit?download={_strip_leading_slash(path)}")

    async def upload(self, path: str, data: bytes) -> None:
        """Write *data* to *path* on the AP's filesystem via ``/littlefs_put``.

        Deliberately uses ``/littlefs_put`` (``ota.cpp:117``) rather than
        ``/edit``'s own POST upload verb: the ``/edit`` upload requires the
        multipart file field to be named ``data`` and its filename to be the
        target path (``SPIFFSEditor::handleUpload``/``handleRequest``), and
        its success response is a post-hoc ``_fs.exists()`` check rather than
        a real write-error signal. ``/littlefs_put`` streams straight to disk
        chunk-by-chunk and explicitly reports ``507`` ("Error. Disk full?")
        on a failed write, which is more useful. Its multipart body needs a
        text field ``path`` naming the destination (read once, before the
        first chunk of the file part — ``handleLittleFSUpload``'s
        ``index == 0`` branch) followed by the file part itself; both are
        sent through :meth:`_HTTPClient.post_multipart`, which already
        requires/handles that field ordering.
        """
        fields: dict[str, Any] = {
            "path": _ensure_leading_slash(path),
            "data": ("upload.bin", data, "application/octet-stream"),
        }
        await self._http.post_multipart("littlefs_put", fields)

    async def delete(self, path: str) -> None:
        """Delete *path* via ``HTTP DELETE /edit`` with a ``path`` form field.

        Firmware quirk: as long as the ``path`` field is present, the AP
        responds ``200`` **unconditionally** — ``SPIFFSEditor.cpp:98-104``
        calls ``_fs.remove(...)`` but never checks (or reports) whether it
        actually succeeded, and doesn't 404/error for a path that never
        existed. A ``200`` here therefore only means the request was well
        formed, not that a file was actually removed.
        """
        await self._http.delete_form("edit", {"path": _strip_leading_slash(path)})

    async def check(self, path: str) -> dict[str, Any] | None:
        """Query size + MD5 of *path* via ``/check_file?path=``.

        Firmware quirk: unlike most other AP endpoints, this one **never**
        404s for a missing file (``ota.cpp:73-107``) — it opens the file,
        and if that fails, still responds ``200`` with
        ``{"filesize": 0, "md5": ""}``. This method detects that sentinel
        (an empty ``md5``) and returns ``None`` in that case instead, since a
        genuinely empty *existing* file still hashes to
        ``"d41d8cd98f00b204e9800998ecf8427e"`` (MD5 of zero bytes), never the
        empty string. On success returns the parsed
        ``{"filesize": int, "md5": str}`` dict as-is.
        """
        data: dict[str, Any] = await self._http.get_json_any(f"check_file?path={_ensure_leading_slash(path)}")
        if not data.get("md5"):
            return None
        return data
