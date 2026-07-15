"""Tests for TagHandle, client.tag(), get_image, filtered subscriptions, and render-waiting."""

import asyncio
import json
import logging

import aiohttp
import pytest
from aioresponses import aioresponses
from PIL import Image

from oepl.client import OEPLClient
from oepl.exceptions import OEPLConnectionError, OEPLTimeoutError
from oepl.models import Tag
from oepl.tag_handle import TagHandle
from oepl.websocket import _WebSocketHandler

HOST = "192.168.1.1"
BASE = f"http://{HOST}"


@pytest.fixture
async def client():
    """Yield an OEPLClient with its own session (no WebSocket started)."""
    c = OEPLClient(HOST)
    yield c
    if c._session is not None:
        await c._session.close()


def _seed_tag(client, tag_dict, *, hw_type=4, mac="AABBCCDDEEFF", **overrides):
    """Populate client._tags directly, bypassing the network, for a known hw_type."""
    data = dict(tag_dict, hwType=hw_type, mac=mac, **overrides)
    tag = Tag.from_dict(data)
    client._tags[tag.mac] = tag
    return tag


# ----------------------------------------------------------------------
# client.tag() / TagHandle delegation
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_client_tag_returns_handle_with_upper_mac(client):
    handle = client.tag("aabbccddeeff")
    assert isinstance(handle, TagHandle)
    assert handle.mac == "AABBCCDDEEFF"


@pytest.mark.asyncio
async def test_tag_handle_refresh_delegates(client):
    with aioresponses() as m:
        m.post(f"{BASE}/tag_cmd", payload={"ok": True})
        await client.tag("aabbccddeeff").refresh()

    calls = m.requests[("POST", aiohttp.client.URL(f"{BASE}/tag_cmd"))]
    assert calls[0].kwargs["data"] == {"mac": "AABBCCDDEEFF", "cmd": "refresh"}


@pytest.mark.asyncio
async def test_tag_handle_clear_pending_delegates(client):
    with aioresponses() as m:
        m.post(f"{BASE}/tag_cmd", payload={"ok": True})
        await client.tag("aabbccddeeff").clear_pending()

    calls = m.requests[("POST", aiohttp.client.URL(f"{BASE}/tag_cmd"))]
    assert calls[0].kwargs["data"] == {"mac": "AABBCCDDEEFF", "cmd": "clear"}


@pytest.mark.asyncio
async def test_tag_handle_reboot_delegates(client):
    with aioresponses() as m:
        m.post(f"{BASE}/tag_cmd", payload={"ok": True})
        await client.tag("aabbccddeeff").reboot()

    calls = m.requests[("POST", aiohttp.client.URL(f"{BASE}/tag_cmd"))]
    assert calls[0].kwargs["data"] == {"mac": "AABBCCDDEEFF", "cmd": "reboot"}


@pytest.mark.asyncio
async def test_tag_handle_scan_delegates(client):
    with aioresponses() as m:
        m.post(f"{BASE}/tag_cmd", payload={"ok": True})
        await client.tag("aabbccddeeff").scan()

    calls = m.requests[("POST", aiohttp.client.URL(f"{BASE}/tag_cmd"))]
    assert calls[0].kwargs["data"] == {"mac": "AABBCCDDEEFF", "cmd": "scan"}


@pytest.mark.asyncio
async def test_tag_handle_deep_sleep_delegates(client):
    with aioresponses() as m:
        m.post(f"{BASE}/tag_cmd", payload={"ok": True})
        await client.tag("aabbccddeeff").deep_sleep()

    calls = m.requests[("POST", aiohttp.client.URL(f"{BASE}/tag_cmd"))]
    assert calls[0].kwargs["data"] == {"mac": "AABBCCDDEEFF", "cmd": "deepsleep"}


@pytest.mark.asyncio
async def test_tag_handle_delete_delegates(client):
    with aioresponses() as m:
        m.post(f"{BASE}/tag_cmd", status=200, body="Ok, done")
        await client.tag("aabbccddeeff").delete()

    calls = m.requests[("POST", aiohttp.client.URL(f"{BASE}/tag_cmd"))]
    assert calls[0].kwargs["data"] == {"mac": "AABBCCDDEEFF", "cmd": "del"}
    assert "AABBCCDDEEFF" not in client._tags


