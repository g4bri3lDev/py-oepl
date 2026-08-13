"""Tests for data model parsing."""

import pytest

from oepl.enums import (
    LUT,
    APState,
    ContentMode,
    Rotation,
    RunStatus,
    TagCapability,
    WakeupReason,
)
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


def test_tag_from_dict_malformed_int_falls_back_to_default(tag_dict):
    """A present-but-malformed value (e.g. a firmware bug) must fall back to the typed
    default rather than being stored as-is and raising later inside last_seen_at."""
    tag_dict["lastseen"] = "x"
    tag = Tag.from_dict(tag_dict)
    assert tag.last_seen == 0
    assert tag.last_seen_at is None
    # The raw value is preserved verbatim for diagnostics.
    assert tag.raw["lastseen"] == "x"


def test_tag_capabilities_list(tag_dict):
    tag_dict["capabilities"] = 0x0043  # LED | Compression | NFC
    tag = Tag.from_dict(tag_dict)
    assert tag.capabilities_list == ["LED", "Compression", "NFC"]


def test_tag_capability_flags_match_firmware(tag_dict):
    """Bit values must match the firmware's CAPABILITY_* constants."""
    assert TagCapability.LED == 0x01
    assert TagCapability.COMPRESSION == 0x02
    assert TagCapability.CUSTOM_LUTS == 0x04
    assert TagCapability.ALT_LUT_SIZE == 0x08
    assert TagCapability.EXT_POWER == 0x10
    assert TagCapability.WAKE_BUTTON == 0x20
    assert TagCapability.NFC == 0x40
    assert TagCapability.NFC_WAKE == 0x80
    assert TagCapability.BLE == 0x0100

    tag_dict["capabilities"] = 0x00C3  # LED | Compression | NFC | NFC_WAKE
    flags = Tag.from_dict(tag_dict).capability_flags
    assert TagCapability.NFC in flags
    assert TagCapability.NFC_WAKE in flags
    assert TagCapability.LED in flags
    assert TagCapability.WAKE_BUTTON not in flags


def test_tag_capability_flags_ignores_unknown_bits(tag_dict):
    """Unknown high bits must not break flag construction."""
    tag_dict["capabilities"] = 0xF001
    assert Tag.from_dict(tag_dict).capability_flags is TagCapability.LED


def test_tagtype_option_helpers():
    """Buttons and LEDs are declared by the tag type's options list."""
    base = {"width": 296, "height": 128}

    both = TagType.from_dict(0x33, {**base, "options": ["button", "led"]})
    assert both.has_button
    assert both.has_led

    button_only = TagType.from_dict(0x01, {**base, "options": ["button"]})
    assert button_only.has_button
    assert not button_only.has_led

    none = TagType.from_dict(0xE0, {**base, "options": []})
    assert not none.has_button
    assert not none.has_led

    # Missing "options" entirely must not raise.
    assert not TagType.from_dict(0xE0, base).has_button


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


def test_apstatus_malformed_int_fields_fall_back_to_defaults():
    """Present-but-malformed values must not raise; they fall back like missing keys."""
    sys_msg = {
        "currtime": "not-a-number",
        "heap": None,
        "psfree": "also-not-a-number",
    }
    status = APStatus.from_dict(sys_msg)
    assert status.current_time == 0
    assert status.heap == 0
    assert status.ps_ram_free is None


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


@pytest.mark.parametrize("bad_apstate", ["", "garbage", None])
def test_apconfig_apstate_tolerant_of_bad_values(real_apconfig_dict, bad_apstate):
    """apstate '' / 'garbage' / None must not crash from_dict; parses as OFFLINE."""
    real_apconfig_dict["apstate"] = bad_apstate
    cfg = APConfig.from_dict(real_apconfig_dict)
    assert cfg.ap_state is APState.OFFLINE


def test_wificonfig_from_dict():
    from oepl.models import WifiConfig

    data = {
        "ssid": "my-network",
        "pw": "hunter2",
        "ip": "192.168.1.50",
        "mask": "255.255.255.0",
        "gw": "192.168.1.1",
        "dns": "192.168.1.1",
        "mac": "AA:BB:CC:DD:EE:FF",
    }
    cfg = WifiConfig.from_dict(data)
    assert cfg.ssid == "my-network"
    assert cfg.password == "hunter2"
    assert cfg.ip == "192.168.1.50"
    assert cfg.mask == "255.255.255.0"
    assert cfg.gateway == "192.168.1.1"
    assert cfg.dns == "192.168.1.1"
    assert cfg.mac == "AA:BB:CC:DD:EE:FF"
    assert cfg.raw == data


