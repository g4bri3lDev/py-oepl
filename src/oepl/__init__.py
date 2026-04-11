"""oepl — async Python client for the OpenDisplay AP."""
__version__ = "0.1.0"
from .client import OEPLClient
from .models import Tag, APConfig, APInfo, APStatus, TagType
from .enums import APState, RunStatus, Rotation, LUT, TagCommand
from .led import Color, LEDSegment, LEDPattern
from .exceptions import (
    OEPLError,
    OEPLConnectionError,
    OEPLTimeoutError,
    OEPLNotFoundError,
    OEPLResponseError,
)
from .image import decode_image

# Re-export epaper-dithering types so callers don't need a separate import
try:
    from epaper_dithering import DitherMode, ColorScheme
except ImportError:
    DitherMode = None  # type: ignore[assignment,misc]
    ColorScheme = None  # type: ignore[assignment,misc]

__all__ = [
    # Client
    "OEPLClient",
    # Models
    "Tag",
    "APConfig",
    "APInfo",
    "APStatus",
    "TagType",
    # Enums
    "APState",
    "RunStatus",
    "Rotation",
    "LUT",
    "TagCommand",
    # LED
    "Color",
    "LEDSegment",
    "LEDPattern",
    # Exceptions
    "OEPLError",
    "OEPLConnectionError",
    "OEPLTimeoutError",
    "OEPLNotFoundError",
    "OEPLResponseError",
    # Image
    "decode_image",
    # Dithering (from epaper-dithering)
    "DitherMode",
    "ColorScheme",
]
