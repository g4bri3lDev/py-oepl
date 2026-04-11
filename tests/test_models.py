"""Tests for data model parsing."""
import pytest
from oepl.models import APStatus, Tag, TagType
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
