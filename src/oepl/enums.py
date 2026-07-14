"""Enumerations for the oepl library."""

from __future__ import annotations

from enum import Enum, IntEnum


class APState(IntEnum):
    """AP hardware/radio state codes."""

    OFFLINE = 0
    ONLINE = 1
    FLASHING = 2
    WAIT_RESET = 3
    REQUIRED_POWER_CYCLE = 4
    FAILED = 5
    COMING_ONLINE = 6
    NO_RADIO = 7


class RunStatus(IntEnum):
    """AP tag-update engine run state."""

    STOP = 0
    PAUSE = 1
    RUN = 2
    INIT = 3


class Rotation(IntEnum):
    """Image rotation applied by the AP before sending to the tag."""

    NONE = 0
    R90 = 1
    R180 = 2
    R270 = 3


class LUT(IntEnum):
    """Display refresh LUT (look-up table) mode.

    Values match firmware (``OpenEpaperLink/oepl-definitions.h``).
    """

    DEFAULT = 0  # auto/default
    NO_REPEAT = 1  # always full refresh
    FAST_NO_REDS = 2  # fast (no reds)
    FAST = 3  # fastest (ghosting)
    OTA = 0x10


class TagCommand(str, Enum):
    """Commands that can be sent to a tag via the AP."""

    CLEAR = "clear"
    REFRESH = "refresh"
    REBOOT = "reboot"
    SCAN = "scan"


class WakeupReason(IntEnum):
    """Reason the tag woke up and checked in (from oepl-definitions.h)."""

    TIMED = 0x00
    GPIO = 0x02
    NFC = 0x03
    BUTTON1 = 0x04
    BUTTON2 = 0x05
    RF = 0x0F
    FAILED_OTA = 0xE0
    FIRST_BOOT = 0xFC
    NETWORK_SCAN = 0xFD
    WDT_RESET = 0xFE


class ContentMode(IntEnum):
    """Content mode assigned to a tag (from contentmanager.cpp)."""

    NOT_CONFIGURED = 0
    TODAY = 1
    COUNT_DAYS = 2
    COUNT_HOURS = 3
    WEATHER = 4
    FIRMWARE = 5
    IMAGE_URL = 7
    FORECAST = 8
    RSS_FEED = 9
    QR_CODE = 10
    CALENDAR = 11
    REMOTE_AP = 12
    SEG_STATIC = 13
    NFC_URL = 14
    BUIENRADAR = 16
    TAG_COMMAND = 17
    TAG_CONFIG = 18
    JSON_TEMPLATE = 19
    DISPLAY_COPY = 20
    AP_INFO = 21
    STATIC_IMAGE = 22
    STATIC_IMAGE_ADV = 23
    EXTERNAL_IMAGE = 24
    HOME_ASSISTANT = 25
    TIMESTAMP = 26
    DAY_AHEAD = 27
    TIME_RAW = 29
