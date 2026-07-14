"""Tests for LED pattern encoding."""

import pytest

from oepl.led import Color, LEDPattern, LEDPatternMode, LEDSegment


def test_rgb_to_rgb332_red():
    assert Color(255, 0, 0).to_rgb332() == "e0"


def test_rgb_to_rgb332_green():
    assert Color(0, 255, 0).to_rgb332() == "1c"


def test_rgb_to_rgb332_blue():
    assert Color(0, 0, 255).to_rgb332() == "03"


def test_rgb_to_rgb332_white():
    assert Color(255, 255, 255).to_rgb332() == "ff"


def test_rgb_to_rgb332_black():
    assert Color(0, 0, 0).to_rgb332() == "00"


def test_color_from_hex_with_hash():
    assert Color.from_hex("#ff0000") == Color(255, 0, 0)


def test_color_from_hex_without_hash():
    assert Color.from_hex("ff0000") == Color(255, 0, 0)


def test_led_encode_length():
    pattern = LEDPattern([LEDSegment(Color(255, 0, 0))])
    assert len(pattern.encode()) == 24


def test_led_encode_known():
    # Red segment, defaults: brightness=2, mode=FLASH, repeats=2
    # byte0: ((2-1) << 4) | 1 = 0x11 -> "11"
    # seg1: Color(255,0,0).to_rgb332() = "e0", flash_speed=0.2 -> int(0.2*10)=2 -> "2",
    #        flash_count=2 -> "2", delay=0.0 -> int(0.0*10)=0 -> "00" -> "e02200"
    # seg2,3: zero segments -> "000000"
    # repeats: 2-1=1 -> "01"; trailer: "00"
    result = LEDPattern(
        [LEDSegment(Color(255, 0, 0), flash_speed=0.2, flash_count=2, delay=0.0)],
        repeats=2,
        brightness=2,
        mode=LEDPatternMode.FLASH,
    ).encode()
    assert result == "11" + "e02200" + "000000" + "000000" + "01" + "00"


def test_led_off_encodes_all_zero():
    assert LEDPattern.off().encode() == "00" * 12


def test_led_segment_padding():
    pattern = LEDPattern([LEDSegment(Color(0, 255, 0))])
    encoded = pattern.encode()
    # Should be exactly 24 chars regardless of segment count
    assert len(encoded) == 24
    # Segments 2 and 3 should be zeroed out
    # byte0(2) + seg1(6) + seg2(6) + seg3(6) + repeats(2) + "00"(2) = 24
    seg2 = encoded[8:14]
    seg3 = encoded[14:20]
    assert seg2 == "000000"
    assert seg3 == "000000"


def test_led_brightness_max_flash():
    # brightness=16 (max), mode=FLASH
    # byte0: ((16-1) << 4) | 1 = 0xf1
    pattern = LEDPattern(
        [LEDSegment(Color(0, 0, 0), flash_speed=0.0, flash_count=0)],
        brightness=16,
        mode=LEDPatternMode.FLASH,
    )
    encoded = pattern.encode()
    assert encoded[:2] == "f1"


def test_led_firmware_example():
    # firmware "ledflash" example (web.cpp:476):
    # mode=1, flashDuration=8, colors that RGB332-encode to 0x3C/0xE4/0x03,
    # counts 3/3/3, speeds 1/5/10, delays 10/10/10 (=1.0s), repeats 2
    # brightness=9 -> high nibble 8 -> byte0 = 0x81
    pattern = LEDPattern(
        segments=[
            LEDSegment(Color.from_hex("20ff00"), flash_speed=0.1, flash_count=3, delay=1.0),
            LEDSegment(Color.from_hex("ff2000"), flash_speed=0.5, flash_count=3, delay=1.0),
            LEDSegment(Color.from_hex("0000ff"), flash_speed=1.0, flash_count=3, delay=1.0),
        ],
        repeats=2,
        brightness=9,
        mode=LEDPatternMode.FLASH,
    )
    assert pattern.encode() == "81" + "3c130a" + "e4530a" + "03a30a" + "01" + "00"


def test_led_pattern_single():
    pattern = LEDPattern.single(Color(255, 0, 0))
    assert pattern.encode() == "11" + "e02200" + "000000" + "000000" + "01" + "00"


class TestLEDPatternValidation:
    def test_no_segments(self):
        with pytest.raises(ValueError):
            LEDPattern([]).encode()

    def test_too_many_segments(self):
        segs = [LEDSegment(Color(0, 0, 0)) for _ in range(4)]
        with pytest.raises(ValueError):
            LEDPattern(segs).encode()

    def test_brightness_too_low(self):
        with pytest.raises(ValueError):
            LEDPattern([LEDSegment(Color(0, 0, 0))], brightness=0).encode()

    def test_brightness_too_high(self):
        with pytest.raises(ValueError):
            LEDPattern([LEDSegment(Color(0, 0, 0))], brightness=17).encode()

    def test_repeats_too_low(self):
        with pytest.raises(ValueError):
            LEDPattern([LEDSegment(Color(0, 0, 0))], repeats=0).encode()

    def test_repeats_too_high(self):
        with pytest.raises(ValueError):
            LEDPattern([LEDSegment(Color(0, 0, 0))], repeats=257).encode()

    def test_flash_count_too_high(self):
        with pytest.raises(ValueError):
            LEDPattern([LEDSegment(Color(0, 0, 0), flash_count=16)]).encode()

    def test_flash_count_negative(self):
        with pytest.raises(ValueError):
            LEDPattern([LEDSegment(Color(0, 0, 0), flash_count=-1)]).encode()

    def test_flash_speed_too_high(self):
        with pytest.raises(ValueError):
            LEDPattern([LEDSegment(Color(0, 0, 0), flash_speed=1.6)]).encode()

    def test_delay_too_high(self):
        with pytest.raises(ValueError):
            LEDPattern([LEDSegment(Color(0, 0, 0), delay=25.6)]).encode()

    def test_color_channel_too_high(self):
        with pytest.raises(ValueError):
            LEDPattern([LEDSegment(Color(256, 0, 0))]).encode()

    def test_color_channel_negative(self):
        with pytest.raises(ValueError):
            LEDPattern([LEDSegment(Color(-1, 0, 0))]).encode()
