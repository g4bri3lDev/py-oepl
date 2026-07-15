"""Image decoding for OpenEPaperLink raw image format."""

from __future__ import annotations

import io
import logging
import zlib

from PIL import Image

from .g5_decoder import G5DecoderError, decode_g5, parse_g5_header
from .models import TagType

_LOGGER = logging.getLogger(__name__)


def decode_image(raw_data: bytes, tag_type: TagType) -> bytes:
    """Decode raw image bytes from the AP to JPEG.

    Handles G5-compressed, zlib-compressed, and uncompressed formats.

    Args:
        raw_data: Raw image bytes as returned by the AP /get?mac=... endpoint
        tag_type: TagType for the tag that owns this image

    Returns:
        JPEG-encoded image bytes
    """
    return _image_to_jpeg(decode_image_pil(raw_data, tag_type))


def decode_image_pil(raw_data: bytes, tag_type: TagType) -> Image.Image:
    """Decode raw image bytes from the AP to a :class:`PIL.Image.Image`.

    Same decoding pipeline as :func:`decode_image`, but returns the
    intermediate PIL image instead of re-encoding it as JPEG — useful when
    the caller wants to inspect/further process the pixels rather than just
    display the bytes.

    Args:
        raw_data: Raw image bytes as returned by the AP /get?mac=... endpoint
        tag_type: TagType for the tag that owns this image

    Returns:
        Decoded PIL Image (mode "RGB").
    """
    bitmap = _decode_esl_raw(raw_data, tag_type)
    return _bitmap_to_image(bitmap, tag_type)


def _looks_like_g5(data: bytes, tag_type: TagType) -> bool:
    """Return True if ``data`` sniffs as a decodable G5 payload for this tag.

    The zlib/raw payloads share the leading bytes' value space with a G5
    header, so a bare header parse is not enough to tell them apart. We only
    treat data as G5 when it parses, uses a G5 compression mode (1 or 2), and
    the header geometry matches the tag's dimensions in either orientation —
    the same check the decoder used to perform, hoisted here so non-matching
    payloads fall through quietly instead of raising and logging.
    """
    try:
        _header_size, width, height, compression_mode = parse_g5_header(data)
    except G5DecoderError:
        return False

    if compression_mode not in (1, 2):
        return False

    dims = (tag_type.width, tag_type.height)
    return width in dims and height in dims


