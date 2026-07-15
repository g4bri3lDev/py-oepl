"""Tests for image decoding."""

from oepl.image import _decode_esl_raw, decode_image
from oepl.models import TagType


def make_tag_type(width: int = 296, height: int = 128, bpp: int = 2) -> TagType:
    return TagType(
        type_id=16,
        width=width,
        height=height,
        bpp=bpp,
        color_table={
            "white": [255, 255, 255],
            "black": [0, 0, 0],
            "red": [255, 0, 0],
        },
    )


def test_decode_image_returns_jpeg():
    """decode_image returns bytes that start with the JPEG magic number."""
    tt = make_tag_type()
    # Create uncompressed raw bitmap: all white pixels
    # 2bpp, width=296, height=128: bytes_per_row = ceil(296/8)=37, total=37*128*2=9472
    bytes_per_row = (tt.width + 7) // 8
    plane_size = bytes_per_row * tt.height
    raw = b"\xff" * plane_size + b"\x00" * plane_size  # white black plane, empty color plane

    result = decode_image(raw, tt)

    # JPEG starts with FF D8 FF
    assert result[:2] == b"\xff\xd8"


def test_decode_image_monochrome():
    """1bpp image decodes without error."""
    tt = make_tag_type(bpp=1)
    bytes_per_row = (tt.width + 7) // 8
    raw = b"\xff" * (bytes_per_row * tt.height)  # all white

    result = decode_image(raw, tt)
    assert result[:2] == b"\xff\xd8"


def test_decode_esl_raw_uncompressed_padding():
    """Short raw data gets zero-padded to the expected size."""
    tt = make_tag_type(width=16, height=8, bpp=1)
    # Expected: bytes_per_row=2, total=2*8=16 bytes
    raw = b"\xff\xff"  # only 2 bytes, short
    result = _decode_esl_raw(raw, tt)
    assert len(result) == 16


def test_decode_esl_raw_g5_falls_through():
    """Data that looks like but isn't valid G5 falls through to raw handling."""
    tt = make_tag_type()
    # Craft data that triggers the G5 header parse but fails validation
    # G5 header: header_size=6, width=10, height=10, compression_mode=1
    bad_g5 = bytes([6, 10, 0, 10, 0, 1]) + b"\x00" * 20
    # Should not raise; will fall through and return padded/raw data
    result = _decode_esl_raw(bad_g5, tt)
    assert isinstance(result, bytes)


def test_decode_esl_raw_g5_matching_geometry_but_malformed_falls_through():
    """A G5 payload whose header geometry matches the tag but whose stream is
    truncated/malformed must not leak a raw IndexError out of decode.

    The header (152x200, mode=1) passes the _looks_like_g5 sniff for this tag,
    so a real decode is attempted; the codec must translate the internal
    bounds error into a G5DecoderError, which _decode_esl_raw swallows and
    falls through to zlib/raw handling.
    """
    tt = TagType(
        type_id=103,
        width=152,
        height=200,
        bpp=2,
        color_table={"white": [255, 255, 255], "black": [0, 0, 0], "red": [255, 0, 0]},
    )
    payload = bytes.fromhex("069800c80001a747054965")  # header 152x200 mode=1
    result = _decode_esl_raw(payload, tt)
    assert isinstance(result, bytes)
