"""Tests for data model parsing."""

import pytest

from oepl.enums import LUT, APState, ContentMode, Rotation, RunStatus, WakeupReason
from oepl.models import APConfig, APInfo, APStatus, Tag, TagType


def test_tag_from_dict(tag_dict):
    tag = Tag.from_dict(tag_dict)
    assert tag.mac == "AABBCCDDEEFF"
    assert tag.alias == "test-tag"
    assert tag.hw_type == 16
    assert tag.last_seen == 1700000000
    assert tag.next_update == 1700003600
    assert tag.next_checkin == 1700001800
    assert tag.pending == 0
    assert tag.content_mode == ContentMode.HOME_ASSISTANT
    assert tag.lqi == 200
    assert tag.rssi == -65
    assert tag.temperature == 22
    assert tag.battery_mv == 3000
    assert tag.wakeup_reason == WakeupReason.TIMED
    assert tag.capabilities == 0
    assert tag.rotate == Rotation.NONE
    assert tag.lut == LUT.NO_REPEAT
    assert tag.update_count == 5
    assert tag.is_external is False
    assert tag.ap_ip == "192.168.1.1"
    assert tag.channel == 11
    assert tag.firmware_version == 1337


def test_tag_capabilities_list(tag_dict):
    tag_dict["capabilities"] = 0x0043  # LED | Compression | NFC
    tag = Tag.from_dict(tag_dict)
    assert tag.capabilities_list == ["LED", "Compression", "NFC"]


def test_apconfig_labels(apconfig_dict):
    # apconfig_dict: led=127→50%, tft=128→50%, language=0→English,
    #                maxsleep=10→10 min, wifipower=78→19.5 dBm
    cfg = APConfig.from_dict(apconfig_dict)
    assert cfg.led_brightness_label == "50%"
    assert cfg.tft_brightness_label == "50%"
    assert cfg.language_label == "English"
    assert cfg.max_sleep_label == "10 min"
    assert cfg.wifi_power_label == "19.5 dBm"


def test_apconfig_labels_unknown(apconfig_dict):
    apconfig_dict["wifipower"] = 99
    apconfig_dict["led"] = 99
    apconfig_dict["tft"] = 99
    apconfig_dict["language"] = 99
    apconfig_dict["maxsleep"] = 99
    cfg = APConfig.from_dict(apconfig_dict)
    assert cfg.wifi_power_label == "99"
    assert cfg.led_brightness_label == "99"
    assert cfg.tft_brightness_label == "99"
    assert cfg.language_label == "99"
    assert cfg.max_sleep_label == "99 min"


def test_apstatus_from_dict():
    sys_msg = {
        "currtime": 1700000000,
        "heap": 200000,
        "recordcount": 10,
        "apstate": 1,
        "runstate": 2,
        "rssi": -70,
        "wifissid": "MyWiFi",
        "uptime": 3600,
        "dbsize": 4096,
        "littlefsfree": 8192,
        "psfree": 1024000,
        "wifistatus": 1,
        "lowbattcount": 0,
        "timeoutcount": 1,
    }
    status = APStatus.from_dict(sys_msg)
    assert status.current_time == 1700000000
    assert status.heap == 200000
    assert status.record_count == 10
    assert status.ap_state == APState.ONLINE
    assert status.run_state == RunStatus.RUN
    assert status.rssi == -70
    assert status.wifi_ssid == "MyWiFi"
    assert status.uptime == 3600
    assert status.db_size == 4096
    assert status.little_fs_free == 8192
    assert status.ps_ram_free == 1024000
    assert status.wifi_status == 1
    assert status.low_battery_count == 0
    assert status.timeout_count == 1


def test_apstatus_no_psram():
    """ps_ram_free is None on boards without PSRAM."""
    sys_msg = {
        "currtime": 0,
        "heap": 0,
        "recordcount": 0,
        "apstate": 0,
        "runstate": 0,
        "rssi": 0,
        "wifissid": "",
        "uptime": 0,
        "dbsize": 0,
        "littlefsfree": 0,
        "wifistatus": 0,
        "lowbattcount": 0,
        "timeoutcount": 0,
    }
    assert APStatus.from_dict(sys_msg).ps_ram_free is None


def test_apstatus_missing_lowbatt_timeout_counts():
    """P0-4 regression: lowbattcount/timeoutcount are only sent ~once/minute.

    Their absence must not raise — on_ap_status must fire for every 'sys'
    message, not just the once-a-minute ones that happen to include these keys.
    """
    sys_msg = {
        "currtime": 1700000000,
        "heap": 200000,
        "recordcount": 10,
        "apstate": 1,
        "runstate": 2,
        "rssi": -70,
        "wifissid": "MyWiFi",
        "uptime": 3600,
        "dbsize": 4096,
        "littlefsfree": 8192,
        "psfree": 1024000,
        "wifistatus": 1,
        # lowbattcount / timeoutcount intentionally absent
    }
    status = APStatus.from_dict(sys_msg)
    assert status.low_battery_count is None
    assert status.timeout_count is None


def test_tagtype_from_dict():
    data = {
        "version": 2,
        "name": "Solum 2.9 BWR",
        "width": 296,
        "height": 128,
        "rotatebuffer": 0,
        "bpp": 2,
        "colortable": {"white": [255, 255, 255], "black": [0, 0, 0], "red": [255, 0, 0]},
        "shortlut": 2,
        "options": [],
        "contentids": [1, 2, 3],
        "template": {},
        "usetemplate": None,
        "zlib_compression": None,
    }
    tt = TagType.from_dict(type_id=16, data=data)
    assert tt.type_id == 16
    assert tt.name == "Solum 2.9 BWR"
    assert tt.width == 296
    assert tt.height == 128
    assert tt.bpp == 2
    assert "red" in tt.color_table
    assert tt.short_lut == 2
    assert tt.content_ids == [1, 2, 3]
    assert tt.raw == data


