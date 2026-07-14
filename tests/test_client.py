"""Tests for OEPLClient HTTP operations."""

import warnings

import aiohttp
import pytest
from aioresponses import aioresponses

from oepl.client import OEPLClient
from oepl.enums import LUT, Rotation, TagCommand
from oepl.exceptions import OEPLResponseError
from oepl.led import Color, LEDPattern, LEDSegment

HOST = "192.168.1.1"
BASE = f"http://{HOST}"


@pytest.fixture
async def client():
    """Yield an OEPLClient with its own session (no WebSocket started)."""
    c = OEPLClient(HOST)
    yield c
    if c._session is not None:
        await c._session.close()


@pytest.mark.asyncio
async def test_get_tags_single_page(client, tag_dict):
    with aioresponses() as m:
        m.get(f"{BASE}/get_db", payload={"tags": [tag_dict], "continu": 0})
        tags = await client.get_tags()

    assert len(tags) == 1
    assert tags[0].mac == "AABBCCDDEEFF"
    assert client._tags["AABBCCDDEEFF"].alias == "test-tag"


@pytest.mark.asyncio
async def test_get_tags_paginated(client, tag_dict):
    page2_dict = dict(tag_dict, mac="001122334455", alias="tag-2")
    with aioresponses() as m:
        m.get(f"{BASE}/get_db", payload={"tags": [tag_dict], "continu": 1})
        m.get(f"{BASE}/get_db?pos=1", payload={"tags": [page2_dict], "continu": 0})
        tags = await client.get_tags()

    assert len(tags) == 2
    macs = {t.mac for t in tags}
    assert "AABBCCDDEEFF" in macs
    assert "001122334455" in macs


def _get_upload_call(m):
    """Return the (args, kwargs) of the single recorded /imgupload POST."""
    calls = m.requests[("POST", aiohttp.client.URL(f"{BASE}/imgupload"))]
    assert len(calls) == 1
    return calls[0]


def _parse_multipart(body: bytes, content_type: str) -> tuple[dict[str, bytes], dict[str, bytes]]:
    """Split a hand-built multipart body into (text_fields, file_parts).

    text_fields: name -> raw part bytes (everything after the blank line, minus
        trailing CRLF) for parts with no Content-Type header.
    file_parts: name -> raw part bytes for parts that do carry a Content-Type
        header (used to check the JPEG payload / content-type).
    """
    boundary = content_type.split("boundary=")[1].strip()
    delimiter = f"--{boundary}".encode()
    raw_parts = body.split(delimiter)
    # First element is empty (before the first boundary), last is "--\r\n".
    text_fields: dict[str, bytes] = {}
    file_parts: dict[str, bytes] = {}
    file_headers: dict[str, str] = {}
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
            file_headers[name] = next(h for h in header_lines if h.startswith("Content-Type"))
        else:
            assert len(header_lines) == 1, f"text part {name!r} has extra headers: {header_lines}"
            text_fields[name] = payload
    file_parts["__headers__"] = file_headers  # type: ignore[assignment]
    return text_fields, file_parts


@pytest.mark.asyncio
async def test_upload_image_pil_default(client):
    """Default call with a PIL image: only mac/contentmode/ttl/image (+dither=0 if dithered)."""
    from PIL import Image

    from oepl.client import dither_image

    image = Image.new("RGB", (4, 4), color="red")

    with aioresponses() as m:
        m.post(f"{BASE}/imgupload", status=200, body=b"")
        await client.upload_image("aabbccddeeff", image)

        args, kwargs = _get_upload_call(m)
        body = kwargs["data"]
        content_type = kwargs["headers"]["Content-Type"]
        assert content_type.startswith("multipart/form-data; boundary=")
        assert isinstance(body, (bytes, bytearray))

        text_fields, file_parts = _parse_multipart(body, content_type)

        assert text_fields["mac"] == b"AABBCCDDEEFF"
        assert text_fields["contentmode"] == b"24"
        assert text_fields["ttl"] == b"0"

        for absent in ("rotate", "lut", "invert", "alias", "preloadtype", "preloadlut"):
            assert absent not in text_fields

        if dither_image is not None:
            assert text_fields["dither"] == b"0"
        else:
            assert "dither" not in text_fields

        assert file_parts["__headers__"]["image"] == "Content-Type: image/jpeg"
        assert file_parts["image"].startswith(b"\xff\xd8")


