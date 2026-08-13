"""Enumerations for the oepl library."""

from __future__ import annotations

from enum import Enum, IntEnum, IntFlag


class OEPLIntEnum(IntEnum):
    """IntEnum that synthesizes UNKNOWN_0xNN pseudo-members for unrecognized values.

    Firmware evolves faster than this library: new wire-protocol values must
    never raise ``ValueError`` during parsing. Unrecognized ints are turned
    into cached pseudo-members (``UNKNOWN_0x63`` for ``99``) that still behave
    like real ``IntEnum`` members for comparison, ``int()``, and identity.
    """

    @classmethod
    def _missing_(cls, value: object) -> "OEPLIntEnum | None":
        if not isinstance(value, int):
            return None
        member = int.__new__(cls, value)
        member._name_ = f"UNKNOWN_0x{value:02X}"
        member._value_ = value
        # cache so identity/equality behave like real members
        cls._value2member_map_[value] = member
        return member


class APState(OEPLIntEnum):
    """AP hardware/radio state codes."""

    OFFLINE = 0
    ONLINE = 1
    FLASHING = 2
    WAIT_RESET = 3
    REQUIRED_POWER_CYCLE = 4
    FAILED = 5
    COMING_ONLINE = 6
    NO_RADIO = 7


class RunStatus(OEPLIntEnum):
    """AP tag-update engine run state."""

    STOP = 0
    PAUSE = 1
    RUN = 2
    INIT = 3


class Rotation(OEPLIntEnum):
    """Image rotation applied by the AP before sending to the tag."""

    NONE = 0
    R90 = 1
    R180 = 2
    R270 = 3

    @property
    def degrees(self) -> int:
        """Clockwise rotation in degrees.

        The wire value is a quarter-turn count, which ``makeimage.cpp``
        applies as a pixel transform per case.
        """
        return int(self) * 90


class LUT(OEPLIntEnum):
    """Display refresh LUT (look-up table) mode.

    Member names mirror the firmware's ``EPD_LUT_*`` constants
    (``OpenEpaperLink/oepl-definitions.h``), but **these values are stored on
    the tag config and the AP reinterprets them** — so the names read
    backwards from what they do. What the AP actually does with the stored
    value (``contentmanager.cpp``, ``imageParams.lut`` selection):

    ==========  =================================================================
    Value       Behaviour
    ==========  =================================================================
    ``DEFAULT`` Adaptive. Cheap no-repeat refreshes, automatically promoted to
                one full refresh per night to clear ghosting. **Best battery
                life — this is the sensible default.**
    ``NO_REPEAT`` Full refresh waveform on *every* update. Highest quality,
                heaviest battery cost. Despite the name, this is the "always
                full refresh" option (the AP web UI labels it exactly that).
    ``FAST_NO_REDS`` Fast waveform, skipping red passes.
    ``FAST``    Fastest waveform; may ghost.
    ==========  =================================================================

    Note a tag type whose ``shortlut`` is disabled always gets the full
    waveform, making this setting a no-op for that hardware.
    """

    DEFAULT = 0  # adaptive: no-repeat, promoted to full once nightly
    NO_REPEAT = 1  # always full refresh (despite the name)
    FAST_NO_REDS = 2  # fast (no reds)
    FAST = 3  # fastest (ghosting)
    OTA = 0x10


class TagCapability(IntFlag):
    """Hardware capability bits a tag reports in ``Tag.capabilities``.

    Values match the firmware's ``CAPABILITY_*`` constants
    (``OpenEpaperLink/oepl-definitions.h``).

    **These are detected at runtime, not declared.** The tag probes its own
    hardware at boot and updates the flags — the wiki describes this for NFC
    wake, where it "takes some measurements on the FD line". Anything not
    electrically detectable therefore never appears here:

    ``WAKE_BUTTON`` in particular is **not populated by tag firmware** in
    practice. Across a fleet of real tags it was set on none, including tags
    whose hardware definitely has buttons. Use :attr:`TagType.has_button`
    instead, which comes from the static per-hardware tag type definition.

    The two sources are complementary rather than redundant: buttons are only
    described by the tag type, NFC only by these flags, and LED by both.
    """

    LED = 0x0001
    COMPRESSION = 0x0002
    CUSTOM_LUTS = 0x0004
    ALT_LUT_SIZE = 0x0008
    EXT_POWER = 0x0010
    WAKE_BUTTON = 0x0020
    NFC = 0x0040
    NFC_WAKE = 0x0080
    BLE = 0x0100


class TagCommand(str, Enum):
    """Commands that can be sent to a tag via the AP."""

    DEL = "del"
    """Remove the tag record from the AP's database."""
    PURGE = "purge"
    """Bulk-delete stale tags from the AP's database — NOT scoped to one tag.

    Despite being sent with a ``mac`` (the handler requires one naming a
    currently registered tag just to reach the command branch), the firmware
    ignores that MAC for the actual purge: it sweeps the *entire* tag
    database and deletes every tag that never checked in, hasn't been seen
    for 24 hours, or is more than 10 minutes overdue for its expected
    checkin (``web.cpp`` ``tag_cmd`` handler, ``purge`` branch). Prefer
    :meth:`oepl.OEPLClient.purge_stale_tags` over sending this directly.
    """
    CLEAR = "clear"
    REFRESH = "refresh"
    REBOOT = "reboot"
    SCAN = "scan"
    RESET = "reset"
    DEEPSLEEP = "deepsleep"
    """Put the tag into deep sleep until woken by button press or NFC."""
    LEDFLASH = "ledflash"
    """Trigger a hardcoded firmware LED flash pattern (short, tri-color)."""
    LEDFLASH_LONG = "ledflash_long"
    """Trigger a hardcoded firmware LED flash pattern (long, red)."""
    LEDFLASH_STOP = "ledflash_stop"
    """Stop any currently running LED flash pattern."""


class WakeupReason(OEPLIntEnum):
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


class ContentMode(OEPLIntEnum):
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


def enum_label(member: IntEnum) -> str:
    """Human-readable label: FAST_NO_REDS -> 'Fast No Reds', UNKNOWN_0x63 -> 'Unknown 0x63'."""
    name = member.name
    if name.startswith("UNKNOWN_0x"):
        return f"Unknown 0x{int(member):02X}"
    return name.replace("_", " ").title()
