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


# Tag type 0xBB ("Gicisky BLE EPD BWRY 2.9\"") as the AP serves it: bpp 5 is
# BPP_PACKED_2BIT, 2 bits per pixel indexing the colortable, MSB first.
def make_bwry_tag_type() -> TagType:
    return TagType(
        type_id=0xBB,
        width=296,
        height=128,
        rotatebuffer=1,
        bpp=5,
        color_table={
            "black": [0, 0, 0],
            "white": [255, 255, 255],
            "yellow": [255, 255, 0],
            "red": [255, 0, 0],
        },
    )


# Four vertical bands on the displayed image, one per colour table index
BWRY_BANDS = [1, 0, 3, 2]  # white, black, red, yellow


def _bwry_band(x: int, width: int) -> int:
    return BWRY_BANDS[x * len(BWRY_BANDS) // width]


def _make_packed_2bit(tt: TagType) -> bytes:
    """Pack a banded image like the AP: rotated buffer, 2 bits/pixel, MSB first."""
    from PIL import Image

    row = bytes(_bwry_band(x, tt.width) for x in range(tt.width))
    shown = Image.frombytes("L", (tt.width, tt.height), row * tt.height)
    # rotatebuffer 1: the buffer is the displayed image turned 90° counter-clockwise
    indices = shown.transpose(Image.Transpose.ROTATE_90).tobytes()
    out = bytearray()
    for i in range(0, len(indices), 4):
        a, b, c, d = indices[i : i + 4]
        out.append(a << 6 | b << 4 | c << 2 | d)
    return bytes(out)


def _assert_bwry_bands(img, tt: TagType) -> None:
    assert img.size == (tt.width, tt.height)
    colours = list(tt.color_table.values())
    for x in (10, 100, 180, 280):
        want = tuple(colours[_bwry_band(x, tt.width)])
        for y in (5, 64, 120):
            assert img.getpixel((x, y)) == want, (x, y)


def test_decode_packed_2bit_raw():
    """bpp 5 (BPP_PACKED_2BIT) is 2 bits per pixel, not 5."""
    from oepl.image import decode_image_pil

    tt = make_bwry_tag_type()
    raw = _make_packed_2bit(tt)
    assert len(raw) == 296 * 128 * 2 // 8
    _assert_bwry_bands(decode_image_pil(raw, tt), tt)


def test_decode_packed_2bit_zlib():
    import zlib

    from oepl.image import decode_image_pil

    tt = make_bwry_tag_type()
    bitmap = _make_packed_2bit(tt)
    payload = bytes(6) + bitmap  # 6-byte header the AP puts before the bitmap
    data = len(payload).to_bytes(4, "little") + zlib.compress(payload)
    _assert_bwry_bands(decode_image_pil(data, tt), tt)


def _make_planes(tt: TagType, bands: list[int]) -> bytes:
    """Two bit planes for vertical bands of colour table indices (no rotation)."""
    bytes_per_row = (tt.width + 7) // 8
    first = bytearray(bytes_per_row * tt.height)
    second = bytearray(bytes_per_row * tt.height)
    for y in range(tt.height):
        for x in range(tt.width):
            index = bands[x * len(bands) // tt.width]
            bit = 0x80 >> (x % 8)
            if index & 1:
                first[y * bytes_per_row + x // 8] |= bit
            if index & 2:
                second[y * bytes_per_row + x // 8] |= bit
    return bytes(first + second)


def _band_colours(img, tt: TagType, count: int) -> list[tuple[int, ...]]:
    return [img.getpixel((tt.width * (2 * i + 1) // (2 * count), tt.height // 2)) for i in range(count)]


def test_decode_two_planes_bwry_white_first():
    """M3 BWRY types: both planes set is yellow, not black."""
    from oepl.image import decode_image_pil

    tt = TagType(
        type_id=0x2B,
        width=64,
        height=8,
        bpp=2,
        color_table={
            "white": [255, 255, 255],
            "black": [0, 0, 0],
            "red": [255, 0, 0],
            "yellow": [255, 255, 0],
        },
        perceptual={"yellow": [200, 200, 0]},
    )
    img = decode_image_pil(_make_planes(tt, [0, 1, 2, 3]), tt)
    assert _band_colours(img, tt, 4) == [(255, 255, 255), (0, 0, 0), (255, 0, 0), (200, 200, 0)]


def test_decode_two_planes_black_first():
    """A colour table that starts with black is read by index, like the AP web UI."""
    from oepl.image import decode_image_pil

    tt = TagType(
        type_id=0xC0,
        width=64,
        height=8,
        bpp=2,
        color_table={
            "black": [0, 0, 0],
            "white": [255, 255, 255],
            "yellow": [255, 255, 0],
            "red": [255, 0, 0],
        },
    )
    img = decode_image_pil(_make_planes(tt, [0, 1, 2, 3]), tt)
    assert _band_colours(img, tt, 4) == [(0, 0, 0), (255, 255, 255), (255, 255, 0), (255, 0, 0)]


def test_decode_two_planes_bwr_unchanged():
    """BWR: both planes set still shows black, as before."""
    from oepl.image import decode_image_pil

    tt = make_tag_type(width=64, height=8)
    img = decode_image_pil(_make_planes(tt, [0, 1, 2, 3]), tt)
    assert _band_colours(img, tt, 4) == [(255, 255, 255), (0, 0, 0), (255, 0, 0), (0, 0, 0)]


def test_decode_one_plane_bw():
    from oepl.image import decode_image_pil

    tt = TagType(type_id=0x01, width=64, height=8, bpp=1, color_table={"white": [255, 255, 255], "black": [0, 0, 0]})
    planes = _make_planes(tt, [0, 1])
    img = decode_image_pil(planes[: len(planes) // 2], tt)
    assert _band_colours(img, tt, 2) == [(255, 255, 255), (0, 0, 0)]