@pytest.mark.asyncio
async def test_upload_image_explicit_optional_fields(client):
    image_bytes = b"\xff\xd8\xff" + b"\x00" * 50

    with aioresponses() as m:
        m.post(f"{BASE}/imgupload", status=200, body=b"")
        await client.upload_image(
            "AABBCCDDEEFF",
            image_bytes,
            rotate=Rotation.R90,
            lut=LUT.FAST,
            invert=True,
            alias="x",
            dither=2,
        )

        _args, kwargs = _get_upload_call(m)
        text_fields, _file_parts = _parse_multipart(kwargs["data"], kwargs["headers"]["Content-Type"])

        assert text_fields["rotate"] == b"1"
        assert text_fields["lut"] == b"3"
        assert text_fields["invert"] == b"1"
        assert text_fields["alias"] == b"x"
        assert text_fields["dither"] == b"2"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("ttl", "expected"),
    [(120, b"2"), (0, b"0"), (30, b"1")],
)
async def test_upload_image_ttl_conversion(client, ttl, expected):
    image_bytes = b"\xff\xd8\xff" + b"\x00" * 50

    with aioresponses() as m:
        m.post(f"{BASE}/imgupload", status=200, body=b"")
        await client.upload_image("AABBCCDDEEFF", image_bytes, ttl=ttl)

        _args, kwargs = _get_upload_call(m)
        text_fields, _file_parts = _parse_multipart(kwargs["data"], kwargs["headers"]["Content-Type"])
        assert text_fields["ttl"] == expected


@pytest.mark.asyncio
async def test_upload_image_raw_bytes_passthrough(client):
    """Raw bytes input is sent byte-identical, with no dither field."""
    image_bytes = b"\xff\xd8\xff" + b"\x00" * 123

    with aioresponses() as m:
        m.post(f"{BASE}/imgupload", status=200, body=b"")
        await client.upload_image("AABBCCDDEEFF", image_bytes)

        _args, kwargs = _get_upload_call(m)
        text_fields, file_parts = _parse_multipart(kwargs["data"], kwargs["headers"]["Content-Type"])
        assert file_parts["image"] == image_bytes
        assert "dither" not in text_fields


@pytest.mark.asyncio
async def test_upload_image_body_ends_with_closing_boundary(client):
    image_bytes = b"\xff\xd8\xff" + b"\x00" * 10

    with aioresponses() as m:
        m.post(f"{BASE}/imgupload", status=200, body=b"")
        await client.upload_image("AABBCCDDEEFF", image_bytes)

        _args, kwargs = _get_upload_call(m)
        body = kwargs["data"]
        content_type = kwargs["headers"]["Content-Type"]
        boundary = content_type.split("boundary=")[1].strip()
        assert isinstance(body, bytes)
        assert body.endswith(f"--{boundary}--\r\n".encode())


@pytest.mark.asyncio
async def test_set_alias(client):
    with aioresponses() as m:
        m.post(f"{BASE}/save_cfg", status=200, body="Ok, saved")
        await client.set_alias("AABBCCDDEEFF", "my-display")

        calls = m.requests[("POST", aiohttp.client.URL(f"{BASE}/save_cfg"))]
        assert len(calls) == 1


@pytest.mark.asyncio
async def test_set_alias_raises_on_ap_error_body(client):
    """The AP reports failures as HTTP 200 with an "Error..." body; must surface as an exception."""
    with aioresponses() as m:
        m.post(f"{BASE}/save_cfg", status=200, body="Error while saving: mac not found")
        with pytest.raises(OEPLResponseError) as exc_info:
            await client.set_alias("DEADBEEFDEAD", "my-display")

    assert exc_info.value.status == 200
    assert exc_info.value.body == "Error while saving: mac not found"


@pytest.mark.asyncio
async def test_send_tag_cmd(client):
    with aioresponses() as m:
        m.post(f"{BASE}/tag_cmd", payload={"ok": True})
        await client.send_tag_cmd("AABBCCDDEEFF", TagCommand.REFRESH)

        calls = m.requests[("POST", aiohttp.client.URL(f"{BASE}/tag_cmd"))]
        assert len(calls) == 1


