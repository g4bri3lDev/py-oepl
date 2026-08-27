"""oepl — async Python client for the OpenEPaperLink AP."""

__version__ = "0.4.0"  # x-release-please-version
from .client import OEPLClient
from .enums import (
    LUT,
    APState,
    ContentMode,
    Rotation,
    RunStatus,
    TagCapability,
    TagCommand,
    WakeupReason,
)
from .exceptions import (
    OEPLConnectionError,
    OEPLError,
    OEPLNotFoundError,
    OEPLResponseError,
    OEPLTimeoutError,
)
from .files import FileEntry, Files
from .image import decode_image, decode_image_pil
from .led import Color, LEDPattern, LEDSegment
from .models import (
    APConfig,
    APInfo,
    APListItem,
    APStatus,
    SSIDList,
    Tag,
    TagType,
    UploadProgress,
    WifiConfig,
    WifiNetwork,
    build_hostname,
)
from .tag_handle import TagHandle

# Re-export epaper-dithering types so callers don't need a separate import
try:
    from epaper_dithering import ColorScheme, DitherMode
except ImportError:
    DitherMode = None  # type: ignore[assignment,misc]
    ColorScheme = None  # type: ignore[assignment,misc]

__all__ = [
    # Client
    "OEPLClient",
    "TagHandle",
    # Models
    "Tag",
    "APConfig",
    "APInfo",
    "APStatus",
    "TagType",
    "APListItem",
    "UploadProgress",
    "WifiConfig",
    "build_hostname",
    "WifiNetwork",
    "SSIDList",
    # Files
    "Files",
    "FileEntry",
    # Enums
    "APState",
    "RunStatus",
    "Rotation",
    "LUT",
    "TagCapability",
    "TagCommand",
    "WakeupReason",
    "ContentMode",
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
    "decode_image_pil",
    # Dithering (from epaper-dithering)
    "DitherMode",
    "ColorScheme",
]
