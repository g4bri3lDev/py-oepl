"""Data models for the oepl library."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, ClassVar

from .enums import LUT, APState, ContentMode, Rotation, RunStatus, WakeupReason


def _epoch_to_datetime(epoch: int) -> datetime | None:
    """Convert a Unix epoch to an aware UTC datetime; 0 (unset) -> None."""
    if not epoch:
        return None
    return datetime.fromtimestamp(epoch, tz=timezone.utc)


def _as_int(value: Any, default: int) -> int:
    """Coerce *value* to ``int``, falling back to *default* if that's not possible.

    Tolerant parsing already covers *missing* keys via ``dict.get(key, default)``;
    this extends the same tolerance to *present-but-malformed* values (e.g. a
    firmware payload with ``lastseen: "not-a-number"``), which would otherwise
    parse fine and then raise deep inside a ``*_at`` datetime property. The raw,
    unparsed value is unaffected — it's still preserved verbatim on ``.raw``.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_optional_int(value: Any) -> int | None:
    """Like :func:`_as_int`, but for fields whose typed default is ``None`` (absent/unset)."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _ap_state(value: Any) -> APState:
    """Coerce a raw 'apstate' value to APState, tolerating '' / None / garbage as OFFLINE."""
    try:
        return APState(int(value))
    except (TypeError, ValueError):
        return APState.OFFLINE


@dataclass
class Tag:
    """Represents an e-paper tag connected to the AP."""

    mac: str
    alias: str = ""
    hw_type: int = 0
    last_seen: int = 0
    next_update: int = 0
    next_checkin: int = 0
    pending: int = 0
    content_mode: ContentMode = ContentMode.NOT_CONFIGURED
    lqi: int = 0
    rssi: int = 0
    temperature: int = 0
    battery_mv: int = 0
    wakeup_reason: WakeupReason = WakeupReason.TIMED
    capabilities: int = 0
    rotate: Rotation = Rotation.NONE
    lut: LUT = LUT.DEFAULT
    update_count: int = 0
    is_external: bool = False
    ap_ip: str = ""
    channel: int = 0
    firmware_version: int = 0
    hash: str = ""
    modecfgjson: str = ""
    invert: bool = False
    update_last: int = 0
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    _CAPABILITIES: ClassVar[list[tuple[int, str]]] = [
        (0x0001, "LED"),
        (0x0002, "Compression"),
        (0x0004, "Custom LUTs"),
        (0x0008, "Alt LUT size"),
        (0x0010, "External power"),
        (0x0020, "Wake button"),
        (0x0040, "NFC"),
        (0x0080, "NFC wake"),
        (0x0100, "BLE"),
    ]

    @property
    def capabilities_list(self) -> list[str]:
        """Names of all active capability bits."""
        return [name for bit, name in self._CAPABILITIES if self.capabilities & bit]

    @property
    def last_seen_at(self) -> datetime | None:
        """``last_seen`` as an aware UTC datetime; ``None`` when unset (0)."""
        return _epoch_to_datetime(self.last_seen)

    @property
    def next_update_at(self) -> datetime | None:
        """``next_update`` as an aware UTC datetime; ``None`` when unset (0)."""
        return _epoch_to_datetime(self.next_update)

    @property
    def next_checkin_at(self) -> datetime | None:
        """``next_checkin`` as an aware UTC datetime; ``None`` when unset (0)."""
        return _epoch_to_datetime(self.next_checkin)

    @property
    def update_last_at(self) -> datetime | None:
        """``update_last`` as an aware UTC datetime; ``None`` when unset (0)."""
        return _epoch_to_datetime(self.update_last)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Tag":
        """Parse a tag dict as returned by the AP /get_db endpoint.

        Tolerant of missing keys (typed defaults are used) except ``mac``,
        which is required.
        """
        mac = data.get("mac")
        if not mac:
            raise ValueError("Tag data is missing required 'mac' key")
        return cls(
            mac=mac,
            alias=data.get("alias", ""),
            hw_type=_as_int(data.get("hwType"), 0),
            last_seen=_as_int(data.get("lastseen"), 0),
            next_update=_as_int(data.get("nextupdate"), 0),
            next_checkin=_as_int(data.get("nextcheckin"), 0),
            pending=_as_int(data.get("pending"), 0),
            content_mode=ContentMode(_as_int(data.get("contentMode"), 0)),
            lqi=_as_int(data.get("LQI"), 0),
            rssi=_as_int(data.get("RSSI"), 0),
            temperature=_as_int(data.get("temperature"), 0),
            battery_mv=_as_int(data.get("batteryMv"), 0),
            wakeup_reason=WakeupReason(_as_int(data.get("wakeupReason"), 0)),
            capabilities=_as_int(data.get("capabilities"), 0),
            rotate=Rotation(_as_int(data.get("rotate"), 0)),
            lut=LUT(_as_int(data.get("lut"), 0)),
            update_count=_as_int(data.get("updatecount"), 0),
            is_external=bool(data.get("isexternal", False)),
            ap_ip=data.get("apip", ""),
            channel=_as_int(data.get("ch"), 0),
            firmware_version=_as_int(data.get("ver"), 0),
            hash=data.get("hash", ""),
            modecfgjson=data.get("modecfgjson", ""),
            invert=bool(data.get("invert", False)),
            update_last=_as_int(data.get("updatelast"), 0),
            raw=dict(data),
        )


@dataclass
class APStatus:
    """Snapshot of AP system status as reported by WebSocket 'sys' messages."""

    current_time: int = 0
    heap: int = 0
    record_count: int = 0
    ap_state: APState = APState.OFFLINE
    run_state: RunStatus = RunStatus.STOP
    rssi: int = 0
    wifi_ssid: str = ""
    uptime: int = 0
    db_size: int = 0
    little_fs_free: int = 0
    ps_ram_free: int | None = None  # absent on boards without PSRAM
    wifi_status: int = 0
    # Only sent ~once/minute by the firmware (web.cpp:182-186); absence must not fail parsing.
    low_battery_count: int | None = None
    timeout_count: int | None = None
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "APStatus":
        """Parse a sys-message dict from the AP WebSocket. Tolerant of missing keys."""
        return cls(
            current_time=_as_int(data.get("currtime"), 0),
            heap=_as_int(data.get("heap"), 0),
            record_count=_as_int(data.get("recordcount"), 0),
            ap_state=APState(_as_int(data.get("apstate"), 0)),
            run_state=RunStatus(_as_int(data.get("runstate"), 0)),
            rssi=_as_int(data.get("rssi"), 0),
            wifi_ssid=data.get("wifissid", ""),
            uptime=_as_int(data.get("uptime"), 0),
            db_size=_as_int(data.get("dbsize"), 0),
            little_fs_free=_as_int(data.get("littlefsfree"), 0),
            ps_ram_free=_as_optional_int(data.get("psfree")),  # conditional on BOARD_HAS_PSRAM
            wifi_status=_as_int(data.get("wifistatus"), 0),
            low_battery_count=_as_optional_int(data.get("lowbattcount")),
            timeout_count=_as_optional_int(data.get("timeoutcount")),
            raw=dict(data),
        )


@dataclass
class APInfo:
    """Static info about the AP hardware and firmware (from /sysinfo)."""

    alias: str = ""
    env: str = ""
    build_version: str = ""
    build_time: str = ""
    ap_version: str = ""
    psram_size: int = 0
    flash_size: int = 0
    has_c6: bool = False
    has_h2: bool = False
    can_rollback: bool = False
    sha: str = ""
    has_tslr: bool = False
    has_flasher: bool = False
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "APInfo":
        """Parse a /sysinfo dict. Tolerant of missing keys."""
        return cls(
            alias=data.get("alias", ""),
            env=data.get("env", ""),
            build_version=data.get("buildversion", ""),
            build_time=data.get("buildtime", ""),
            ap_version=str(data.get("ap_version", "")),
            psram_size=_as_int(data.get("psramsize"), 0),
            flash_size=_as_int(data.get("flashsize"), 0),
            has_c6=bool(data.get("hasC6", False)),
            has_h2=bool(data.get("hasH2", False)),
            can_rollback=bool(data.get("rollback", False)),
            sha=data.get("sha", ""),
            has_tslr=bool(data.get("hasTslr", False)),
            has_flasher=bool(data.get("hasFlasher", False)),
            raw=dict(data),
        )


@dataclass
class APConfig:
    """Mutable AP configuration (from /get_ap_config, written via /save_apcfg).

    Capability fields (``has_*``) and other AP-reported state (``ap_state``,
    ``tlsr``, ``save_space``) are read-only flags reported by the AP firmware.
    Config fields are writable via :meth:`to_dict` / ``save_apcfg``.
    """

    # Writable config
    alias: str = ""
    channel: int = 0
    subghz_channel: int = 0
    led_brightness: int = 0
    tft_brightness: int = 0
    language: int = 0
    max_sleep: int = 0
    stop_sleep: int = 0
    timezone: str = ""
    preview: bool = False
    nightly_reboot: bool = False
    lock: bool = False
    wifi_power: int = 0
    sleep_time1: int = 0
    sleep_time2: int = 0
    ble_enabled: bool = False
    repo: str = ""
    env: str = ""
    discovery: bool = False
    show_timestamp: bool = False
    # Read-only hardware capability flags (sent as string "0"/"1" by the AP)
    has_ble: bool = False
    has_c6: bool = False
    has_h2: bool = False
    has_sub_ghz: bool = False
    # Read-only AP-reported state
    ap_state: APState = APState.OFFLINE
    tlsr: bool = False
    save_space: bool = False
    has_flasher: bool = False
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    _WIFI_POWER_LABELS: ClassVar[dict[int, str]] = {
        78: "19.5 dBm",
        76: "19.0 dBm",
        74: "18.5 dBm",
        68: "17.0 dBm",
        60: "15.0 dBm",
        52: "13.0 dBm",
        44: "11.0 dBm",
        34: "8.5 dBm",
        28: "7.0 dBm",
        20: "5.0 dBm",
        8: "2.0 dBm",
    }
    _LED_BRIGHTNESS_LABELS: ClassVar[dict[int, str]] = {
        0: "off",
        15: "10%",
        31: "25%",
        127: "50%",
        191: "75%",
        255: "100%",
    }
    _TFT_BRIGHTNESS_LABELS: ClassVar[dict[int, str]] = {
        0: "off",
        20: "10%",
        64: "25%",
        128: "50%",
        192: "75%",
        255: "100%",
    }
    _MAX_SLEEP_LABELS: ClassVar[dict[int, str]] = {
        0: "shortest (40 sec)",
        5: "5 min",
        10: "10 min",
        30: "30 min",
        60: "1 hour",
    }
    _LANGUAGE_LABELS: ClassVar[dict[int, str]] = {
        0: "English",
        1: "Nederlands",
        2: "Deutsch",
        3: "Norsk",
        4: "Français",
        5: "Čeština",
        6: "Slovenčina",
        7: "Polski",
        8: "Español",
        9: "Svenska",
        10: "Dansk",
        11: "Eesti",
    }

    @property
    def wifi_power_label(self) -> str:
        """Transmit power in dBm."""
        return self._WIFI_POWER_LABELS.get(self.wifi_power, str(self.wifi_power))

    @property
    def led_brightness_label(self) -> str:
        """LED brightness as a human-readable percentage."""
        return self._LED_BRIGHTNESS_LABELS.get(self.led_brightness, str(self.led_brightness))

    @property
    def tft_brightness_label(self) -> str:
        """TFT brightness as a human-readable percentage."""
        return self._TFT_BRIGHTNESS_LABELS.get(self.tft_brightness, str(self.tft_brightness))

    @property
    def max_sleep_label(self) -> str:
        """Maximum tag sleep interval in human-readable form."""
        return self._MAX_SLEEP_LABELS.get(self.max_sleep, f"{self.max_sleep} min")

    @property
    def language_label(self) -> str:
        """Display language name."""
        return self._LANGUAGE_LABELS.get(self.language, str(self.language))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "APConfig":
        """Parse a /get_ap_config dict. Tolerant of missing keys."""

        def _flag(key: str) -> bool:
            """Capability flags are sent as string '0'/'1'; absent = False."""
            return str(data.get(key, "0")) == "1"

        return cls(
            alias=data.get("alias", ""),
            channel=_as_int(data.get("channel"), 0),
            subghz_channel=_as_int(data.get("subghzchannel"), 0),
            led_brightness=_as_int(data.get("led"), 0),
            tft_brightness=_as_int(data.get("tft"), 0),
            language=_as_int(data.get("language"), 0),
            max_sleep=_as_int(data.get("maxsleep"), 0),
            stop_sleep=_as_int(data.get("stopsleep"), 0),
            timezone=data.get("timezone", ""),
            preview=bool(data.get("preview", False)),
            nightly_reboot=bool(data.get("nightlyreboot", False)),
            lock=bool(data.get("lock", False)),
            wifi_power=_as_int(data.get("wifipower"), 0),
            sleep_time1=_as_int(data.get("sleeptime1"), 0),
            sleep_time2=_as_int(data.get("sleeptime2"), 0),
            ble_enabled=bool(data.get("ble", False)),
            repo=data.get("repo", ""),
            env=data.get("env", ""),
            discovery=bool(data.get("discovery", False)),
            show_timestamp=bool(data.get("showtimestamp", False)),
            has_ble=_flag("hasBLE"),
            has_c6=_flag("C6"),
            has_h2=_flag("H2"),
            has_sub_ghz=_flag("hasSubGhz"),
            ap_state=_ap_state(data.get("apstate", 0)),
            tlsr=_flag("TLSR"),
            save_space=_flag("savespace"),
            has_flasher=_flag("hasFlasher"),
            raw=dict(data),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize writable fields back to the AP's field names for /save_apcfg."""
        return {
            "alias": self.alias,
            "channel": self.channel,
            "subghzchannel": self.subghz_channel,
            "led": self.led_brightness,
            "tft": self.tft_brightness,
            "language": self.language,
            "maxsleep": self.max_sleep,
            "stopsleep": self.stop_sleep,
            "timezone": self.timezone,
            "preview": int(self.preview),
            "nightlyreboot": int(self.nightly_reboot),
            "lock": int(self.lock),
            "wifipower": self.wifi_power,
            "sleeptime1": self.sleep_time1,
            "sleeptime2": self.sleep_time2,
            "ble": int(self.ble_enabled),
            "repo": self.repo,
            "env": self.env,
            "discovery": int(self.discovery),
            "showtimestamp": int(self.show_timestamp),
        }