def test_wificonfig_tolerant_missing_keys():
    from oepl.models import WifiConfig

    cfg = WifiConfig.from_dict({})
    assert cfg.ssid == ""
    assert cfg.password == ""
    assert cfg.mac == ""


def test_ssidlist_from_dict():
    from oepl.models import SSIDList

    data = {
        "scanstatus": 2,
        "networks": [
            {"ssid": "net-a", "ch": 6, "rssi": -50, "enc": 3},
            {"ssid": "net-b", "ch": 11, "rssi": -70, "enc": 4},
        ],
    }
    result = SSIDList.from_dict(data)
    assert result.scan_status == 2
    assert len(result.networks) == 2
    assert result.networks[0].ssid == "net-a"
    assert result.networks[0].channel == 6
    assert result.networks[0].rssi == -50
    assert result.networks[0].encryption == 3
    assert result.networks[1].ssid == "net-b"
    assert result.raw == data


def test_ssidlist_tolerant_missing_keys():
    from oepl.models import SSIDList

    result = SSIDList.from_dict({})
    assert result.scan_status == 0
    assert result.networks == []


def test_ssidlist_scanning_status():
    """scan_status can be -1 (scanning) or -2 (not started) per WiFi.scanComplete()."""
    from oepl.models import SSIDList

    result = SSIDList.from_dict({"scanstatus": -1, "networks": []})
    assert result.scan_status == -1


def test_apconfig_lock_is_tristate(apconfig_dict):
    """Inventory lock has three states, so it cannot be a boolean.

    The firmware distinguishes 1 (reject new tags) from 2 (accept only tags
    that are booting); collapsing them would lose the learning mode.
    """
    for raw, expected in ((0, 0), (1, 1), (2, 2)):
        assert APConfig.from_dict({**apconfig_dict, "lock": raw}).lock == expected


def test_apconfig_lock_round_trips(apconfig_dict):
    """Learning mode must survive being written back."""
    config = APConfig.from_dict({**apconfig_dict, "lock": 2})
    assert config.to_dict()["lock"] == 2


def test_apconfig_exposes_valid_choices():
    """Consumers need the value sets, not just a label for the current value.

    Home Assistant reinvented these and got several wrong: LED and TFT
    brightness use different steps, and the language numbering is not
    alphabetical.
    """
    assert APConfig.LED_BRIGHTNESS_LEVELS != APConfig.TFT_BRIGHTNESS_LEVELS
    assert APConfig.LED_BRIGHTNESS_LEVELS[15] == "10%"
    assert APConfig.TFT_BRIGHTNESS_LEVELS[20] == "10%"
    assert APConfig.LANGUAGES[3] == "Norsk"
    assert APConfig.LANGUAGES[4] == "Français"
    assert APConfig.CHANNELS[0] == "automatic"
    assert set(APConfig.LOCK_MODES) == {0, 1, 2}


def test_apconfig_labels_come_from_the_public_maps(apconfig_dict):
    """A label is just a lookup in the same map callers can enumerate."""
    config = APConfig.from_dict({**apconfig_dict, "lock": 2, "channel": 0})
    assert config.lock_label == APConfig.LOCK_MODES[2]
    assert config.channel_label == APConfig.CHANNELS[0]


def test_tagtype_accent_color():
    """A two-colour panel has no accent, and must not claim one."""
    base = {"width": 296, "height": 152}
    mono = TagType.from_dict(0x01, {**base, "colortable": {"white": [], "black": []}})
    bwr = TagType.from_dict(0x04, {**base, "colortable": {"white": [], "black": [], "red": []}})
    bwy = TagType.from_dict(0x60, {**base, "colortable": {"white": [], "black": [], "yellow": []}})
    assert mono.accent_color is None
    assert bwr.accent_color == "red"
    assert bwy.accent_color == "yellow"


def test_tag_battery_sentinels_are_not_measurements(tag_dict):
    """1337 mV means the tag has no usable reading, not a flat battery.

    The firmware and the Access Point's own web interface both exclude 0 and
    1337 wherever they touch battery values.
    """
    for mv in (0, 1337):
        tag = Tag.from_dict({**tag_dict, "batteryMv": mv})
        assert not tag.has_battery_reading
        assert tag.battery_low is None


def test_tag_battery_low_matches_the_firmware_threshold(tag_dict):
    """The firmware counts a tag as low below 2400 mV."""
    assert Tag.from_dict({**tag_dict, "batteryMv": 2399}).battery_low is True
    assert Tag.from_dict({**tag_dict, "batteryMv": 2400}).battery_low is False


def test_rotation_degrees():
    """The wire value is a quarter-turn count, not degrees."""
    assert [r.degrees for r in Rotation] == [0, 90, 180, 270]
