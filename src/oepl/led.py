"""LED pattern builder for OpenDisplay AP."""

from __future__ import annotations

from dataclasses import dataclass


def _int_to_hex2(n: int) -> str:
    """Convert integer to two-digit zero-padded hex string."""
    return hex(n)[2:].zfill(2)


@dataclass
class Color:
    """An RGB color used in an LED segment."""

    r: int
    g: int
    b: int

    def to_rgb332(self) -> str:
        """Encode as a 2-char hex RGB332 value.

        RGB332 packs 3 bits of red, 3 bits of green, and 2 bits of blue
        into a single byte. This is the format the AP uses for LED colors.
        """
        r = (max(0, min(255, self.r)) // 32) & 0b111
        g = (max(0, min(255, self.g)) // 32) & 0b111
        b = (max(0, min(255, self.b)) // 64) & 0b11
        return hex((r << 5) | (g << 2) | b)[2:].zfill(2)


@dataclass
class LEDSegment:
    """One color segment within an LED pattern."""

    color: Color
    flash_speed: float = 0.2  # seconds; AP encodes as floor(speed*10), 1 hex char
    flash_count: int = 2  # 1 hex char
    delay: float = 0.0  # seconds after segment; AP encodes as floor(delay*10), 2 hex chars

    def _encode(self) -> str:
        """Encode to 6 hex characters."""
        return (
            self.color.to_rgb332()
            + hex(int(self.flash_speed * 10))[2:]
            + hex(self.flash_count)[2:]
            + _int_to_hex2(int(self.delay * 10))
        )


@dataclass
class LEDPattern:
    """Complete LED pattern sent to the AP via /led_flash."""

    segments: list[LEDSegment]  # 1-3 segments; padded to 3 on encode
    repeats: int = 2  # Number of full-pattern repeats; encoded as repeats-1
    brightness: int = 2  # 1-16; packed into upper nibble of modebyte
    flash: bool = False  # Sets the flash bit in modebyte lower nibble

    def encode(self) -> str:
        """Encode the pattern to a 24-character hex string for the AP.

        Format: <modebyte><seg1><seg2><seg3><repeats><"00">
        Each segment is 6 chars; modebyte and repeats are 2 chars each.
        """
        modebyte = _int_to_hex2(((self.brightness - 1) << 4) | int(self.flash))
        segs = list(self.segments)
        # Pad to exactly 3 segments with silent zero-color segments
        while len(segs) < 3:
            segs.append(LEDSegment(Color(0, 0, 0), flash_speed=0.0, flash_count=0))
        encoded_segs = "".join(s._encode() for s in segs)
        return modebyte + encoded_segs + _int_to_hex2(self.repeats - 1) + "00"
