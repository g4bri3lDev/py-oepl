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
    """Display refresh LUT (look-up table) mode."""
    NO_REPEAT = 0
    DEFAULT = 1
    FAST_NO_REDS = 2
    FAST = 3


class TagCommand(str, Enum):
    """Commands that can be sent to a tag via the AP."""
    CLEAR = "clear"
    REFRESH = "refresh"
    REBOOT = "reboot"
    SCAN = "scan"
