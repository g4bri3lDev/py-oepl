"""Byte-exact golden tests for the image decode pipeline.

These fixtures were captured from a real AP (firmware 2.91): raw payload +
tagtype.json + the PNG the AP's own web UI rendered for that payload. They
cover G5 modes 0/1/2, zlib and raw payloads, 1bpp and 2bpp, rotatebuffer
1/2/3, and sizes up to 960x672.

This test MUST pass against the code as it stands before any refactor, and
MUST keep passing — unchanged — after every subsequent commit. No output
pixel may change; that is the whole point of having it.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from oepl.image import decode_image_pil
from oepl.models import TagType

GOLDEN_DIR = Path(__file__).parent / "golden_images"


def _load_manifest() -> list[dict[str, Any]]:
    with (GOLDEN_DIR / "manifest.json").open() as f:
        return list(json.load(f))


def _case_id(entry: dict[str, Any]) -> str:
    return f"{entry['mac']}_hw{entry['hw_type']:02X}"


MANIFEST = _load_manifest()


@pytest.mark.parametrize("entry", MANIFEST, ids=_case_id)
def test_golden_image_decodes_pixel_exact(entry: dict[str, Any]) -> None:
    """decode_image_pil output matches the golden PNG byte-for-byte."""
    stem = _case_id(entry)
    raw_path = GOLDEN_DIR / f"{stem}.raw"
    tagtype_path = GOLDEN_DIR / f"{stem}.tagtype.json"
    png_path = GOLDEN_DIR / f"{stem}.png"

    raw_data = raw_path.read_bytes()
    with tagtype_path.open() as f:
        tagtype_json = json.load(f)

    tag_type = TagType.from_dict(entry["hw_type"], tagtype_json)

    decoded = decode_image_pil(raw_data, tag_type)
    golden = Image.open(png_path)

    expected_width, expected_height = entry["size"]
    assert decoded.size == (expected_width, expected_height)
    assert golden.size == (expected_width, expected_height)

    assert decoded.tobytes() == golden.convert(decoded.mode).tobytes()