# ── real firmware payloads (captured live from fw 2.91) ────────────────────


def test_tag_from_real_payload(real_tag_dict):
    tag = Tag.from_dict(real_tag_dict)
    assert tag.mac == "00000335042F3E10"
    assert tag.hash == "1b00000000c2cb3fc88ccb3f5c6f0540"
    assert tag.alias == "MVG 22"
    assert tag.content_mode is ContentMode.HOME_ASSISTANT
    assert tag.modecfgjson == '{"filename":"/temp/x.jpg","dither":"2"}'
    assert tag.invert is False
    assert tag.update_last == 0
    assert tag.hw_type == 4
    assert tag.raw == real_tag_dict


def test_tag_raw_retention(real_tag_dict):
    tag = Tag.from_dict(real_tag_dict)
    assert tag.raw == real_tag_dict
    assert tag.raw is not real_tag_dict


def test_tag_unknown_enum_values(real_tag_dict):
    real_tag_dict["contentMode"] = 99
    real_tag_dict["lut"] = 7
    tag = Tag.from_dict(real_tag_dict)
    assert tag.content_mode.name == "UNKNOWN_0x63"
    assert int(tag.content_mode) == 99
    assert tag.lut.name == "UNKNOWN_0x07"
    assert int(tag.lut) == 7


@pytest.mark.parametrize(
    "dropped_key",
    [
        "hash",
        "lastseen",
        "nextupdate",
        "nextcheckin",
        "pending",
        "alias",
        "contentMode",
        "LQI",
        "RSSI",
        "temperature",
        "batteryMv",
        "hwType",
        "wakeupReason",
        "capabilities",
        "modecfgjson",
        "isexternal",
        "apip",
        "rotate",
        "lut",
        "invert",
        "updatecount",
        "updatelast",
        "ch",
        "ver",
    ],
)
def test_tag_tolerant_missing_key(real_tag_dict, dropped_key):
    del real_tag_dict[dropped_key]
    # Must not raise; typed default is used instead.
    Tag.from_dict(real_tag_dict)


def test_tag_empty_dict_except_mac():
    tag = Tag.from_dict({"mac": "AABBCCDDEEFF"})
    assert tag.mac == "AABBCCDDEEFF"
    assert tag.alias == ""
    assert tag.hash == ""
    assert tag.modecfgjson == ""
    assert tag.invert is False
    assert tag.update_last == 0
    assert tag.content_mode is ContentMode.NOT_CONFIGURED
    assert tag.wakeup_reason is WakeupReason.TIMED
    assert tag.lut is LUT.DEFAULT
    assert tag.rotate is Rotation.NONE


def test_tag_missing_mac_raises():
    with pytest.raises(ValueError):
        Tag.from_dict({"alias": "no-mac"})


def test_tag_timestamp_properties_zero_is_none():
    tag = Tag.from_dict({"mac": "AABBCCDDEEFF", "lastseen": 0, "nextupdate": 0, "nextcheckin": 0, "updatelast": 0})
    assert tag.last_seen_at is None
    assert tag.next_update_at is None
    assert tag.next_checkin_at is None
    assert tag.update_last_at is None


def test_tag_timestamp_properties_real_epoch(real_tag_dict):
    tag = Tag.from_dict(real_tag_dict)
    assert tag.last_seen_at is not None
    assert tag.last_seen_at.tzinfo is not None
    assert tag.next_checkin_at is not None
    assert tag.next_checkin_at.tzinfo is not None


def test_apconfig_from_real_payload(real_apconfig_dict):
    cfg = APConfig.from_dict(real_apconfig_dict)
    assert cfg.ap_state is APState.ONLINE
    assert cfg.tlsr is False
    assert cfg.save_space is False
    assert cfg.has_flasher is False
    assert cfg.has_c6 is True
    assert cfg.has_h2 is False
    assert cfg.has_ble is True
    assert cfg.has_sub_ghz is False
    assert cfg.channel == 0
    assert cfg.wifi_power == 34


def test_apconfig_to_dict_roundtrip_excludes_readonly_fields(real_apconfig_dict):
    cfg = APConfig.from_dict(real_apconfig_dict)
    out = cfg.to_dict()
    for key in ("apstate", "TLSR", "savespace", "hasFlasher", "hasBLE", "hasSubGhz", "C6", "H2"):
        assert key not in out
    # Wire keys for writable fields are preserved exactly.
    assert out["channel"] == 0
    assert out["wifipower"] == 34
    assert out["timezone"] == real_apconfig_dict["timezone"]
    assert out["env"] == real_apconfig_dict["env"]
    assert out["repo"] == real_apconfig_dict["repo"]


def test_apconfig_tolerant_missing_keys():
    cfg = APConfig.from_dict({})
    assert cfg.ap_state is APState.OFFLINE
    assert cfg.tlsr is False
    assert cfg.channel == 0
    assert cfg.alias == ""


def test_apinfo_from_real_payload(real_sysinfo_dict):
    info = APInfo.from_dict(real_sysinfo_dict)
    assert info.sha == "9dc57673f83e6a6aa4cf0310dbc97ad2da26c120"
    assert info.has_tslr is False
    assert info.has_flasher is False
    assert info.build_version == "2.91"
    assert info.psram_size == 8383159
    assert info.can_rollback is True


def test_apinfo_tolerant_missing_keys():
    info = APInfo.from_dict({})
    assert info.sha == ""
    assert info.has_tslr is False
    assert info.has_flasher is False
    assert info.alias == ""
