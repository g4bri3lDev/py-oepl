"""Shared fixtures for oepl tests."""

import pytest
from aioresponses import aioresponses

HOST = "192.168.1.1"
BASE_URL = f"http://{HOST}"


@pytest.fixture
def mock_aiohttp():
    """Yield an aioresponses context that mocks all aiohttp requests."""
    with aioresponses() as m:
        yield m


@pytest.fixture
def apconfig_dict():
    """Minimal AP config dict as returned by /get_ap_config."""
    return {
        "alias": "my-ap",
        "channel": 11,
        "subghzchannel": 0,
        "led": 127,
        "tft": 128,
        "language": 0,
        "maxsleep": 10,
        "stopsleep": 0,
        "timezone": "UTC",
        "preview": 0,
        "nightlyreboot": 0,
        "lock": 0,
        "wifipower": 78,
        "sleeptime1": 0,
        "sleeptime2": 0,
        "ble": 0,
        "repo": "",
        "env": "SDEP_EXT_CC1101",
        "discovery": 1,
        "showtimestamp": 0,
    }


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
        "hash": "deadbeef",
        "modecfgjson": "{}",
        "invert": 0,
        "updatelast": 1700003500,
    }


@pytest.fixture
def real_tag_dict():
    """Real /get_db tag payload captured live from firmware 2.91."""
    return {
        "mac": "00000335042F3E10",
        "hash": "1b00000000c2cb3fc88ccb3f5c6f0540",
        "lastseen": 1784033099,
        "nextupdate": 3216153600,
        "nextcheckin": 1784033159,
        "pending": 0,
        "alias": "MVG 22",
        "contentMode": 25,
        "LQI": 0,
        "RSSI": -23,
        "temperature": 0,
        "batteryMv": 0,
        "hwType": 4,
        "wakeupReason": 0,
        "capabilities": 0,
        "modecfgjson": '{"filename":"/temp/x.jpg","dither":"2"}',
        "isexternal": False,
        "apip": "0.0.0.0",
        "rotate": 0,
        "lut": 0,
        "invert": 0,
        "updatecount": 0,
        "updatelast": 0,
        "ch": 0,
        "ver": 0,
    }


@pytest.fixture
def real_apconfig_dict():
    """Real /get_ap_config payload captured live from firmware 2.91."""
    return {
        "C6": "1",
        "H2": "0",
        "TLSR": "0",
        "savespace": "0",
        "hasFlasher": "0",
        "hasBLE": "1",
        "hasSubGhz": "0",
        "apstate": "1",
        "channel": 0,
        "subghzchannel": 0,
        "alias": "",
        "led": 0,
        "tft": 20,
        "language": 2,
        "maxsleep": 0,
        "stopsleep": 1,
        "preview": 1,
        "nightlyreboot": 0,
        "lock": 0,
        "wifipower": 34,
        "timezone": "CET-1CEST-2,M3.5.0/02:00:00,M10.5.0/03:00:00",
        "sleeptime1": 0,
        "sleeptime2": 0,
        "ble": 0,
        "repo": "OpenEPaperLink/OpenEPaperLink",
        "env": "ESP32_S3_16_8_YELLOW_AP",
        "discovery": 0,
        "showtimestamp": 0,
    }


@pytest.fixture
def real_sysinfo_dict():
    """Real /sysinfo payload captured live from firmware 2.91."""
    return {
        "alias": "",
        "env": "ESP32_S3_16_8_YELLOW_AP",
        "buildtime": "1783441124",
        "buildversion": "2.91",
        "sha": "9dc57673f83e6a6aa4cf0310dbc97ad2da26c120",
        "psramsize": 8383159,
        "flashsize": 16777216,
        "rollback": True,
        "ap_version": 31,
        "hasC6": 1,
        "hasH2": 0,
        "hasTslr": 0,
        "hasFlasher": 0,
    }
