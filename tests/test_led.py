"""Tests for LED pattern encoding."""
import pytest
from oepl.led import Color, LEDPattern, LEDSegment


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


def test_led_encode_length():
    pattern = LEDPattern([LEDSegment(Color(255, 0, 0))])
    assert len(pattern.encode()) == 24


def test_led_encode_known():
    # Red segment, defaults: brightness=2, flash=False, repeats=2
    # modebyte: ((2-1) << 4) | 0 = 0x10 → "10"
    # seg1: Color(255,0,0).to_rgb332() = "e0", flash_speed=0.2 → int(0.2*10)=2 → "2",
    #        flash_count=2 → "2", delay=0.0 → int(0.0*10)=0 → "00" → "e02200"
    # seg2,3: zero segments → "000000"
    # repeats: 2-1=1 → "01"; trailer: "00"
    result = LEDPattern(
        [LEDSegment(Color(255, 0, 0), flash_speed=0.2, flash_count=2, delay=0.0)],
        repeats=2,
        brightness=2,
        flash=False,
    ).encode()
    assert result == "10" + "e02200" + "000000" + "000000" + "01" + "00"


def test_led_segment_padding():
    pattern = LEDPattern([LEDSegment(Color(0, 255, 0))])
    encoded = pattern.encode()
    # Should be exactly 24 chars regardless of segment count
    assert len(encoded) == 24
    # Segments 2 and 3 should be zeroed out
    # modebyte(2) + seg1(6) + seg2(6) + seg3(6) + repeats(2) + "00"(2) = 24
    seg2 = encoded[8:14]
    seg3 = encoded[14:20]
    assert seg2 == "000000"
    assert seg3 == "000000"


def test_led_brightness_flash():
    # brightness=16 (max), flash=True
    # modebyte: ((16-1) << 4) | 1 = 0xf1
    pattern = LEDPattern(
        [LEDSegment(Color(0, 0, 0), flash_speed=0.0, flash_count=0)],
        brightness=16,
        flash=True,
    )
    encoded = pattern.encode()
    assert encoded[:2] == "f1"