@pytest.mark.asyncio
async def test_set_led(client):
    pattern = LEDPattern([LEDSegment(Color(255, 0, 0))])
    encoded = pattern.encode()
    assert len(encoded) == 24

    with aioresponses() as m:
        m.get(
            f"{BASE}/led_flash?mac=AABBCCDDEEFF&pattern={encoded}",
            status=200,
            body=b"ok",
        )
        await client.set_led("AABBCCDDEEFF", pattern)


@pytest.mark.asyncio
async def test_get_image_raw_404(client):
    with aioresponses() as m:
        m.get(f"{BASE}/current/AABBCCDDEEFF.raw", status=404)
        result = await client.get_image_raw("AABBCCDDEEFF")

    assert result is None


@pytest.mark.asyncio
async def test_get_sysinfo(client):
    sysinfo = {
        "alias": "My AP",
        "env": "OpenDisplay_Mini_AP_v4",
        "buildversion": "1.0.0",
        "buildtime": "2024-01-01",
        "ap_version": 20,
        "psramsize": 8000000,
        "flashsize": 16000000,
        "hasC6": 1,
        "hasH2": 0,
        "rollback": False,
    }
    with aioresponses() as m:
        m.get(f"{BASE}/sysinfo", payload=sysinfo)
        info = await client.get_sysinfo()

    assert info.alias == "My AP"
    assert info.env == "OpenDisplay_Mini_AP_v4"
    assert info.ap_version == "20"
    assert info.has_c6 is True
    assert info.has_h2 is False
    assert info.can_rollback is False


@pytest.mark.asyncio
async def test_tag_update_callback(client, tag_dict):
    """on_tag_update callback fires when get_tags populates the cache."""
    received = []
    client.on_tag_update(received.append)

    with aioresponses() as m:
        m.get(f"{BASE}/get_db", payload={"tags": [tag_dict], "continu": 0})
        await client.get_tags()

    assert len(received) == 1
    assert received[0].mac == "AABBCCDDEEFF"


@pytest.mark.asyncio
async def test_unsubscribe_callback(client, tag_dict):
    """Unsubscribe callable removes the callback."""
    received = []
    unsub = client.on_tag_update(received.append)
    unsub()

    with aioresponses() as m:
        m.get(f"{BASE}/get_db", payload={"tags": [tag_dict], "continu": 0})
        await client.get_tags()

    assert len(received) == 0


# ----------------------------------------------------------------------
# Session lifecycle (HA inject-websession compliance)
# ----------------------------------------------------------------------


def test_sync_construction_does_not_create_session():
    """Constructing a client outside a running event loop must not create a session."""
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        c = OEPLClient(HOST)

    assert c._session is None
    assert c._owned_session is True


@pytest.mark.asyncio
async def test_owned_session_created_lazily_on_first_use(tag_dict):
    c = OEPLClient(HOST)
    assert c._session is None

    with aioresponses() as m:
        m.get(f"{BASE}/get_db", payload={"tags": [tag_dict], "continu": 0})
        await c.get_tags()

    assert c._session is not None
    assert c._owned_session is True
    await c.disconnect()
    assert c._session is None


@pytest.mark.asyncio
async def test_owned_session_closed_after_disconnect(tag_dict):
    c = OEPLClient(HOST)
    with aioresponses() as m:
        m.get(f"{BASE}/get_db", payload={"tags": [tag_dict], "continu": 0})
        await c.get_tags()

    session = c.session
    await c.disconnect()
    assert session.closed is True


@pytest.mark.asyncio
async def test_injected_session_never_created_closed_or_mutated(tag_dict):
    async with aiohttp.ClientSession() as injected:
        c = OEPLClient(HOST, session=injected)
        assert c._session is injected
        assert c._owned_session is False

        with aioresponses() as m:
            m.get(f"{BASE}/get_db", payload={"tags": [tag_dict], "continu": 0})
            await c.get_tags()

        assert c.session is injected

        await c.disconnect()
        assert injected.closed is False
        assert c._session is injected
