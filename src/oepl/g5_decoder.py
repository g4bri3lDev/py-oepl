"""G5 (Group5) bitstream decoder for OpenEPaperLink displays.

This is a pure codec: it turns a G5-compressed payload into flat 1-bpp
plane bytes. It does NOT assemble PIL images, apply color tables, or handle
rotation — that lives in :mod:`oepl.image`, which drives this decoder for
the G5 path and its own logic for the zlib/raw paths.

Original G5 codec by Larry Bank; JavaScript port for OpenEPaperLink by
Nic Limper. This Python port shares its lineage with the copy carried by
the Home Assistant OpenEPaperLink integration; keep the two behaviourally
in sync when touching the bit-level decode.
"""

from __future__ import annotations

# ============================================================================
# Exceptions
# ============================================================================


class G5DecoderError(Exception):
    """Base exception for G5 decoder errors."""


class G5InvalidParameterError(G5DecoderError):
    """Invalid parameters provided to the decoder."""


class G5UnsupportedFeatureError(G5DecoderError):
    """Unsupported G5 feature encountered (e.g. bad compression mode)."""


class G5DecodeError(G5DecoderError):
    """Error during the G5 decoding process."""


# ============================================================================
# Constants
# ============================================================================

# Internal return codes.
_G5_SUCCESS = 0
_G5_INVALID_PARAMETER = 1
_G5_DECODE_ERROR = 2

# Decoder configuration.
MAX_IMAGE_FLIPS = 640
REGISTER_WIDTH = 32

# Horizontal prefix bits.
HORIZ_SHORT_SHORT = 0
HORIZ_SHORT_LONG = 1
HORIZ_LONG_SHORT = 2
HORIZ_LONG_LONG = 3

# Code table for Group 4 (MMR) decoding, as (code, bit_length) pairs flattened
# into a single list indexed by the next 8 bits of the stream (& 0xFE).
CODE_TABLE = [
    0x90,
    0,
    0x40,
    0,  # trash, uncompressed mode - codes 0 and 1
    3,
    7,  # V(-3) pos = 2
    0x13,
    7,  # V(3)  pos = 3
    2,
    6,
    2,
    6,  # V(-2) pos = 4,5
    0x12,
    6,
    0x12,
    6,  # V(2)  pos = 6,7
    0x30,
    4,
    0x30,
    4,
    0x30,
    4,
    0x30,
    4,  # pass  pos = 8->F
    0x30,
    4,
    0x30,
    4,
    0x30,
    4,
    0x30,
    4,
    0x20,
    3,
    0x20,
    3,
    0x20,
    3,
    0x20,
    3,  # horiz pos = 10->1F
    0x20,
    3,
    0x20,
    3,
    0x20,
    3,
    0x20,
    3,
    0x20,
    3,
    0x20,
    3,
    0x20,
    3,
    0x20,
    3,
    0x20,
    3,
    0x20,
    3,
    0x20,
    3,
    0x20,
    3,
    1,
    3,
    1,
    3,
    1,
    3,
    1,
    3,  # V(-1) pos = 20->2F
    1,
    3,
    1,
    3,
    1,
    3,
    1,
    3,
    1,
    3,
    1,
    3,
    1,
    3,
    1,
    3,
    1,
    3,
    1,
    3,
    1,
    3,
    1,
    3,
    0x11,
    3,
    0x11,
    3,
    0x11,
    3,
    0x11,
    3,  # V(1) pos = 30->3F
    0x11,
    3,
    0x11,
    3,
    0x11,
    3,
    0x11,
    3,
    0x11,
    3,
    0x11,
    3,
    0x11,
    3,
    0x11,
    3,
    0x11,
    3,
    0x11,
    3,
    0x11,
    3,
    0x11,
    3,
]


# ============================================================================
# Utilities
# ============================================================================


def read_motorola_long(data: bytes, offset: int) -> int:
    """Read a 32-bit big-endian integer from ``data`` (TIFFMOTOLONG).

    Tolerates reads that run past the end of ``data`` by treating missing
    bytes as zero, matching the reference implementation.
    """
    value = 0
    for i in range(4):
        if offset + i < len(data):
            value |= data[offset + i] << (24 - i * 8)
    return value


