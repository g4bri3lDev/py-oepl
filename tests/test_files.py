"""Tests for the Files namespace (client.files) — /edit, /check_file, /littlefs_put."""

import aiohttp
import pytest
from aioresponses import aioresponses

from oepl.client import OEPLClient
from oepl.files import FileEntry

HOST = "192.168.1.1"
BASE = f"http://{HOST}"


@pytest.fixture
async def client():
    c = OEPLClient(HOST)
    yield c
    if c._session is not None:
        await c._session.close()


def _parse_multipart(body: bytes, content_type: str) -> tuple[dict[str, bytes], dict[str, bytes]]:
    """Split a hand-built multipart body into (text_fields, file_parts)."""
    boundary = content_type.split("boundary=")[1].strip()
    delimiter = f"--{boundary}".encode()
    raw_parts = body.split(delimiter)
    text_fields: dict[str, bytes] = {}
    file_parts: dict[str, bytes] = {}
    for raw in raw_parts:
        raw = raw.strip(b"\r\n")
        if not raw or raw == b"--":
            continue
        headers_blob, _, payload = raw.partition(b"\r\n\r\n")
        headers_text = headers_blob.decode()
        header_lines = [h for h in headers_text.split("\r\n") if h]
        disposition = next(h for h in header_lines if h.startswith("Content-Disposition"))
        name = disposition.split('name="')[1].split('"')[0]
        if any(h.startswith("Content-Type") for h in header_lines):
            file_parts[name] = payload
        else:
            text_fields[name] = payload
    return text_fields, file_parts


# ---------------------------------------------------------------------
# list()
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_parses_firmware_shaped_listing(client):
    """Fixture built from SPIFFSEditor::listFilesRecursively's non-recursive serialization."""
    payload = (
        b'[{"type":"dir","name":"current"},'
        b'{"type":"file","name":"config.json","size":128},'
        b'{"type":"file","name":"empty.bin","size":0}]'
    )
    with aioresponses() as m:
        m.get(f"{BASE}/edit?list=/", status=200, body=payload, content_type="application/json")
        entries = await client.files.list()

    assert entries == [
        FileEntry(type="dir", name="current", size=None, raw={"type": "dir", "name": "current"}),
        FileEntry(type="file", name="config.json", size=128, raw={"type": "file", "name": "config.json", "size": 128}),
        FileEntry(type="file", name="empty.bin", size=0, raw={"type": "file", "name": "empty.bin", "size": 0}),
    ]


@pytest.mark.asyncio
async def test_list_custom_dir_query_param(client):
    with aioresponses() as m:
        m.get(f"{BASE}/edit?list=/sub", status=200, body=b"[]", content_type="application/json")
        result = await client.files.list("/sub")
    assert result == []


@pytest.mark.asyncio
async def test_list_unrooted_dir_gets_leading_slash(client):
    """The /edit list branch passes its param verbatim to _fs.open(), and the ESP32 VFS
    rejects unrooted paths (the AP silently lists nothing) -- so list() must root the path.
    Subdirectory FileEntry.name values are unrooted, making list(entry.name) the common case."""
    with aioresponses() as m:
        m.get(f"{BASE}/edit?list=/sub", status=200, body=b"[]", content_type="application/json")
        result = await client.files.list("sub")
    assert result == []


# ---------------------------------------------------------------------
# download()
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_download_strips_leading_slash_and_returns_bytes(client):
    with aioresponses() as m:
        m.get(f"{BASE}/edit?download=foo.bin", status=200, body=b"\x01\x02\x03")
        result = await client.files.download("/foo.bin")
    assert result == b"\x01\x02\x03"


@pytest.mark.asyncio
async def test_download_no_leading_slash_passthrough(client):
    with aioresponses() as m:
        m.get(f"{BASE}/edit?download=foo.bin", status=200, body=b"data")
        result = await client.files.download("foo.bin")
    assert result == b"data"


@pytest.mark.asyncio
async def test_download_404_returns_none(client):
    with aioresponses() as m:
        m.get(f"{BASE}/edit?download=missing.bin", status=404)
        result = await client.files.download("missing.bin")
    assert result is None


@pytest.mark.asyncio
async def test_download_filename_with_space_is_url_encoded(client):
    """A raw space in the query string would corrupt it -- must be percent-encoded.

    aioresponses only matches the mock below (registered against the percent-encoded
    path) if the client actually sent an encoded request; an unencoded "my file.bin"
    would fail to match and raise a connection error instead.
    """
    with aioresponses() as m:
        m.get(f"{BASE}/edit?download=my%20file.bin", status=200, body=b"data")
        result = await client.files.download("my file.bin")
    assert result == b"data"