@pytest.mark.asyncio
async def test_tag_handle_set_alias_delegates(client):
    with aioresponses() as m:
        m.post(f"{BASE}/save_cfg", status=200, body="Ok, saved")
        await client.tag("aabbccddeeff").set_alias("my-alias")

    calls = m.requests[("POST", aiohttp.client.URL(f"{BASE}/save_cfg"))]
    assert calls[0].kwargs["data"] == {"mac": "AABBCCDDEEFF", "alias": "my-alias"}


@pytest.mark.asyncio
async def test_tag_handle_save_config_delegates(client):
    with aioresponses() as m:
        m.post(f"{BASE}/save_cfg", status=200, body="Ok, saved")
        await client.tag("aabbccddeeff").save_config(alias="x")

    calls = m.requests[("POST", aiohttp.client.URL(f"{BASE}/save_cfg"))]
    assert calls[0].kwargs["data"] == {"mac": "AABBCCDDEEFF", "alias": "x"}


@pytest.mark.asyncio
async def test_tag_handle_upload_json_delegates(client):
    with aioresponses() as m:
        m.post(f"{BASE}/jsonupload", status=200, body="Ok, saved")
        await client.tag("aabbccddeeff").upload_json({"a": 1}, ttl=60)

    calls = m.requests[("POST", aiohttp.client.URL(f"{BASE}/jsonupload"))]
    data = calls[0].kwargs["data"]
    assert data["mac"] == "AABBCCDDEEFF"
    assert data["json"] == '{"a": 1}'
    assert data["ttl"] == "60"


@pytest.mark.asyncio
async def test_tag_handle_upload_image_raw_bytes_delegates(client):
    image_bytes = b"\xff\xd8\xff" + b"\x00" * 10
    with aioresponses() as m:
        m.post(f"{BASE}/imgupload", status=200, body=b"")
        await client.tag("aabbccddeeff").upload_image(image_bytes)

    calls = m.requests[("POST", aiohttp.client.URL(f"{BASE}/imgupload"))]
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_tag_handle_info_reads_client_cache(client, tag_dict):
    assert client.tag("AABBCCDDEEFF").info is None

    with aioresponses() as m:
        m.get(f"{BASE}/get_db", payload={"tags": [tag_dict], "continu": 0})
        await client.get_tags()

    assert client.tag("aabbccddeeff").info.alias == "test-tag"


@pytest.mark.asyncio
async def test_tag_handle_get_type_fetches_tag_if_uncached(client, tag_dict, tagtype_04_dict):
    tag = dict(tag_dict, hwType=4)
    with aioresponses() as m:
        m.get(f"{BASE}/get_db?mac=AABBCCDDEEFF", payload={"tags": [tag]})
        m.get(f"{BASE}/tagtypes/04.json", payload=tagtype_04_dict)
        tag_type = await client.tag("aabbccddeeff").get_type()

    assert tag_type is not None
    assert (tag_type.width, tag_type.height) == (296, 152)


@pytest.mark.asyncio
async def test_tag_handle_get_type_unknown_tag_returns_none(client):
    with aioresponses() as m:
        m.get(f"{BASE}/get_db?mac=AABBCCDDEEFF", payload={"tags": []})
        tag_type = await client.tag("aabbccddeeff").get_type()

    assert tag_type is None


# ----------------------------------------------------------------------
# TagHandle.upload_image — fit modes
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_image_strict_mismatch_raises_with_both_sizes(client, tag_dict, tagtype_04_dict):
    _seed_tag(client, tag_dict)
    image = Image.new("RGB", (100, 100), "white")

    with aioresponses() as m:
        m.get(f"{BASE}/tagtypes/04.json", payload=tagtype_04_dict)
        with pytest.raises(ValueError) as exc_info:
            await client.tag("AABBCCDDEEFF").upload_image(image, fit="strict")

    message = str(exc_info.value)
    assert "(100, 100)" in message
    assert "(296, 152)" in message


