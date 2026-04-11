"""Shared fixtures for oepl tests."""
import pytest
import aiohttp
from aioresponses import aioresponses


HOST = "192.168.1.1"
BASE_URL = f"http://{HOST}"


@pytest.fixture
def mock_aiohttp():
    """Yield an aioresponses context that mocks all aiohttp requests."""
    with aioresponses() as m:
        yield m


@pytest.fixture
def tag_dict():
    """Minimal AP tag dict as returned by /get_db."""
    return {
        "mac": "AABBCCDDEEFF",
        "alias": "test-tag",
        "hwType": 16,
        "lastseen": 1700000000,
        "nextupdate": 1700003600,
        "nextcheckin": 1700001800,
        "pending": 0,
        "contentMode": 25,
        "LQI": 200,
        "RSSI": -65,
        "temperature": 22,
        "batteryMv": 3000,
        "wakeupReason": 0,
        "capabilities": 0,
        "rotate": 0,
        "lut": 1,
        "updatecount": 5,
        "isexternal": False,
        "apip": "192.168.1.1",
        "ch": 11,
        "ver": 1337,
    }