@dataclass
class APListItem:
    """Mesh AP announcement from the 'apitem' WS message."""

    ip: str = ""
    alias: str = ""
    count: int = 0
    channel: int = 0
    version: str = ""  # coerce via str() — firmware may send int or hex string
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "APListItem":
        """Parse an 'apitem' WS message dict. Tolerant of arbitrary/missing keys."""
        return cls(
            ip=data.get("ip", ""),
            alias=data.get("alias", ""),
            count=_as_int(data.get("count"), 0),
            channel=_as_int(data.get("channel"), 0),
            version=str(data.get("version", "")),
            raw=dict(data),
        )


@dataclass
class UploadProgress:
    """Image-transfer progress from the 'upload' WS message."""

    src: str = ""  # tag MAC
    current: int = 0
    total: int = 0
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @property
    def done(self) -> bool:
        """True once the transfer has completed (current >= total and total > 0)."""
        return self.total > 0 and self.current >= self.total

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UploadProgress":
        """Parse an 'upload' WS message dict. Tolerant of missing keys."""
        return cls(
            src=data.get("src", ""),
            current=_as_int(data.get("current"), 0),
            total=_as_int(data.get("total"), 0),
            raw=dict(data),
        )


@dataclass
class TagType:
    """Tag hardware type specification.

    Used for image decoding and for callers that need to store/pass
    full tag hardware specifications. JSON key mappings noted in comments.
    """

    type_id: int
    width: int
    height: int
    version: int = 1
    name: str = ""
    rotatebuffer: int = 0
    bpp: int = 2
    color_table: dict[str, list[int]] = field(
        default_factory=lambda: {
            "white": [255, 255, 255],
            "black": [0, 0, 0],
        }
    )
    short_lut: int = 2
    options: list[Any] = field(default_factory=list)
    content_ids: list[Any] = field(default_factory=list)
    template: dict[str, Any] = field(default_factory=dict)
    use_template: Any = None
    zlib_compression: Any = None
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @classmethod
    def from_dict(cls, type_id: int, data: dict[str, Any]) -> "TagType":
        return cls(
            type_id=type_id,
            version=_as_int(data.get("version"), 1),
            name=data.get("name", f"Unknown Type {type_id}"),
            width=data["width"],
            height=data["height"],
            rotatebuffer=_as_int(data.get("rotatebuffer"), 0),
            bpp=_as_int(data.get("bpp"), 2),
            color_table=data.get("colortable", {"white": [255, 255, 255], "black": [0, 0, 0]}),
            short_lut=_as_int(data.get("shortlut"), 2),
            options=data.get("options", []),
            content_ids=data.get("contentids", []),
            template=data.get("template", {}),
            use_template=data.get("usetemplate"),
            zlib_compression=data.get("zlib_compression"),
            raw=dict(data),
        )