@pytest.mark.asyncio
async def test_upload_image_contain_letterboxes_with_white_borders(client, tag_dict, tagtype_04_dict, monkeypatch):
    _seed_tag(client, tag_dict)
    image = Image.new("RGB", (100, 100), "red")
    captured = {}

    async def fake_upload(mac, img, **kwargs):
        captured["image"] = img

    monkeypatch.setattr(client, "upload_image", fake_upload)

    with aioresponses() as m:
        m.get(f"{BASE}/tagtypes/04.json", payload=tagtype_04_dict)
        await client.tag("AABBCCDDEEFF").upload_image(image, fit="contain")

    result = captured["image"]
    assert result.size == (296, 152)
    # Letterboxed onto a white canvas: corners must be padding, not the original red fill.
    assert result.getpixel((0, 0)) == (255, 255, 255)
    assert result.getpixel((295, 0)) == (255, 255, 255)


@pytest.mark.asyncio
async def test_upload_image_cover_crops_to_exact_size(client, tag_dict, tagtype_04_dict, monkeypatch):
    _seed_tag(client, tag_dict)
    image = Image.new("RGB", (100, 100), "red")
    captured = {}

    async def fake_upload(mac, img, **kwargs):
        captured["image"] = img

    monkeypatch.setattr(client, "upload_image", fake_upload)

    with aioresponses() as m:
        m.get(f"{BASE}/tagtypes/04.json", payload=tagtype_04_dict)
        await client.tag("AABBCCDDEEFF").upload_image(image, fit="cover")

    assert captured["image"].size == (296, 152)


@pytest.mark.asyncio
async def test_upload_image_matching_size_passes_through_unresized(client, tag_dict, tagtype_04_dict, monkeypatch):
    _seed_tag(client, tag_dict)
    image = Image.new("RGB", (296, 152), "blue")
    captured = {}

    async def fake_upload(mac, img, **kwargs):
        captured["image"] = img

    monkeypatch.setattr(client, "upload_image", fake_upload)

    with aioresponses() as m:
        m.get(f"{BASE}/tagtypes/04.json", payload=tagtype_04_dict)
        await client.tag("AABBCCDDEEFF").upload_image(image, fit="contain")

    # Same object passed straight through -- proves no resample/copy happened.
    assert captured["image"] is image


@pytest.mark.asyncio
async def test_upload_image_unknown_tag_strict_raises(client):
    image = Image.new("RGB", (100, 100), "white")
    with aioresponses() as m:
        m.get(f"{BASE}/get_db?mac=AABBCCDDEEFF", payload={"tags": []})
        with pytest.raises(ValueError):
            await client.tag("AABBCCDDEEFF").upload_image(image, fit="strict")


@pytest.mark.asyncio
async def test_upload_image_unknown_tag_contain_passes_through_with_warning(client, monkeypatch, caplog):
    image = Image.new("RGB", (100, 100), "white")
    captured = {}

    async def fake_upload(mac, img, **kwargs):
        captured["image"] = img

    monkeypatch.setattr(client, "upload_image", fake_upload)

    with aioresponses() as m, caplog.at_level(logging.WARNING):
        m.get(f"{BASE}/get_db?mac=AABBCCDDEEFF", payload={"tags": []})
        await client.tag("AABBCCDDEEFF").upload_image(image, fit="contain")

    assert captured["image"] is image
    assert any("unknown" in rec.message.lower() for rec in caplog.records)


@pytest.mark.asyncio
async def test_upload_image_raw_bytes_skips_size_validation(client, tag_dict):
    """Raw bytes input is never size-checked, even with fit='strict' and a known mismatched type."""
    _seed_tag(client, tag_dict)
    image_bytes = b"\xff\xd8\xff" + b"\x00" * 5
    captured = {}

    async def fake_upload(mac, img, **kwargs):
        captured["image"] = img

    client.upload_image = fake_upload
    # No aioresponses mock registered at all -- if this tried to fetch the tag type
    # over the network, the test would fail with a "no mock" connection error.
    await client.tag("AABBCCDDEEFF").upload_image(image_bytes, fit="strict")

    assert captured["image"] == image_bytes


# ----------------------------------------------------------------------
# client.get_image
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_image_end_to_end(client, tag_dict, tagtype_04_dict):
    tag = dict(tag_dict, hwType=4)
    bytes_per_row = (296 + 7) // 8
    plane_size = bytes_per_row * 152
    raw = b"\xff" * plane_size + b"\x00" * plane_size  # all-white bitmap

    with aioresponses() as m:
        m.get(f"{BASE}/get_db?mac=AABBCCDDEEFF", payload={"tags": [tag]})
        m.get(f"{BASE}/tagtypes/04.json", payload=tagtype_04_dict)
        m.get(f"{BASE}/current/AABBCCDDEEFF.raw", status=200, body=raw)
        img = await client.get_image("AABBCCDDEEFF")

    assert img is not None
    assert img.size == (296, 152)


