"""Tests for wire-format enum values."""

from oepl.enums import LUT


def test_lut_values_match_firmware():
    # OpenEpaperLink/oepl-definitions.h:165-169
    assert LUT.DEFAULT == 0
    assert LUT.NO_REPEAT == 1
    assert LUT.FAST_NO_REDS == 2
    assert LUT.FAST == 3
    assert LUT.OTA == 0x10