def parse_g5_header(data: bytes) -> tuple[int, int, int, int]:
    """Parse a G5 header, returning ``(header_size, width, height, mode)``.

    Header layout (matching the JavaScript ``drawCanvas.js``):

    - ``data[0]``: header size
    - ``data[1:3]``: width, little-endian (``data[2] << 8 | data[1]``)
    - ``data[3:5]``: height, little-endian (``data[4] << 8 | data[3]``)
    - ``data[5]``: compression mode (0-3)

    Compression-mode-2 height doubling is applied by :func:`decode_g5`, not
    here.
    """
    if len(data) < 6:
        raise G5InvalidParameterError("Data too short for G5 header")

    header_size = data[0]
    width = (data[2] << 8) | data[1]
    height = (data[4] << 8) | data[3]
    compression_mode = data[5]

    if compression_mode > 3:
        raise G5UnsupportedFeatureError(f"Unsupported compression mode: {compression_mode}")

    return header_size, width, height, compression_mode


# ============================================================================
# G5 Decoder
# ============================================================================


class G5Decoder:
    """G5 bitstream decoder with explicit 32-bit register arithmetic.

    All register values are kept as plain Python ints and masked to 32 bits
    where the reference relies on unsigned wrap-around.
    """

    def __init__(self) -> None:
        self.width = 0
        self.height = 0
        self.error = 0
        self.y = 0
        self.vlc_size = 0
        self.h_len = 0
        self.pitch = 0

        # 32-bit register state.
        self.bit_off = 0
        self.bits = 0

        # Source buffer management.
        self.src_data: bytes = b""
        self.buf_index = 0

        # Flip-tracking arrays (changing-element positions per scan line).
        self.cur_flips = [0] * MAX_IMAGE_FLIPS
        self.ref_flips = [0] * MAX_IMAGE_FLIPS

    def init_decoder(self, width: int, height: int, data: bytes) -> int:
        """Initialise the decoder with image parameters and source data."""
        if not data or width < 1 or height < 1 or len(data) < 1:
            return _G5_INVALID_PARAMETER

        self.vlc_size = len(data)
        self.src_data = data
        self.bit_off = 0
        self.y = 0
        self.bits = read_motorola_long(data, 0)
        self.width = width
        self.height = height

        return _G5_SUCCESS

    def decode_begin(self) -> None:
        """Seed internal structures before decoding the first line."""
        xsize = self.width

        # Seed current and reference lines with xsize for V(0) codes.
        for i in range(MAX_IMAGE_FLIPS - 2):
            self.ref_flips[i] = xsize
            self.cur_flips[i] = xsize

        # Prefill the tail with 0x7fff to prevent walking off the end.
        self.cur_flips[MAX_IMAGE_FLIPS - 2] = 0x7FFF
        self.cur_flips[MAX_IMAGE_FLIPS - 1] = 0x7FFF
        self.ref_flips[MAX_IMAGE_FLIPS - 2] = 0x7FFF
        self.ref_flips[MAX_IMAGE_FLIPS - 1] = 0x7FFF

        # Initialise the register from the head of the stream.
        self.buf_index = 0
        self.bits = read_motorola_long(self.src_data, 0)
        self.bit_off = 0

        # Bit length needed to represent width (JS: 32 - Math.clz32(width)).
        if self.width == 0:
            self.h_len = 0
        else:
            self.h_len = self.width.bit_length()

    def decode_line(self) -> int:
        """Decode a single scan line into ``cur_flips``."""
        a0 = -1
        cur_index = 0
        ref_index = 0
        xsize = self.width
        h_len = self.h_len
        h_mask = (1 << h_len) - 1

        # Local copies for the hot loop; wrapped back to state at the end.
        bits = self.bits
        bit_off = self.bit_off
        buf_index = self.buf_index

        while a0 < xsize:
            # Refill register if we have consumed too many bits.
            if bit_off > (REGISTER_WIDTH - 8):
                buf_index += bit_off >> 3
                bit_off &= 7
                if buf_index < len(self.src_data):
                    bits = read_motorola_long(self.src_data, buf_index)

            # Check for V(0) code (top bit after the current offset).
            shifted_bits = (bits << bit_off) & 0xFFFFFFFF
            test_bit = shifted_bits & 0x80000000
            if test_bit != 0:
                # V(0) code.
                a0 = self.ref_flips[ref_index]
                ref_index += 1
                self.cur_flips[cur_index] = a0
                cur_index += 1
                bit_off += 1
            else:
                # Extract code from lookup table.
                l_bits = (bits >> (REGISTER_WIDTH - 8 - bit_off)) & 0xFE
                s_code = CODE_TABLE[l_bits]
                bit_off += CODE_TABLE[l_bits + 1]

                if s_code in [1, 2, 3]:  # V(-1), V(-2), V(-3)
                    a0 = self.ref_flips[ref_index] - s_code
                    self.cur_flips[cur_index] = a0
                    cur_index += 1
                    if ref_index == 0:
                        ref_index += 2
                    ref_index -= 1
                    while a0 >= self.ref_flips[ref_index]:
                        ref_index += 2

                elif s_code in [0x11, 0x12, 0x13]:  # V(1), V(2), V(3)
                    a0 = self.ref_flips[ref_index]
                    ref_index += 1
                    b1 = a0
                    a0 += s_code & 7
                    if b1 != xsize and a0 < xsize:
                        while a0 >= self.ref_flips[ref_index]:
                            ref_index += 2
                    if a0 > xsize:
                        a0 = xsize
                    self.cur_flips[cur_index] = a0
                    cur_index += 1

                elif s_code == 0x20:  # Horizontal codes
                    if bit_off > (REGISTER_WIDTH - 16):
                        buf_index += bit_off >> 3
                        bit_off &= 7
                        if buf_index < len(self.src_data):
                            bits = read_motorola_long(self.src_data, buf_index)

                    a0_p = max(0, a0)
                    l_bits = (bits >> ((REGISTER_WIDTH - 2) - bit_off)) & 0x3
                    bit_off += 2

                    # Handle the four horizontal code types.
                    if l_bits == HORIZ_SHORT_SHORT:
                        tot_run = (bits >> ((REGISTER_WIDTH - 3) - bit_off)) & 0x7
                        bit_off += 3
                        tot_run1 = (bits >> ((REGISTER_WIDTH - 3) - bit_off)) & 0x7
                        bit_off += 3
                    elif l_bits == HORIZ_SHORT_LONG:
                        tot_run = (bits >> ((REGISTER_WIDTH - 3) - bit_off)) & 0x7
                        bit_off += 3
                        tot_run1 = (bits >> ((REGISTER_WIDTH - h_len) - bit_off)) & h_mask
                        bit_off += h_len
                    elif l_bits == HORIZ_LONG_SHORT:
                        tot_run = (bits >> ((REGISTER_WIDTH - h_len) - bit_off)) & h_mask
                        bit_off += h_len
                        tot_run1 = (bits >> ((REGISTER_WIDTH - 3) - bit_off)) & 0x7
                        bit_off += 3
                    else:  # HORIZ_LONG_LONG
                        tot_run = (bits >> ((REGISTER_WIDTH - h_len) - bit_off)) & h_mask
                        bit_off += h_len
                        if bit_off > (REGISTER_WIDTH - 16):
                            buf_index += bit_off >> 3
                            bit_off &= 7
                            if buf_index < len(self.src_data):
                                bits = read_motorola_long(self.src_data, buf_index)
                        tot_run1 = (bits >> ((REGISTER_WIDTH - h_len) - bit_off)) & h_mask
                        bit_off += h_len

                    a0 = a0_p + tot_run
                    self.cur_flips[cur_index] = a0
                    cur_index += 1
                    a0 += tot_run1

                    if a0 < xsize:
                        while a0 >= self.ref_flips[ref_index]:
                            ref_index += 2
                    self.cur_flips[cur_index] = a0
                    cur_index += 1

                elif s_code == 0x30:  # Pass code
                    ref_index += 1
                    a0 = self.ref_flips[ref_index]
                    ref_index += 1

                else:  # ERROR
                    self.error = _G5_DECODE_ERROR
                    return self.error

        # Finalise the line.
        self.cur_flips[cur_index] = xsize
        self.cur_flips[cur_index + 1] = xsize

        # Persist register state.
        self.bits = bits & 0xFFFFFFFF
        self.bit_off = bit_off
        self.buf_index = buf_index

        return self.error

    def draw_line(self, output_buffer: bytearray, line_offset: int) -> None:
        """Rasterise the decoded ``cur_flips`` into a 1-bpp scan line."""
        xright = self.width
        cur_index = 0

        # Line length in bytes.
        line_len = (xright + 7) >> 3

        # Initialise the line to white (0xff).
        for i in range(line_len):
            output_buffer[line_offset + i] = 0xFF

        # Note: x is not incremented in the loop, matching the reference; the
        # loop terminates on the start_x/run break condition below.
        x = 0
        while x < xright:
            start_x = self.cur_flips[cur_index]
            cur_index += 1
            run = self.cur_flips[cur_index] - start_x
            cur_index += 1

            if start_x >= xright or run <= 0:
                break

            # Clip the run to the visible line.
            visible_x = max(0, start_x)
            visible_run = min(xright, start_x + run) - visible_x

            if visible_run > 0:
                start_byte = visible_x >> 3
                end_byte = (visible_x + visible_run) >> 3

                l_bit = (0xFF << (8 - (visible_x & 7))) & 0xFF
                r_bit = 0xFF >> ((visible_x + visible_run) & 7)

                if end_byte == start_byte:
                    # Run fits in a single byte.
                    output_buffer[line_offset + start_byte] &= l_bit | r_bit
                else:
                    # Mask the left-most byte.
                    output_buffer[line_offset + start_byte] &= l_bit

                    # Zero the intermediate bytes.
                    for i in range(start_byte + 1, end_byte):
                        output_buffer[line_offset + i] = 0x00

                    # Mask the right-most byte if not fully aligned.
                    if end_byte < line_len:
                        output_buffer[line_offset + end_byte] &= r_bit


