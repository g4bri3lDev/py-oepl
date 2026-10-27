"""oepl — async Python client for the OpenEPaperLink AP."""

__version__ = "0.10.0"  # x-release-please-version
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
    OEPLUpdateError,
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
    ap_display_mac,
    build_hostname,
)
from .tag_handle import TagHandle
from .update import (
    DEFAULT_REPO,
    Release,
    ReleaseFile,
    TagFirmware,
    UpdateProgress,
    Updates,
    UpdateStage,
    format_radio_version,
    normalize_version,
    same_version,
)

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
    "ap_display_mac",
    "build_hostname",
    "WifiNetwork",
    "SSIDList",
    # Files
    "Files",
    "FileEntry",
    # Updates
    "Updates",
    "Release",
    "ReleaseFile",
    "TagFirmware",
    "UpdateProgress",
    "UpdateStage",
    "DEFAULT_REPO",
    "format_radio_version",
    "normalize_version",
    "same_version",
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
    "OEPLUpdateError",
    # Image
    "decode_image",
    "decode_image_pil",
    # Dithering (from epaper-dithering)
    "DitherMode",
    "ColorScheme",
]