@pytest.mark.asyncio
async def test_get_image_uses_cached_tag(client, tag_dict, tagtype_04_dict):
    """When the tag is already cached, get_image must not re-fetch it via get_db."""
    _seed_tag(client, tag_dict)
    bytes_per_row = (296 + 7) // 8
    plane_size = bytes_per_row * 152
    raw = b"\xff" * plane_size + b"\x00" * plane_size

    with aioresponses() as m:
        m.get(f"{BASE}/tagtypes/04.json", payload=tagtype_04_dict)
        m.get(f"{BASE}/current/AABBCCDDEEFF.raw", status=200, body=raw)
        img = await client.get_image("AABBCCDDEEFF")

    assert img is not None
    assert ("GET", aiohttp.client.URL(f"{BASE}/get_db?mac=AABBCCDDEEFF")) not in m.requests


@pytest.mark.asyncio
async def test_get_image_404_returns_none(client, tag_dict, tagtype_04_dict):
    tag = dict(tag_dict, hwType=4)
    with aioresponses() as m:
        m.get(f"{BASE}/get_db?mac=AABBCCDDEEFF", payload={"tags": [tag]})
        m.get(f"{BASE}/tagtypes/04.json", payload=tagtype_04_dict)
        m.get(f"{BASE}/current/AABBCCDDEEFF.raw", status=404)
        img = await client.get_image("AABBCCDDEEFF")

    assert img is None


@pytest.mark.asyncio
async def test_get_image_no_tag_record_returns_none(client):
    with aioresponses() as m:
        m.get(f"{BASE}/get_db?mac=AABBCCDDEEFF", payload={"tags": []})
        img = await client.get_image("AABBCCDDEEFF")

    assert img is None


@pytest.mark.asyncio
async def test_get_image_unknown_tag_type_raises(client, tag_dict):
    tag = dict(tag_dict, hwType=99)
    with aioresponses() as m:
        m.get(f"{BASE}/get_db?mac=AABBCCDDEEFF", payload={"tags": [tag]})
        m.get(f"{BASE}/tagtypes/63.json", status=404)
        with pytest.raises(ValueError):
            await client.get_image("AABBCCDDEEFF")


@pytest.mark.asyncio
async def test_tag_handle_get_image_delegates(client, tag_dict, tagtype_04_dict):
    tag = dict(tag_dict, hwType=4)
    bytes_per_row = (296 + 7) // 8
    plane_size = bytes_per_row * 152
    raw = b"\xff" * plane_size + b"\x00" * plane_size

    with aioresponses() as m:
        m.get(f"{BASE}/get_db?mac=AABBCCDDEEFF", payload={"tags": [tag]})
        m.get(f"{BASE}/tagtypes/04.json", payload=tagtype_04_dict)
        m.get(f"{BASE}/current/AABBCCDDEEFF.raw", status=200, body=raw)
        img = await client.tag("aabbccddeeff").get_image()

    assert img is not None
    assert img.size == (296, 152)


# ----------------------------------------------------------------------
# get_tag_type caching
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_tag_type_caches_result(client, tagtype_04_dict):
    with aioresponses() as m:
        m.get(f"{BASE}/tagtypes/04.json", payload=tagtype_04_dict)
        first = await client.get_tag_type(4)
        second = await client.get_tag_type(4)

    assert first is not None
    assert second is not None
    assert first.width == second.width
    # Only one HTTP call recorded, despite two get_tag_type() calls.
    assert len(m.requests[("GET", aiohttp.client.URL(f"{BASE}/tagtypes/04.json"))]) == 1


@pytest.mark.asyncio
async def test_get_tag_type_caches_404_miss(client):
    with aioresponses() as m:
        m.get(f"{BASE}/tagtypes/63.json", status=404)
        first = await client.get_tag_type(99)
        second = await client.get_tag_type(99)

    assert first is None
    assert second is None
    assert len(m.requests[("GET", aiohttp.client.URL(f"{BASE}/tagtypes/63.json"))]) == 1


