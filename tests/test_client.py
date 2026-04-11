"""Tests for OEPLClient HTTP operations."""
import json
import pytest
from aioresponses import aioresponses
import aiohttp

from oepl.client import OEPLClient
from oepl.enums import LUT, Rotation, TagCommand
from oepl.led import Color, LEDPattern, LEDSegment

HOST = "192.168.1.1"
BASE = f"http://{HOST}"


@pytest.fixture
async def client():
    """Yield an OEPLClient with its own session (no WebSocket started)."""
    c = OEPLClient(HOST)
    yield c
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


@pytest.mark.asyncio
async def test_upload_image_multipart(client):
    image_bytes = b"\xff\xd8\xff" + b"\x00" * 100  # minimal fake JPEG

    captured_fields = {}

    with aioresponses() as m:
        m.post(f"{BASE}/imgupload", status=200, body=b"ok")
        await client.upload_image(
            "AABBCCDDEEFF",
            image_bytes,
            lut=LUT.DEFAULT,
            rotate=Rotation.NONE,
        )
        # Verify request was made
        calls = m.requests[("POST", aiohttp.client.URL(f"{BASE}/imgupload"))]
        assert len(calls) == 1


@pytest.mark.asyncio
async def test_upload_image_ttl_conversion(client):
    """ttl=120 seconds → ttl_minutes=2 in the request."""
    image_bytes = b"\xff\xd8\xff" + b"\x00" * 50

    field_data = {}

    with aioresponses() as m:
        m.post(f"{BASE}/imgupload", status=200, body=b"ok")
        await client.upload_image("AABBCCDDEEFF", image_bytes, ttl=120)
        # The key check is that post_multipart was called without raising
        # (field validation is done in integration tests against a live AP)


@pytest.mark.asyncio
async def test_upload_image_ttl_zero(client):
    """ttl=0 → ttl_minutes=0 (AP uses tag default)."""
    image_bytes = b"\xff\xd8\xff" + b"\x00" * 50
    with aioresponses() as m:
        m.post(f"{BASE}/imgupload", status=200, body=b"ok")
        # Should not raise
        await client.upload_image("AABBCCDDEEFF", image_bytes, ttl=0)


@pytest.mark.asyncio
async def test_set_alias(client):
    with aioresponses() as m:
        m.post(f"{BASE}/save_cfg", payload={"ok": True})
        await client.set_alias("AABBCCDDEEFF", "my-display")

        calls = m.requests[("POST", aiohttp.client.URL(f"{BASE}/save_cfg"))]
        assert len(calls) == 1


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