@dataclass
class WifiConfig:
    """Stored WiFi/network settings (from ``/get_wifi_config``, web.cpp:749-762).

    The firmware reads these back out of its ``Preferences`` "wifi" namespace
    and always includes all six keys (empty string when unset), plus the
    AP's own MAC address.
    """

    ssid: str = ""
    password: str = ""
    ip: str = ""
    mask: str = ""
    gateway: str = ""
    dns: str = ""
    mac: str = ""
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WifiConfig":
        """Parse a ``/get_wifi_config`` dict. Tolerant of missing keys."""
        return cls(
            ssid=data.get("ssid", ""),
            password=data.get("pw", ""),
            ip=data.get("ip", ""),
            mask=data.get("mask", ""),
            gateway=data.get("gw", ""),
            dns=data.get("dns", ""),
            mac=data.get("mac", ""),
            raw=dict(data),
        )


@dataclass
class WifiNetwork:
    """A single scanned WiFi network, as reported by ``/get_ssid_list``."""

    ssid: str = ""
    channel: int = 0
    rssi: int = 0
    encryption: int = 0
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WifiNetwork":
        """Parse a single entry of the ``networks`` array. Tolerant of missing keys."""
        return cls(
            ssid=data.get("ssid", ""),
            channel=_as_int(data.get("ch"), 0),
            rssi=_as_int(data.get("rssi"), 0),
            encryption=_as_int(data.get("enc"), 0),
            raw=dict(data),
        )


@dataclass
class SSIDList:
    """Scan results from ``/get_ssid_list`` (web.cpp:764-788).

    ``scan_status`` mirrors ESP32 ``WiFi.scanComplete()`` semantics: ``-1``
    means a scan is currently running, ``-2`` means no scan has been started
    yet, and any value ``>= 0`` is the number of networks found by the last
    completed scan (``networks`` is capped at 50 entries by the firmware
    regardless of that count). The firmware (re)starts a background scan on
    almost every call to this endpoint, so polling it repeatedly is the
    normal way to eventually observe a non-negative ``scan_status``.
    """

    scan_status: int = 0
    networks: list[WifiNetwork] = field(default_factory=list)
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SSIDList":
        """Parse a ``/get_ssid_list`` dict. Tolerant of missing keys."""
        return cls(
            scan_status=_as_int(data.get("scanstatus"), 0),
            networks=[WifiNetwork.from_dict(n) for n in data.get("networks", [])],
            raw=dict(data),
        )
