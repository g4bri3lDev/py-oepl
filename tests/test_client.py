"""Tests for OEPLClient HTTP operations."""

import json
import warnings

import aiohttp
import pytest
from aioresponses import aioresponses

from oepl.client import OEPLClient
from oepl.enums import LUT, Rotation, TagCommand
from oepl.exceptions import OEPLNotFoundError, OEPLResponseError
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
async def test_delete_tag_sends_del(client):
    with aioresponses() as m:
        m.post(f"{BASE}/tag_cmd", status=200, body="Ok, done")
        client._tags["AABBCCDDEEFF"] = object()  # sentinel; only presence/absence matters
        await client.delete_tag("AABBCCDDEEFF")

    calls = m.requests[("POST", aiohttp.client.URL(f"{BASE}/tag_cmd"))]
    assert len(calls) == 1
    assert calls[0].kwargs["data"] == {"mac": "AABBCCDDEEFF", "cmd": "del"}
    assert "AABBCCDDEEFF" not in client._tags


@pytest.mark.asyncio
async def test_delete_tag_missing_from_cache_is_noop(client):
    """Deleting a MAC not currently in the cache must not raise (cache is best-effort)."""
    with aioresponses() as m:
        m.post(f"{BASE}/tag_cmd", status=200, body="Ok, done")
        await client.delete_tag("AABBCCDDEEFF")


@pytest.mark.asyncio
async def test_purge_stale_tags_sends_purge_with_registered_mac(client, tag_dict):
    """Purge fetches the tag list, sends cmd=purge with a registered MAC, then refetches the cache."""
    survivor = dict(tag_dict, mac="001122334455", alias="survivor")
    with aioresponses() as m:
        # First get_tags(): both tags present.
        m.get(f"{BASE}/get_db", payload={"tags": [tag_dict, survivor], "continu": 0})
        m.post(f"{BASE}/tag_cmd", status=200, body="Ok, done")
        # Refetch after purge: only the survivor remains server-side.
        m.get(f"{BASE}/get_db", payload={"tags": [survivor], "continu": 0})
        await client.purge_stale_tags()

    calls = m.requests[("POST", aiohttp.client.URL(f"{BASE}/tag_cmd"))]
    assert len(calls) == 1
    assert calls[0].kwargs["data"] == {"mac": "AABBCCDDEEFF", "cmd": "purge"}
    # Cache reflects the server-side deletions (purged tag gone, survivor kept).
    assert set(client._tags) == {"001122334455"}


@pytest.mark.asyncio
async def test_purge_stale_tags_empty_db_sends_nothing(client):
    """With no tags registered there is no valid MAC to satisfy the handler guard; no command is sent."""
    with aioresponses() as m:
        m.get(f"{BASE}/get_db", payload={"tags": [], "continu": 0})
        await client.purge_stale_tags()

    assert ("POST", aiohttp.client.URL(f"{BASE}/tag_cmd")) not in m.requests


@pytest.mark.asyncio
async def test_get_tag_found(client, real_tag_dict):
    with aioresponses() as m:
        m.get(f"{BASE}/get_db?mac=00000335042F3E10", payload={"tags": [real_tag_dict]})
        tag = await client.get_tag("00000335042F3E10")

    assert tag is not None
    assert tag.mac == "00000335042F3E10"
    assert tag.alias == "MVG 22"
    assert client._tags["00000335042F3E10"] is tag


@pytest.mark.asyncio
async def test_get_tag_found_fires_callback(client, real_tag_dict):
    received = []
    client.on_tag_update(received.append)

    with aioresponses() as m:
        m.get(f"{BASE}/get_db?mac=00000335042F3E10", payload={"tags": [real_tag_dict]})
        await client.get_tag("00000335042F3E10")

    assert len(received) == 1
    assert received[0].mac == "00000335042F3E10"


@pytest.mark.asyncio
async def test_get_tag_not_found_returns_none(client):
    with aioresponses() as m:
        m.get(f"{BASE}/get_db?mac=AABBCCDDEEFF", payload={"tags": []})
        tag = await client.get_tag("aabbccddeeff")

    assert tag is None