@pytest.mark.asyncio
async def test_get_tag_type_use_cache_false_bypasses(client, tagtype_04_dict):
    with aioresponses() as m:
        m.get(f"{BASE}/tagtypes/04.json", payload=tagtype_04_dict)
        m.get(f"{BASE}/tagtypes/04.json", payload=tagtype_04_dict)
        await client.get_tag_type(4)
        await client.get_tag_type(4, use_cache=False)

    assert len(m.requests[("GET", aiohttp.client.URL(f"{BASE}/tagtypes/04.json"))]) == 2


# ----------------------------------------------------------------------
# Filtered on_tag_update
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_tag_update_filtered_by_mac(client, tag_dict):
    received = []
    client.on_tag_update(received.append, mac="AABBCCDDEEFF")

    other = dict(tag_dict, mac="001122334455")
    with aioresponses() as m:
        m.get(f"{BASE}/get_db", payload={"tags": [tag_dict, other], "continu": 0})
        await client.get_tags()

    assert len(received) == 1
    assert received[0].mac == "AABBCCDDEEFF"


@pytest.mark.asyncio
async def test_on_tag_update_filter_case_insensitive(client, tag_dict):
    received = []
    client.on_tag_update(received.append, mac="aabbccddeeff")

    with aioresponses() as m:
        m.get(f"{BASE}/get_db", payload={"tags": [tag_dict], "continu": 0})
        await client.get_tags()

    assert len(received) == 1


@pytest.mark.asyncio
async def test_on_tag_update_unfiltered_still_fires_for_all(client, tag_dict):
    """Omitting mac= keeps the old behavior: fires for every tag."""
    received = []
    client.on_tag_update(received.append)

    other = dict(tag_dict, mac="001122334455")
    with aioresponses() as m:
        m.get(f"{BASE}/get_db", payload={"tags": [tag_dict, other], "continu": 0})
        await client.get_tags()

    assert len(received) == 2


@pytest.mark.asyncio
async def test_tag_handle_on_update_filters_by_mac(client, tag_dict):
    received = []
    client.tag("aabbccddeeff").on_update(received.append)

    other = dict(tag_dict, mac="001122334455")
    with aioresponses() as m:
        m.get(f"{BASE}/get_db", payload={"tags": [tag_dict, other], "continu": 0})
        await client.get_tags()

    assert len(received) == 1
    assert received[0].mac == "AABBCCDDEEFF"


@pytest.mark.asyncio
async def test_on_tag_update_filtered_unsubscribe(client, tag_dict):
    received = []
    unsub = client.on_tag_update(received.append, mac="AABBCCDDEEFF")
    unsub()

    with aioresponses() as m:
        m.get(f"{BASE}/get_db", payload={"tags": [tag_dict], "continu": 0})
        await client.get_tags()

    assert received == []


# ----------------------------------------------------------------------
# wait_for_checkin
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wait_for_checkin_resolves_on_next_message(client, real_tag_dict):
    handler = _WebSocketHandler(client, reconnect_interval=30.0)
    mac = real_tag_dict["mac"]

    async def feed():
        await asyncio.sleep(0.01)
        await handler._handle_message(json.dumps({"tags": [real_tag_dict]}))

    task = asyncio.create_task(feed())
    tag = await client.wait_for_checkin(mac, timeout=2.0)
    await task

    assert tag.mac == mac
    assert len(client._tag_update_cbs) == 0  # unsubscribed


@pytest.mark.asyncio
async def test_wait_for_checkin_ignores_other_macs(client, real_tag_dict):
    handler = _WebSocketHandler(client, reconnect_interval=30.0)
    mac = real_tag_dict["mac"]
    other = dict(real_tag_dict, mac="001122334455")

    async def feed():
        await asyncio.sleep(0.01)
        await handler._handle_message(json.dumps({"tags": [other]}))
        await asyncio.sleep(0.01)
        await handler._handle_message(json.dumps({"tags": [real_tag_dict]}))

    task = asyncio.create_task(feed())
    tag = await client.wait_for_checkin(mac, timeout=2.0)
    await task

    assert tag.mac == mac


@pytest.mark.asyncio
async def test_wait_for_checkin_timeout_raises_and_unsubscribes(client):
    with pytest.raises(OEPLTimeoutError):
        await client.wait_for_checkin("AABBCCDDEEFF", timeout=0.05)

    assert len(client._tag_update_cbs) == 0


