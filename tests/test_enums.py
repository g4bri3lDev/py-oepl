"""Tests for wire-format enum values."""

from oepl.enums import LUT, ContentMode, enum_label


def test_lut_values_match_firmware():
    # OpenEpaperLink/oepl-definitions.h:165-169
    assert LUT.DEFAULT == 0
    assert LUT.NO_REPEAT == 1
    assert LUT.FAST_NO_REDS == 2
    assert LUT.FAST == 3
    assert LUT.OTA == 0x10


def test_unknown_int_synthesizes_pseudo_member():
    member = ContentMode(99)
    assert member.name == "UNKNOWN_0x63"
    assert int(member) == 99
    assert member == 99


def test_unknown_int_is_cached_identity():
    assert ContentMode(99) is ContentMode(99)


def test_known_member_unaffected():
    assert ContentMode(25) is ContentMode.HOME_ASSISTANT


def test_enum_label_known_member():
    assert enum_label(ContentMode.HOME_ASSISTANT) == "Home Assistant"


def test_enum_label_multi_word_member():
    assert enum_label(LUT.FAST_NO_REDS) == "Fast No Reds"


def test_enum_label_unknown_member():
    assert enum_label(ContentMode(99)) == "Unknown 0x63"