@pytest.mark.asyncio
async def test_save_tag_config_only_passed_fields(client):
    with aioresponses() as m:
        m.post(f"{BASE}/save_cfg", status=200, body="Ok, saved")
        await client.save_tag_config("AABBCCDDEEFF", alias="my-tag")

    calls = m.requests[("POST", aiohttp.client.URL(f"{BASE}/save_cfg"))]
    data = calls[0].kwargs["data"]
    assert data == {"mac": "AABBCCDDEEFF", "alias": "my-tag"}


@pytest.mark.asyncio
async def test_save_tag_config_all_fields(client):
    from oepl.enums import ContentMode

    with aioresponses() as m:
        m.post(f"{BASE}/save_cfg", status=200, body="Ok, saved")
        await client.save_tag_config(
            "AABBCCDDEEFF",
            content_mode=ContentMode.TODAY,
            alias="my-tag",
            mode_cfg_json={"a": 1},
            rotate=Rotation.R180,
            lut=LUT.FAST,
            invert=True,
        )

    calls = m.requests[("POST", aiohttp.client.URL(f"{BASE}/save_cfg"))]
    data = calls[0].kwargs["data"]
    assert data["mac"] == "AABBCCDDEEFF"
    assert data["contentmode"] == "1"
    assert data["alias"] == "my-tag"
    assert data["modecfgjson"] == '{"a": 1}'
    assert data["rotate"] == "2"
    assert data["lut"] == "3"
    assert data["invert"] == "1"


@pytest.mark.asyncio
async def test_save_tag_config_mode_cfg_json_string_passthrough(client):
    with aioresponses() as m:
        m.post(f"{BASE}/save_cfg", status=200, body="Ok, saved")
        await client.save_tag_config("AABBCCDDEEFF", mode_cfg_json='{"raw":"1"}')

    calls = m.requests[("POST", aiohttp.client.URL(f"{BASE}/save_cfg"))]
    assert calls[0].kwargs["data"]["modecfgjson"] == '{"raw":"1"}'


@pytest.mark.asyncio
async def test_save_tag_config_content_mode_int_passthrough(client):
    with aioresponses() as m:
        m.post(f"{BASE}/save_cfg", status=200, body="Ok, saved")
        await client.save_tag_config("AABBCCDDEEFF", content_mode=24)

    calls = m.requests[("POST", aiohttp.client.URL(f"{BASE}/save_cfg"))]
    assert calls[0].kwargs["data"]["contentmode"] == "24"


@pytest.mark.asyncio
async def test_save_tag_config_no_fields_sends_only_mac(client):
    with aioresponses() as m:
        m.post(f"{BASE}/save_cfg", status=200, body="Ok, saved")
        await client.save_tag_config("AABBCCDDEEFF")

    calls = m.requests[("POST", aiohttp.client.URL(f"{BASE}/save_cfg"))]
    assert calls[0].kwargs["data"] == {"mac": "AABBCCDDEEFF"}


@pytest.mark.asyncio
async def test_save_tag_config_raises_on_ap_error_body(client):
    with aioresponses() as m:
        m.post(f"{BASE}/save_cfg", status=200, body="Error while saving: mac not found")
        with pytest.raises(OEPLResponseError) as exc_info:
            await client.save_tag_config("DEADBEEFDEAD", alias="x")

    assert exc_info.value.status == 200
    assert exc_info.value.body == "Error while saving: mac not found"


@pytest.mark.asyncio
async def test_set_alias_delegates_to_save_tag_config(client, monkeypatch):
    calls = []

    async def fake_save_tag_config(mac, **kwargs):
        calls.append((mac, kwargs))

    monkeypatch.setattr(client, "save_tag_config", fake_save_tag_config)
    await client.set_alias("AABBCCDDEEFF", "my-display")

    assert calls == [("AABBCCDDEEFF", {"alias": "my-display"})]