@pytest.mark.asyncio
async def test_tag_handle_wait_for_checkin_delegates(client, real_tag_dict):
    handler = _WebSocketHandler(client, reconnect_interval=30.0)
    mac = real_tag_dict["mac"]

    async def feed():
        await asyncio.sleep(0.01)
        await handler._handle_message(json.dumps({"tags": [real_tag_dict]}))

    task = asyncio.create_task(feed())
    tag = await client.tag(mac).wait_for_checkin(timeout=2.0)
    await task

    assert tag.mac == mac


# ----------------------------------------------------------------------
# upload_image(wait=True) — render-complete waiting
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_image_wait_without_connection_raises_immediately(client):
    with aioresponses() as m:
        with pytest.raises(OEPLConnectionError):
            await client.upload_image("AABBCCDDEEFF", b"\xff\xd8\xff", wait=True)

    # Must fail before ever attempting the HTTP upload.
    assert ("POST", aiohttp.client.URL(f"{BASE}/imgupload")) not in m.requests


@pytest.mark.asyncio
async def test_upload_image_wait_true_resolves_on_hash_change_and_pending_zero(client, tag_dict):
    client._set_connected(True)
    mac = "AABBCCDDEEFF"
    client._tags[mac] = Tag.from_dict(dict(tag_dict, mac=mac, hash="oldhash", pending=0))

    handler = _WebSocketHandler(client, reconnect_interval=30.0)

    async def feed():
        await asyncio.sleep(0.01)
        # New hash but still pending -- must NOT resolve yet.
        not_done = dict(tag_dict, mac=mac, hash="newhash", pending=1)
        await handler._handle_message(json.dumps({"tags": [not_done]}))
        await asyncio.sleep(0.01)
        # New hash and pending cleared -- render-complete signal.
        done = dict(tag_dict, mac=mac, hash="newhash", pending=0)
        await handler._handle_message(json.dumps({"tags": [done]}))

    task = asyncio.create_task(feed())

    with aioresponses() as m:
        m.post(f"{BASE}/imgupload", status=200, body=b"")
        await client.upload_image(mac, b"\xff\xd8\xff" + b"\x00" * 10, wait=True, wait_timeout=2.0)

    await task
    assert len(client._tag_update_cbs) == 0


@pytest.mark.asyncio
async def test_upload_image_wait_true_same_hash_pending_zero_does_not_resolve(client, tag_dict):
    """pending==0 with an unchanged hash must NOT be mistaken for render-complete."""
    client._set_connected(True)
    mac = "AABBCCDDEEFF"
    client._tags[mac] = Tag.from_dict(dict(tag_dict, mac=mac, hash="samehash", pending=0))

    handler = _WebSocketHandler(client, reconnect_interval=30.0)

    async def feed():
        await asyncio.sleep(0.01)
        stale = dict(tag_dict, mac=mac, hash="samehash", pending=0)
        await handler._handle_message(json.dumps({"tags": [stale]}))

    task = asyncio.create_task(feed())

    with aioresponses() as m:
        m.post(f"{BASE}/imgupload", status=200, body=b"")
        with pytest.raises(OEPLTimeoutError):
            await client.upload_image(mac, b"\xff\xd8\xff" + b"\x00" * 10, wait=True, wait_timeout=0.1)

    await task


@pytest.mark.asyncio
async def test_upload_image_wait_true_timeout_raises(client):
    client._set_connected(True)
    mac = "AABBCCDDEEFF"

    with aioresponses() as m:
        m.post(f"{BASE}/imgupload", status=200, body=b"")
        with pytest.raises(OEPLTimeoutError):
            await client.upload_image(mac, b"\xff\xd8\xff" + b"\x00" * 10, wait=True, wait_timeout=0.05)

    assert len(client._tag_update_cbs) == 0


@pytest.mark.asyncio
async def test_tag_handle_upload_image_forwards_wait(client, tag_dict, monkeypatch):
    """TagHandle.upload_image forwards wait/wait_timeout through to client.upload_image."""
    captured = {}

    async def fake_upload(mac, img, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(client, "upload_image", fake_upload)
    image_bytes = b"\xff\xd8\xff" + b"\x00" * 5
    await client.tag("aabbccddeeff").upload_image(image_bytes, wait=True, wait_timeout=5.0)

    assert captured["wait"] is True
    assert captured["wait_timeout"] == 5.0
