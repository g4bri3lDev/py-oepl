"""Tests for the low-level _HTTPClient: error-body detection and response release."""

from unittest.mock import MagicMock, patch

import pytest
from aioresponses import aioresponses

from oepl._http import _HTTPClient
from oepl.exceptions import OEPLNotFoundError, OEPLResponseError

HOST = "192.168.1.1"
BASE = f"http://{HOST}"


@pytest.fixture
async def http_client():
    import aiohttp

    session = aiohttp.ClientSession()
    yield _HTTPClient(HOST, lambda: session)
    await session.close()


@pytest.mark.asyncio
async def test_post_form_raises_on_error_body(http_client):
    with aioresponses() as m:
        m.post(f"{BASE}/save_cfg", status=200, body="Error while saving: mac not found")
        with pytest.raises(OEPLResponseError) as exc_info:
            await http_client.post_form("save_cfg", {"mac": "DEADBEEF"})

    assert exc_info.value.status == 200
    assert exc_info.value.body == "Error while saving: mac not found"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    ["Ok, saved", "Ok, done", "ok, request transmitted", "OK Reboot", "ok", "Ok, restored."],
)
async def test_post_form_success_bodies_pass(http_client, body):
    with aioresponses() as m:
        m.post(f"{BASE}/save_cfg", status=200, body=body)
        result = await http_client.post_form("save_cfg", {"mac": "DEADBEEF"})
    assert result == body


@pytest.mark.asyncio
async def test_get_text_raises_on_error_body(http_client):
    with aioresponses() as m:
        m.get(f"{BASE}/led_flash", status=200, body="Error: something")
        with pytest.raises(OEPLResponseError) as exc_info:
            await http_client.get_text("led_flash")

    assert exc_info.value.status == 200
    assert exc_info.value.body == "Error: something"


@pytest.mark.asyncio
async def test_get_text_success_body_returns_normally(http_client):
    with aioresponses() as m:
        m.get(f"{BASE}/led_flash", status=200, body="ok, request transmitted")
        result = await http_client.get_text("led_flash")
    assert result == "ok, request transmitted"


@pytest.mark.asyncio
async def test_post_multipart_empty_body_is_not_an_error(http_client):
    """/imgupload returns an empty 200 body on success; no error-body check applies."""
    with aioresponses() as m:
        m.post(f"{BASE}/imgupload", status=200, body=b"")
        await http_client.post_multipart("imgupload", {"mac": "DEADBEEF"})


@pytest.mark.asyncio
async def test_get_raw_no_body_check(http_client):
    """get_raw/get_json never apply the error-body heuristic."""
    with aioresponses() as m:
        m.get(f"{BASE}/current/AABB.raw", status=200, body=b"Error-looking-but-actually-binary")
        result = await http_client.get_raw("current/AABB.raw")
    assert result == b"Error-looking-but-actually-binary"


@pytest.mark.asyncio
async def test_get_bytes_returns_body(http_client):
    with aioresponses() as m:
        m.get(f"{BASE}/backup_db", status=200, body=b'{"tags":[]}')
        result = await http_client.get_bytes("backup_db")
    assert result == b'{"tags":[]}'


@pytest.mark.asyncio
async def test_get_bytes_raises_not_found_on_404(http_client):
    with aioresponses() as m:
        m.get(f"{BASE}/backup_db", status=404)
        with pytest.raises(OEPLNotFoundError):
            await http_client.get_bytes("backup_db")


@pytest.mark.asyncio
async def test_post_multipart_check_body_raises_on_error_body(http_client):
    with aioresponses() as m:
        m.post(f"{BASE}/restore_db", status=200, body="Error: bad file")
        with pytest.raises(OEPLResponseError):
            await http_client.post_multipart("restore_db", {"file": ("x", b"y", "text/plain")}, check_body=True)


@pytest.mark.asyncio
async def test_post_multipart_check_body_false_ignores_error_looking_body(http_client):
    """Default check_body=False -- needed for /imgupload's empty-body success case, but also
    means a body that merely starts with 'Error' is not checked unless opted in."""
    with aioresponses() as m:
        m.post(f"{BASE}/imgupload", status=200, body="Error-looking but not opted into checking")
        await http_client.post_multipart("imgupload", {"mac": "DEADBEEF"})


@pytest.mark.asyncio
async def test_404_releases_response(http_client):
    with aioresponses() as m:
        m.get(f"{BASE}/missing", status=404)
        with patch("aiohttp.ClientResponse.release", new=MagicMock()) as mock_release, pytest.raises(OEPLNotFoundError):
            await http_client.get_text("missing")
        mock_release.assert_called()


@pytest.mark.asyncio
async def test_delete_form_sends_delete_verb_with_data(http_client):
    with aioresponses() as m:
        m.delete(f"{BASE}/edit", status=200, body="DELETE: foo.bin")
        result = await http_client.delete_form("edit", {"path": "foo.bin"})
    assert result == "DELETE: foo.bin"


@pytest.mark.asyncio
async def test_delete_form_raises_on_error_body(http_client):
    with aioresponses() as m:
        m.delete(f"{BASE}/edit", status=200, body="Error: nope")
        with pytest.raises(OEPLResponseError):
            await http_client.delete_form("edit", {"path": "foo.bin"})


@pytest.mark.asyncio
async def test_get_json_any_parses_bare_array(http_client):
    with aioresponses() as m:
        m.get(f"{BASE}/edit", status=200, body=b'[{"a": 1}, {"b": 2}]', content_type="application/json")
        result = await http_client.get_json_any("edit")
    assert result == [{"a": 1}, {"b": 2}]


@pytest.mark.asyncio
async def test_post_form_custom_timeout_is_passed_through(http_client):
    import aiohttp

    custom = aiohttp.ClientTimeout(total=30)
    with aioresponses() as m:
        m.post(f"{BASE}/update_ota", status=200, body="In progress")
        await http_client.post_form("update_ota", {"url": "x"}, timeout=custom)

    from aiohttp.client import URL

    recorded = m.requests[("POST", URL(f"{BASE}/update_ota"))]
    assert len(recorded) == 1
    _args, kwargs = recorded[0]
    assert kwargs["timeout"] == custom


@pytest.mark.asyncio
async def test_non200_releases_response(http_client):
    with aioresponses() as m:
        m.get(f"{BASE}/broken", status=500, body="boom")
        with patch("aiohttp.ClientResponse.release", new=MagicMock()) as mock_release, pytest.raises(OEPLResponseError):
            await http_client.get_text("broken")
        mock_release.assert_called()