@pytest.mark.asyncio
async def test_upload_json_dict(client):
    with aioresponses() as m:
        m.post(f"{BASE}/jsonupload", status=200, body="Ok, saved")
        await client.upload_json("AABBCCDDEEFF", {"foo": "bar"}, ttl=60)

    calls = m.requests[("POST", aiohttp.client.URL(f"{BASE}/jsonupload"))]
    data = calls[0].kwargs["data"]
    assert data["mac"] == "AABBCCDDEEFF"
    assert data["json"] == '{"foo": "bar"}'
    assert data["ttl"] == "60"


@pytest.mark.asyncio
async def test_upload_json_string_passthrough(client):
    with aioresponses() as m:
        m.post(f"{BASE}/jsonupload", status=200, body="Ok, saved")
        await client.upload_json("AABBCCDDEEFF", '{"raw":true}')

    calls = m.requests[("POST", aiohttp.client.URL(f"{BASE}/jsonupload"))]
    data = calls[0].kwargs["data"]
    assert data["json"] == '{"raw":true}'
    assert data["ttl"] == "0"


@pytest.mark.asyncio
async def test_upload_json_raises_on_ap_error_body(client):
    """The AP reports an unknown MAC for /jsonupload as a genuine HTTP 400 (unlike /save_cfg's 200)."""
    with aioresponses() as m:
        m.post(f"{BASE}/jsonupload", status=400, body="mac not found in tagDB")
        with pytest.raises(OEPLResponseError):
            await client.upload_json("DEADBEEFDEAD", {"a": 1})


@pytest.mark.asyncio
async def test_get_image_data_bytes_passthrough(client):
    with aioresponses() as m:
        m.get(f"{BASE}/getdata?mac=AABBCCDDEEFF", status=200, body=b"\x01\x02\x03")
        data = await client.get_image_data("AABBCCDDEEFF")

    assert data == b"\x01\x02\x03"


@pytest.mark.asyncio
async def test_get_image_data_404_returns_none(client):
    with aioresponses() as m:
        m.get(f"{BASE}/getdata?mac=AABBCCDDEEFF", status=404)
        data = await client.get_image_data("AABBCCDDEEFF")

    assert data is None


@pytest.mark.asyncio
async def test_get_image_data_md5_param_included(client):
    with aioresponses() as m:
        m.get(
            f"{BASE}/getdata?mac=AABBCCDDEEFF&md5=deadbeefdeadbeef",
            status=200,
            body=b"\xff",
        )
        data = await client.get_image_data("AABBCCDDEEFF", md5="deadbeefdeadbeef")

    assert data == b"\xff"


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


# ----------------------------------------------------------------------
# AP operations: variables, wifi, backup/restore, set_time
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_variable(client):
    with aioresponses() as m:
        m.post(f"{BASE}/set_var", status=200, body="Ok, saved")
        await client.set_variable("myvar", "myvalue")

    calls = m.requests[("POST", aiohttp.client.URL(f"{BASE}/set_var"))]
    assert len(calls) == 1
    assert calls[0].kwargs["data"] == {"key": "myvar", "val": "myvalue"}


@pytest.mark.asyncio
async def test_set_variables_serializes_dict_as_json_field(client):
    with aioresponses() as m:
        m.post(f"{BASE}/set_vars", status=200, body="JSON uploaded and processed")
        await client.set_variables({"a": "1", "b": "2"})

    calls = m.requests[("POST", aiohttp.client.URL(f"{BASE}/set_vars"))]
    assert len(calls) == 1
    data = calls[0].kwargs["data"]
    assert set(data.keys()) == {"json"}
    assert json.loads(data["json"]) == {"a": "1", "b": "2"}


@pytest.mark.asyncio
async def test_get_wifi_config(client):
    payload = {
        "ssid": "home-network",
        "pw": "secret",
        "ip": "",
        "mask": "",
        "gw": "",
        "dns": "",
        "mac": "AA:BB:CC:DD:EE:FF",
    }
    with aioresponses() as m:
        m.get(f"{BASE}/get_wifi_config", payload=payload)
        cfg = await client.get_wifi_config()

    assert cfg.ssid == "home-network"
    assert cfg.password == "secret"
    assert cfg.mac == "AA:BB:CC:DD:EE:FF"
    assert cfg.raw == payload


