"""Tests for _WebSocketHandler message parsing and routing."""

import json
import logging

import pytest

from oepl.client import OEPLClient
from oepl.models import APListItem, UploadProgress
from oepl.websocket import _WebSocketHandler

HOST = "192.168.1.1"


@pytest.fixture
async def client():
    """Yield an OEPLClient with its own session (no WebSocket started)."""
    c = OEPLClient(HOST)
    yield c
    if c._session is not None:
        await c._session.close()


@pytest.fixture
def handler(client):
    """A _WebSocketHandler wired to the client fixture, without a live connection."""
    return _WebSocketHandler(client, reconnect_interval=30.0)


# ----------------------------------------------------------------------
# tags
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tags_message_updates_cache_and_fires(handler, client, real_tag_dict):
    seen = []
    client.on_tag_update(seen.append)

    result = await handler._handle_message(json.dumps({"tags": [real_tag_dict]}))

    assert result is False
    mac = real_tag_dict["mac"]
    assert mac in client._tags
    assert client._tags[mac].alias == real_tag_dict["alias"]
    assert len(seen) == 1
    assert seen[0].mac == mac


# ----------------------------------------------------------------------
# sys
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sys_message_without_battery_fields_still_fires(handler, client):
    """P0-4 wire-level regression: sys messages without lowbattcount/timeoutcount
    (sent most of the time by the firmware) must still fire on_ap_status."""
    seen = []
    client.on_ap_status(seen.append)

    sys_data = {
        "currtime": 1700000000,
        "heap": 12345,
        "recordcount": 3,
        "apstate": 1,
        "runstate": 0,
        "rssi": -50,
        "wifissid": "test",
        "uptime": 100,
        "dbsize": 10,
        "littlefsfree": 500,
        "wifistatus": 3,
    }
    await handler._handle_message(json.dumps({"sys": sys_data}))

    assert len(seen) == 1
    assert seen[0].low_battery_count is None
    assert seen[0].timeout_count is None


@pytest.mark.asyncio
async def test_sys_message_with_battery_fields_sets_them(handler, client):
    seen = []
    client.on_ap_status(seen.append)

    sys_data = {
        "currtime": 1700000000,
        "heap": 12345,
        "recordcount": 3,
        "apstate": 1,
        "runstate": 0,
        "rssi": -50,
        "wifissid": "test",
        "uptime": 100,
        "dbsize": 10,
        "littlefsfree": 500,
        "wifistatus": 3,
        "lowbattcount": 2,
        "timeoutcount": 5,
    }
    await handler._handle_message(json.dumps({"sys": sys_data}))

    assert len(seen) == 1
    assert seen[0].low_battery_count == 2
    assert seen[0].timeout_count == 5


# ----------------------------------------------------------------------
# logMsg / errMsg
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_log_msg_fires_on_log(handler, client):
    seen = []
    client.on_log(seen.append)

    result = await handler._handle_message(json.dumps({"logMsg": "hello"}))

    assert result is False
    assert seen == ["hello"]


@pytest.mark.asyncio
async def test_err_msg_rebooting_disconnects_and_signals_break(handler, client):
    logs = []
    client.on_log(logs.append)
    client._set_connected(True)

    result = await handler._handle_message(json.dumps({"errMsg": "REBOOTING"}))

    assert result is True
    assert client.connected is False
    assert logs == ["errMsg: REBOOTING"]


@pytest.mark.asyncio
async def test_err_msg_other_only_fires_log(handler, client):
    logs = []
    client.on_log(logs.append)
    client._set_connected(True)

    result = await handler._handle_message(json.dumps({"errMsg": "some other error"}))

    assert result is False
    assert client.connected is True
    assert logs == ["errMsg: some other error"]


# ----------------------------------------------------------------------
# apitem
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apitem_full_shape(handler, client):
    seen: list[APListItem] = []
    client.on_ap_item(seen.append)

    apitem = {"ip": "192.168.1.5", "alias": "mesh-ap", "count": 3, "channel": 11, "version": "2.91"}
    await handler._handle_message(json.dumps({"apitem": apitem}))

    assert len(seen) == 1
    assert seen[0].ip == "192.168.1.5"
    assert seen[0].alias == "mesh-ap"
    assert seen[0].count == 3
    assert seen[0].channel == 11
    assert seen[0].version == "2.91"


@pytest.mark.asyncio
async def test_apitem_change_variant_does_not_raise(handler, client):
    seen: list[APListItem] = []
    client.on_ap_item(seen.append)

    result = await handler._handle_message(json.dumps({"apitem": {"type": "change"}}))

    assert result is False
    assert len(seen) == 1
    assert seen[0].ip == ""
    assert seen[0].raw == {"type": "change"}