# ============================================================================
# Public interface
# ============================================================================


def decode_g5(data: bytes) -> bytes:
    """Decode a full G5 payload (6-byte header + stream) to plane bytes.

    Returns flat 1-bpp bitmap bytes for the geometry described by the G5
    header. Compression-mode-2 payloads carry a half-height stream that is
    doubled here. The caller is responsible for interpreting the result as
    one or more colour planes and for any rotation.
    """
    if not data:
        raise G5InvalidParameterError("Data must be provided")

    header_size, width, height, compression_mode = parse_g5_header(data)

    # Compression mode 2 stores a half-height stream.
    if compression_mode == 2:
        height *= 2

    payload = data[header_size:]

    decoder = G5Decoder()
    init_result = decoder.init_decoder(width, height, payload)
    if init_result != _G5_SUCCESS:
        raise G5InvalidParameterError("Invalid decoder parameters")

    decoder.decode_begin()

    bytes_per_line = (width + 7) // 8
    output_buffer = bytearray(height * bytes_per_line)

    # A truncated or malformed payload can drive the bitstream loop past the
    # bounds of its flip/output arrays. Translate any such low-level error
    # into a G5DecodeError so callers only ever have to catch G5DecoderError;
    # the decoder must never leak a raw IndexError/ValueError.
    try:
        for y in range(height):
            decoder.y = y
            decode_result = decoder.decode_line()
            if decode_result != _G5_SUCCESS:
                raise G5DecodeError(f"Decoding error on line {y}: {decode_result}")

            decoder.draw_line(output_buffer, y * bytes_per_line)

            # Swap current and reference flip arrays for the next line.
            decoder.cur_flips, decoder.ref_flips = decoder.ref_flips, decoder.cur_flips
    except (IndexError, ValueError) as exc:
        raise G5DecodeError(f"Malformed G5 payload: {exc}") from exc

    return bytes(output_buffer)