@pytest.mark.asyncio
async def test_get_ssid_list(client):
    payload = {
        "scanstatus": 1,
        "networks": [{"ssid": "net-a", "ch": 6, "rssi": -50, "enc": 3}],
    }
    with aioresponses() as m:
        m.get(f"{BASE}/get_ssid_list", payload=payload)
        result = await client.get_ssid_list()

    assert result.scan_status == 1
    assert len(result.networks) == 1
    assert result.networks[0].ssid == "net-a"


@pytest.mark.asyncio
async def test_save_wifi_config_posts_json_body(client):
    with aioresponses() as m:
        m.post(f"{BASE}/save_wifi_config", status=200, body="Ok, saved")
        await client.save_wifi_config("my-ssid", password="my-pass", ip="192.168.1.50")

    calls = m.requests[("POST", aiohttp.client.URL(f"{BASE}/save_wifi_config"))]
    assert len(calls) == 1
    kwargs = calls[0].kwargs
    assert "data" not in kwargs or kwargs.get("data") is None
    assert kwargs["json"] == {"ssid": "my-ssid", "pw": "my-pass", "ip": "192.168.1.50"}


@pytest.mark.asyncio
async def test_save_wifi_config_omits_unset_fields(client):
    with aioresponses() as m:
        m.post(f"{BASE}/save_wifi_config", status=200, body="Ok, saved")
        await client.save_wifi_config("my-ssid")

    calls = m.requests[("POST", aiohttp.client.URL(f"{BASE}/save_wifi_config"))]
    assert calls[0].kwargs["json"] == {"ssid": "my-ssid"}


@pytest.mark.asyncio
async def test_save_wifi_config_factory_ssid_raises_without_force(client):
    with pytest.raises(ValueError, match="factory"):
        await client.save_wifi_config("factory")


@pytest.mark.asyncio
async def test_save_wifi_config_factory_ssid_with_force_passes_through(client):
    with aioresponses() as m:
        m.post(f"{BASE}/save_wifi_config", status=200, body="Ok, saved")
        await client.save_wifi_config("factory", force=True)

    calls = m.requests[("POST", aiohttp.client.URL(f"{BASE}/save_wifi_config"))]
    assert calls[0].kwargs["json"] == {"ssid": "factory"}


@pytest.mark.asyncio
async def test_backup_db_bytes_passthrough(client):
    with aioresponses() as m:
        m.get(f"{BASE}/backup_db", status=200, body=b'{"tags":[]}')
        data = await client.backup_db()

    assert data == b'{"tags":[]}'


@pytest.mark.asyncio
async def test_backup_db_404_raises(client):
    with aioresponses() as m:
        m.get(f"{BASE}/backup_db", status=404)
        with pytest.raises(OEPLNotFoundError):
            await client.backup_db()


@pytest.mark.asyncio
async def test_restore_db_multipart_contains_file_part(client):
    payload = b'{"tags":[{"mac":"AABBCCDDEEFF"}]}'
    with aioresponses() as m:
        m.post(f"{BASE}/restore_db", status=200, body="Ok, restored.")
        await client.restore_db(payload)

    calls = m.requests[("POST", aiohttp.client.URL(f"{BASE}/restore_db"))]
    assert len(calls) == 1
    kwargs = calls[0].kwargs
    content_type = kwargs["headers"]["Content-Type"]
    text_fields, file_parts = _parse_multipart(kwargs["data"], content_type)
    assert text_fields == {}
    assert file_parts["file"] == payload
    assert file_parts["__headers__"]["file"] == "Content-Type: application/json"


@pytest.mark.asyncio
async def test_restore_db_raises_on_200_error_body(client):
    """restore_db opts into post_multipart's check_body=True: unlike imgupload, /restore_db
    can return a 200 carrying an AP-reported error string, which must not be swallowed."""
    payload = b'{"tags":[]}'
    with aioresponses() as m:
        m.post(f"{BASE}/restore_db", status=200, body="Error: bad backup file")
        with pytest.raises(OEPLResponseError):
            await client.restore_db(payload)