def _decode_esl_raw(data: bytes, tag_type: TagType) -> bytes:
    """Decompress raw AP image data to a flat bitmap."""
    # Check for G5 compression.
    if len(data) >= 6 and _looks_like_g5(data, tag_type):
        try:
            return decode_g5(data)
        except G5DecoderError as exc:
            _LOGGER.debug("G5 sniff matched but decode failed, falling through: %s", exc)

    # Calculate expected bitmap size
    width = tag_type.height if tag_type.rotatebuffer % 2 else tag_type.width
    height = tag_type.width if tag_type.rotatebuffer % 2 else tag_type.height

    if tag_type.bpp <= 2:
        bytes_per_row = (width + 7) // 8
        bytes_per_plane = bytes_per_row * height
        total_size = bytes_per_plane * (2 if tag_type.bpp == 2 else 1)
    else:
        bytes_per_row = (width * tag_type.bpp + 7) // 8
        total_size = bytes_per_row * height

    header_size = 6

    # Check for zlib-compressed data (4-byte little-endian size header)
    try:
        if len(data) >= 4:
            compressed_size = int.from_bytes(data[:4], byteorder="little")
            if compressed_size > 0:
                compressed_data = data[4:]
                decompressor = zlib.decompressobj(wbits=15)
                decompressed_data = decompressor.decompress(compressed_data)

                # Handle potential second block for BWY/BWR mode
                if tag_type.bpp == 2 and decompressor.unused_data:
                    remaining_data = decompressor.unused_data
                    second_decompressor = zlib.decompressobj(wbits=15)
                    second_block = second_decompressor.decompress(remaining_data)

                    first_plane = decompressed_data[header_size : header_size + total_size // 2]
                    second_plane = second_block[header_size : header_size + total_size // 2]
                    return first_plane + second_plane
                else:
                    return decompressed_data[header_size:]
            else:
                # Uncompressed
                if len(data) < total_size:
                    data = data.ljust(total_size, b"\x00")
                return data
    except Exception as exc:
        _LOGGER.warning("zlib decode failed, treating as raw bitmap: %s", exc)

    # Treat as raw
    if len(data) < total_size:
        data = data.ljust(total_size, b"\x00")
    return data


def _bitmap_to_image(data: bytes, tag_type: TagType) -> Image.Image:
    """Convert a flat bitmap to a PIL Image using the tag's color table."""
    native_width = tag_type.width
    native_height = tag_type.height
    if tag_type.rotatebuffer % 2:
        native_width, native_height = native_height, native_width

    img = Image.new("RGB", (native_width, native_height), "white")
    pixels = img.load()
    assert pixels is not None

    color_table = {k: tuple(v) for k, v in tag_type.color_table.items()}

    if tag_type.bpp <= 2:
        bytes_per_row = (native_width + 7) // 8
        bytes_per_plane = bytes_per_row * native_height

        black_plane = data[:bytes_per_plane]
        color_plane = data[bytes_per_plane : bytes_per_plane * 2] if tag_type.bpp == 2 else None

        for y in range(native_height):
            row_offset = y * bytes_per_row
            for x in range(native_width):
                byte_offset = row_offset + (x // 8)
                bit_mask = 0x80 >> (x % 8)

                black = bool(black_plane[byte_offset] & bit_mask)
                color = bool(color_plane[byte_offset] & bit_mask) if color_plane else False

                if black:
                    pixels[x, y] = color_table["black"]
                elif color:
                    color_key = next((k for k in color_table if k not in ("black", "white")), "white")
                    pixels[x, y] = color_table[color_key]
                else:
                    pixels[x, y] = color_table["white"]
    else:
        bits_per_pixel = tag_type.bpp
        bit_mask = (1 << bits_per_pixel) - 1
        bytes_per_row = (native_width * bits_per_pixel + 7) // 8
        colors_list = list(color_table.values())

        for y in range(native_height):
            for x in range(native_width):
                bit_position = (x * bits_per_pixel) % 8
                byte_offset = (y * bytes_per_row) + (x * bits_per_pixel) // 8

                if byte_offset < len(data):
                    if bit_position + bits_per_pixel <= 8:
                        color_index = (data[byte_offset] >> (8 - bit_position - bits_per_pixel)) & bit_mask
                    else:
                        first_byte = data[byte_offset] & ((1 << (8 - bit_position)) - 1)
                        bits_from_first = 8 - bit_position
                        bits_from_second = bits_per_pixel - bits_from_first
                        if byte_offset + 1 < len(data):
                            second_byte = data[byte_offset + 1] >> (8 - bits_from_second)
                            color_index = (first_byte << bits_from_second) | second_byte
                        else:
                            color_index = first_byte << bits_from_second

                    if color_index < len(colors_list):
                        pixels[x, y] = colors_list[color_index]

    if tag_type.rotatebuffer == 1:
        img = img.transpose(Image.Transpose.ROTATE_270)
    elif tag_type.rotatebuffer == 2:
        img = img.transpose(Image.Transpose.ROTATE_180)
    elif tag_type.rotatebuffer == 3:
        img = img.transpose(Image.Transpose.ROTATE_90)

    return img


def _image_to_jpeg(img: Image.Image) -> bytes:
    """Encode a PIL Image as JPEG bytes (quality=95, matching prior behavior)."""
    output = io.BytesIO()
    img.save(output, format="JPEG", quality=95)
    output.seek(0)
    return output.read()
