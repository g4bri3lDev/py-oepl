"""Tests for OTA / firmware-update client methods. Mock-only -- these are destructive on a real AP."""

import aiohttp
import pytest
from aioresponses import aioresponses

from oepl.client import OEPLClient
from oepl.exceptions import OEPLResponseError

HOST = "192.168.1.1"
BASE = f"http://{HOST}"


@pytest.fixture
async def client():
    c = OEPLClient(HOST)
    yield c
    if c._session is not None:
        await c._session.close()


def _form_call(m, method, path):
    calls = m.requests[(method, aiohttp.client.URL(f"{BASE}/{path}"))]
    assert len(calls) == 1
    return calls[0]


@pytest.mark.asyncio
async def test_update_ota_posts_exact_fields(client):
    with aioresponses() as m:
        m.post(f"{BASE}/update_ota", status=200, body="In progress")
        await client.update_ota("http://example.com/fw.bin", "deadbeef", 12345)

    _args, kwargs = _form_call(m, "POST", "update_ota")
    assert kwargs["data"] == {"url": "http://example.com/fw.bin", "md5": "deadbeef", "size": "12345"}


@pytest.mark.asyncio
async def test_update_ota_bad_request_raises(client):
    with aioresponses() as m:
        m.post(f"{BASE}/update_ota", status=400, body="Bad request")
        with pytest.raises(OEPLResponseError) as exc_info:
            await client.update_ota("http://x/fw.bin", "md5", 1)
    assert exc_info.value.status == 400


@pytest.mark.asyncio
async def test_rollback_posts_no_body(client):
    with aioresponses() as m:
        m.post(f"{BASE}/rollback", status=200, body="Rollback successful")
        await client.rollback()

    _args, kwargs = _form_call(m, "POST", "rollback")
    assert kwargs["data"] == {}


@pytest.mark.asyncio
async def test_rollback_not_allowed_raises(client):
    with aioresponses() as m:
        m.post(f"{BASE}/rollback", status=400, body="Rollback not allowed")
        with pytest.raises(OEPLResponseError):
            await client.rollback()


@pytest.mark.asyncio
async def test_run_update_actions_posts_no_body(client):
    with aioresponses() as m:
        m.post(f"{BASE}/update_actions", status=200, body="No update actions needed")
        await client.run_update_actions()

    _args, kwargs = _form_call(m, "POST", "update_actions")
    assert kwargs["data"] == {}


@pytest.mark.asyncio
async def test_update_c6_posts_url(client):
    with aioresponses() as m:
        m.post(f"{BASE}/update_c6", status=200, body="Ok")
        await client.update_c6("http://example.com/c6fw.bin")

    _args, kwargs = _form_call(m, "POST", "update_c6")
    assert kwargs["data"] == {"url": "http://example.com/c6fw.bin"}


@pytest.mark.asyncio
async def test_update_c6_not_implemented_raises(client):
    with aioresponses() as m:
        m.post(f"{BASE}/update_c6", status=400, body="C6/H2 flashing not implemented")
        with pytest.raises(OEPLResponseError):
            await client.update_c6("http://x/fw.bin")
