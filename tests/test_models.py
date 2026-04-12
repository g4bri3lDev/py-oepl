"""Tests for data model parsing."""
import pytest
from oepl.models import APConfig, APStatus, Tag, TagType
from oepl.enums import APState, RunStatus


def test_tag_from_dict(tag_dict):
    tag = Tag.from_dict(tag_dict)
    assert tag.mac == "AABBCCDDEEFF"
    assert tag.alias == "test-tag"
    assert tag.hw_type == 16
    assert tag.last_seen == 1700000000
    assert tag.next_update == 1700003600
    assert tag.next_checkin == 1700001800
    assert tag.pending == 0
    assert tag.content_mode == 25
    assert tag.lqi == 200
    assert tag.rssi == -65
    assert tag.temperature == 22
    assert tag.battery_mv == 3000
    assert tag.wakeup_reason == 0
    assert tag.capabilities == 0
    assert tag.rotate == 0
    assert tag.lut == 1
    assert tag.update_count == 5
    assert tag.is_external is False
    assert tag.ap_ip == "192.168.1.1"
    assert tag.channel == 11
    assert tag.firmware_version == 1337



def test_tag_labels_known(tag_dict):
    # tag_dict: contentMode=25, wakeupReason=0, rotate=0, lut=1, capabilities=0
    tag = Tag.from_dict(tag_dict)
    assert tag.content_mode_label == "Home Assistant"
    assert tag.wakeup_reason_label == "Timed"
    assert tag.rotate_label == "None"
    assert tag.lut_label == "No repeats"
    assert tag.capabilities_list == []


def test_tag_labels_unknown(tag_dict):
    tag_dict["contentMode"] = 999
    tag_dict["wakeupReason"] = 999
    tag_dict["rotate"] = 99
    tag_dict["lut"] = 99
    tag = Tag.from_dict(tag_dict)
    assert tag.content_mode_label == "999"
    assert tag.wakeup_reason_label == "999"
    assert tag.rotate_label == "99"
    assert tag.lut_label == "99"


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
        "currtime": 0, "heap": 0, "recordcount": 0, "apstate": 0, "runstate": 0,
        "rssi": 0, "wifissid": "", "uptime": 0, "dbsize": 0, "littlefsfree": 0,
        "wifistatus": 0, "lowbattcount": 0, "timeoutcount": 0,
    }
    assert APStatus.from_dict(sys_msg).ps_ram_free is None


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
