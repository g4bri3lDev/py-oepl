"""LED pattern builder for OpenEPaperLink AP."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


def _int_to_hex2(n: int) -> str:
    """Convert integer to two-digit zero-padded hex string."""
    return hex(n)[2:].zfill(2)


class LEDPatternMode(IntEnum):
    """LED pattern mode: byte0 LOW nibble of the ``ledFlash`` struct."""

    OFF = 0  # stop any running flash pattern
    FLASH = 1


@dataclass
class Color:
    """An RGB color used in an LED segment."""

    r: int
    g: int
    b: int

    @classmethod
    def from_hex(cls, value: str) -> "Color":
        """Build a Color from a hex string like ``"#ff0000"`` or ``"ff0000"``."""
        value = value.lstrip("#")
        return cls(int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))

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

    def _validate(self) -> None:
        for channel in (self.color.r, self.color.g, self.color.b):
            if not 0 <= channel <= 255:
                raise ValueError(f"Color channel {channel} out of range 0..255")
        if not 0 <= self.flash_count <= 15:
            raise ValueError(f"flash_count {self.flash_count} out of range 0..15")
        speed_units = int(self.flash_speed * 10)
        if not 0 <= speed_units <= 15:
            raise ValueError(f"flash_speed {self.flash_speed} out of range (0..1.5s)")
        delay_units = int(self.delay * 10)
        if not 0 <= delay_units <= 255:
            raise ValueError(f"delay {self.delay} out of range (0..25.5s)")

    def _encode(self) -> str:
        """Encode to 6 hex characters."""
        self._validate()
        return (
            self.color.to_rgb332()
            + hex(int(self.flash_speed * 10))[2:]
            + hex(self.flash_count)[2:]
            + _int_to_hex2(int(self.delay * 10))
        )


@dataclass
class LEDPattern:
    """Complete LED pattern sent to the AP via /led_flash.

    Wire format is the firmware's ``struct ledFlash`` (``OpenEpaperLink/oepl-proto.h``),
    12 bytes encoded as 24 hex characters.
    """

    segments: list[LEDSegment]  # 1-3; padded to 3 zero segments on encode
    repeats: int = 2  # 1..256; encoded as repeats-1
    # 1..16; encoded as (brightness-1) in byte0 HIGH nibble. The protocol struct
    # calls this nibble "flashDuration", but the ecosystem UI presents it as brightness.
    brightness: int = 2
    mode: LEDPatternMode = LEDPatternMode.FLASH  # byte0 LOW nibble

    def encode(self) -> str:
        """Encode the pattern to a 24-character hex string for the AP.

        Format: <byte0><seg1><seg2><seg3><repeats><"00">
        Each segment is 6 chars; byte0 and repeats are 2 chars each.
        """
        if not 1 <= len(self.segments) <= 3:
            raise ValueError(f"segments must contain 1-3 entries, got {len(self.segments)}")
        if not 1 <= self.brightness <= 16:
            raise ValueError(f"brightness {self.brightness} out of range 1..16")
        if not 1 <= self.repeats <= 256:
            raise ValueError(f"repeats {self.repeats} out of range 1..256")

        byte0 = _int_to_hex2(((self.brightness - 1) << 4) | int(self.mode))
        segs = list(self.segments)
        # Pad to exactly 3 segments with silent zero-color segments
        while len(segs) < 3:
            segs.append(LEDSegment(Color(0, 0, 0), flash_speed=0.0, flash_count=0))
        encoded_segs = "".join(s._encode() for s in segs)
        return byte0 + encoded_segs + _int_to_hex2(self.repeats - 1) + "00"

    @classmethod
    def single(
        cls,
        color: Color,
        *,
        flash_count: int = 2,
        flash_speed: float = 0.2,
        delay: float = 0.0,
        repeats: int = 2,
        brightness: int = 2,
    ) -> "LEDPattern":
        """Build a single-segment flash pattern."""
        return cls(
            segments=[LEDSegment(color, flash_speed=flash_speed, flash_count=flash_count, delay=delay)],
            repeats=repeats,
            brightness=brightness,
            mode=LEDPatternMode.FLASH,
        )

    @classmethod
    def off(cls) -> "LEDPattern":
        """Build a pattern that stops any running flash on the tag."""
        return cls(
            segments=[LEDSegment(Color(0, 0, 0), flash_speed=0.0, flash_count=0)],
            repeats=1,
            brightness=1,
            mode=LEDPatternMode.OFF,
        )