@pytest.mark.asyncio
async def test_upload_image_empty_body_still_succeeds(client):
    """imgupload does NOT opt into check_body -- its empty-body success response must not
    be mistaken for an error (post_multipart's check_body defaults to False)."""
    with aioresponses() as m:
        m.post(f"{BASE}/imgupload", status=200, body=b"")
        await client.upload_image("AABBCCDDEEFF", b"\xff\xd8\xff" + b"\x00" * 10)


@pytest.mark.asyncio
async def test_set_time_no_arg_posts_current_epoch(client, monkeypatch):
    monkeypatch.setattr("oepl.client.time.time", lambda: 1750000000.0)
    with aioresponses() as m:
        m.post(f"{BASE}/set_time", status=200, body="ok")
        await client.set_time()

    calls = m.requests[("POST", aiohttp.client.URL(f"{BASE}/set_time"))]
    assert calls[0].kwargs["data"] == {"epoch": "1750000000"}


@pytest.mark.asyncio
async def test_set_time_explicit_epoch(client):
    with aioresponses() as m:
        m.post(f"{BASE}/set_time", status=200, body="ok")
        await client.set_time(1234567890)

    calls = m.requests[("POST", aiohttp.client.URL(f"{BASE}/set_time"))]
    assert calls[0].kwargs["data"] == {"epoch": "1234567890"}


# ----------------------------------------------------------------------
# set_ap_config_item / set_sleep_window
# ----------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("key", "value", "expected"),
    [
        ("alias", "my-ap", "my-ap"),
        ("channel", 11, "11"),
        ("preview", True, "1"),
        ("nightlyreboot", False, "0"),
        ("timezone", "UTC", "UTC"),
    ],
)
async def test_set_ap_config_item_posts_exactly_one_key(client, key, value, expected):
    with aioresponses() as m:
        m.post(f"{BASE}/save_apcfg", status=200, body="Ok, saved")
        await client.set_ap_config_item(key, value)

    calls = m.requests[("POST", aiohttp.client.URL(f"{BASE}/save_apcfg"))]
    assert len(calls) == 1
    assert calls[0].kwargs["data"] == {key: expected}


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["sleeptime1", "sleeptime2"])
async def test_set_ap_config_item_sleeptime_raises(client, key):
    """Posting sleeptime1 alone null-derefs in firmware (web.cpp:659-662); both keys refused."""
    with aioresponses() as m:
        with pytest.raises(ValueError, match="set_sleep_window"):
            await client.set_ap_config_item(key, 5)

    assert ("POST", aiohttp.client.URL(f"{BASE}/save_apcfg")) not in m.requests


@pytest.mark.asyncio
async def test_set_sleep_window_posts_both_keys(client):
    with aioresponses() as m:
        m.post(f"{BASE}/save_apcfg", status=200, body="Ok, saved")
        await client.set_sleep_window(23, 6)

    calls = m.requests[("POST", aiohttp.client.URL(f"{BASE}/save_apcfg"))]
    assert len(calls) == 1
    assert calls[0].kwargs["data"] == {"sleeptime1": "23", "sleeptime2": "6"}


@pytest.mark.asyncio
async def test_set_sleep_window_equal_hours_disable(client):
    """Equal values disable the window (util::isSleeping returns false when equal)."""
    with aioresponses() as m:
        m.post(f"{BASE}/save_apcfg", status=200, body="Ok, saved")
        await client.set_sleep_window(0, 0)

    calls = m.requests[("POST", aiohttp.client.URL(f"{BASE}/save_apcfg"))]
    assert calls[0].kwargs["data"] == {"sleeptime1": "0", "sleeptime2": "0"}


@pytest.mark.asyncio
@pytest.mark.parametrize(("start", "end"), [(-1, 6), (24, 6), (23, -1), (23, 24)])
async def test_set_sleep_window_rejects_out_of_range_hours(client, start, end):
    with aioresponses() as m:
        with pytest.raises(ValueError, match="0-23"):
            await client.set_sleep_window(start, end)

    assert ("POST", aiohttp.client.URL(f"{BASE}/save_apcfg")) not in m.requests