# ----------------------------------------------------------------------
# upload
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_progress_not_done(handler, client):
    seen: list[UploadProgress] = []
    client.on_upload_progress(seen.append)

    await handler._handle_message(json.dumps({"upload": {"src": "AABBCCDDEEFF0011", "current": 3, "total": 10}}))

    assert len(seen) == 1
    assert seen[0].src == "AABBCCDDEEFF0011"
    assert seen[0].current == 3
    assert seen[0].total == 10
    assert seen[0].done is False


@pytest.mark.asyncio
async def test_upload_progress_done(handler, client):
    seen: list[UploadProgress] = []
    client.on_upload_progress(seen.append)

    await handler._handle_message(json.dumps({"upload": {"src": "AABBCCDDEEFF0011", "current": 10, "total": 10}}))

    assert len(seen) == 1
    assert seen[0].done is True


# ----------------------------------------------------------------------
# touch
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_touch_passthrough(handler, client):
    seen = []
    client.on_touch(seen.append)

    touch = {"count": 1, "points": [{"id": 0, "x": 10, "y": 20, "size": 5}]}
    await handler._handle_message(json.dumps({"touch": touch}))

    assert seen == [touch]


# ----------------------------------------------------------------------
# console
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_console_with_color_fires_on_console(handler, client):
    seen = []
    client.on_console(seen.append)

    await handler._handle_message(json.dumps({"console": "boot log line", "color": "red"}))

    assert seen == ["boot log line"]


# ----------------------------------------------------------------------
# raw / unknown
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_key_fires_raw_no_warning(handler, client, caplog):
    seen = []
    client.on_raw_message(seen.append)

    with caplog.at_level(logging.DEBUG):
        result = await handler._handle_message(json.dumps({"whatever": 1}))

    assert result is False
    assert seen == [{"whatever": 1}]
    assert not any(rec.levelno >= logging.WARNING for rec in caplog.records)


@pytest.mark.asyncio
async def test_raw_message_fires_for_known_types_too(handler, client):
    seen = []
    client.on_raw_message(seen.append)
    log_seen = []
    client.on_log(log_seen.append)

    await handler._handle_message(json.dumps({"logMsg": "hi"}))

    assert seen == [{"logMsg": "hi"}]
    assert log_seen == ["hi"]


@pytest.mark.asyncio
async def test_malformed_json_is_skipped(handler, client, caplog):
    with caplog.at_level(logging.DEBUG):
        result = await handler._handle_message("not json{{{")

    assert result is False
    assert any("Could not parse" in rec.message for rec in caplog.records)


# ----------------------------------------------------------------------
# callback isolation
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_raising_callback_does_not_block_others(handler, client):
    calls = []

    def bad_cb(_msg):
        raise RuntimeError("boom")

    def good_cb(msg):
        calls.append(msg)

    client.on_log(bad_cb)
    client.on_log(good_cb)

    await handler._handle_message(json.dumps({"logMsg": "still works"}))

    assert calls == ["still works"]


# ----------------------------------------------------------------------
# unsubscribe
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unsubscribe_ap_item(handler, client):
    seen = []
    unsub = client.on_ap_item(seen.append)
    unsub()

    await handler._handle_message(json.dumps({"apitem": {"ip": "1.2.3.4"}}))

    assert seen == []


@pytest.mark.asyncio
async def test_unsubscribe_upload_progress(handler, client):
    seen = []
    unsub = client.on_upload_progress(seen.append)
    unsub()

    await handler._handle_message(json.dumps({"upload": {"src": "x", "current": 1, "total": 1}}))

    assert seen == []


@pytest.mark.asyncio
async def test_unsubscribe_touch(handler, client):
    seen = []
    unsub = client.on_touch(seen.append)
    unsub()

    await handler._handle_message(json.dumps({"touch": {"count": 0, "points": []}}))

    assert seen == []


@pytest.mark.asyncio
async def test_unsubscribe_console(handler, client):
    seen = []
    unsub = client.on_console(seen.append)
    unsub()

    await handler._handle_message(json.dumps({"console": "text"}))

    assert seen == []


@pytest.mark.asyncio
async def test_unsubscribe_raw_message(handler, client):
    seen = []
    unsub = client.on_raw_message(seen.append)
    unsub()

    await handler._handle_message(json.dumps({"whatever": 1}))

    assert seen == []