@pytest.mark.asyncio
async def test_list_dir_with_ampersand_is_url_encoded(client):
    """A raw '&' would be parsed as a query-param separator -- must be percent-encoded.

    See test_download_filename_with_space_is_url_encoded for why matching the mock
    at all is the assertion here.
    """
    with aioresponses() as m:
        m.get(f"{BASE}/edit?list=/foo%26bar", status=200, body=b"[]", content_type="application/json")
        result = await client.files.list("/foo&bar")
    assert result == []


@pytest.mark.asyncio
async def test_check_path_with_space_is_url_encoded(client):
    with aioresponses() as m:
        m.get(
            f"{BASE}/check_file?path=/my%20file.bin",
            status=200,
            payload={"filesize": 1, "md5": "abcd"},
        )
        result = await client.files.check("/my file.bin")
    assert result == {"filesize": 1, "md5": "abcd"}


# ---------------------------------------------------------------------
# upload()
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_posts_littlefs_put_with_path_and_file(client):
    with aioresponses() as m:
        m.post(f"{BASE}/littlefs_put", status=200, body="Ok, file written")
        await client.files.upload("/www/foo.bin", b"\xde\xad\xbe\xef")

    calls = m.requests[("POST", aiohttp.client.URL(f"{BASE}/littlefs_put"))]
    assert len(calls) == 1
    _args, kwargs = calls[0]
    body = kwargs["data"]
    content_type = kwargs["headers"]["Content-Type"]
    assert content_type.startswith("multipart/form-data; boundary=")

    text_fields, file_parts = _parse_multipart(body, content_type)
    assert text_fields["path"] == b"/www/foo.bin"
    assert file_parts["data"] == b"\xde\xad\xbe\xef"


@pytest.mark.asyncio
async def test_upload_raises_on_200_error_body(client):
    """upload() opts into post_multipart's check_body=True: /littlefs_put can return a 200
    body reporting a write failure (e.g. disk full), which must not be swallowed."""
    from oepl.exceptions import OEPLResponseError

    with aioresponses() as m:
        m.post(f"{BASE}/littlefs_put", status=200, body="Error. Disk full?")
        with pytest.raises(OEPLResponseError):
            await client.files.upload("/www/foo.bin", b"\xde\xad\xbe\xef")


@pytest.mark.asyncio
async def test_upload_adds_leading_slash(client):
    with aioresponses() as m:
        m.post(f"{BASE}/littlefs_put", status=200, body="Ok, file written")
        await client.files.upload("www/foo.bin", b"x")

    calls = m.requests[("POST", aiohttp.client.URL(f"{BASE}/littlefs_put"))]
    _args, kwargs = calls[0]
    text_fields, _ = _parse_multipart(kwargs["data"], kwargs["headers"]["Content-Type"])
    assert text_fields["path"] == b"/www/foo.bin"


# ---------------------------------------------------------------------
# delete()
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_uses_delete_verb_with_path_form_field(client):
    with aioresponses() as m:
        m.delete(f"{BASE}/edit", status=200, body="DELETE: foo.bin")
        await client.files.delete("/foo.bin")

    calls = m.requests[("DELETE", aiohttp.client.URL(f"{BASE}/edit"))]
    assert len(calls) == 1
    _args, kwargs = calls[0]
    assert kwargs["data"] == {"path": "foo.bin"}


# ---------------------------------------------------------------------
# check()
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_query_param_and_leading_slash(client):
    with aioresponses() as m:
        m.get(
            f"{BASE}/check_file?path=/www/foo.bin",
            status=200,
            payload={"filesize": 42, "md5": "abcd1234"},
        )
        result = await client.files.check("www/foo.bin")
    assert result == {"filesize": 42, "md5": "abcd1234"}


@pytest.mark.asyncio
async def test_check_missing_file_sentinel_returns_none(client):
    """Firmware quirk: missing file is a 200 with filesize=0, md5="" -- never a 404."""
    with aioresponses() as m:
        m.get(f"{BASE}/check_file?path=/nope.bin", status=200, payload={"filesize": 0, "md5": ""})
        result = await client.files.check("/nope.bin")
    assert result is None


@pytest.mark.asyncio
async def test_check_genuinely_empty_existing_file_is_not_none(client):
    """MD5 of zero bytes is a real (non-empty) hash, distinguishing this from the sentinel."""
    with aioresponses() as m:
        m.get(
            f"{BASE}/check_file?path=/empty.bin",
            status=200,
            payload={"filesize": 0, "md5": "d41d8cd98f00b204e9800998ecf8427e"},
        )
        result = await client.files.check("/empty.bin")
    assert result == {"filesize": 0, "md5": "d41d8cd98f00b204e9800998ecf8427e"}
