"""Data models for the oepl library."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from .enums import APState, ContentMode, RunStatus, WakeupReason


@dataclass
class Tag:
    """Represents an e-paper tag connected to the AP."""

    mac: str
    alias: str
    hw_type: int
    last_seen: int
    next_update: int
    next_checkin: int
    pending: int
    content_mode: int
    lqi: int
    rssi: int
    temperature: int
    battery_mv: int
    wakeup_reason: int
    capabilities: int
    rotate: int
    lut: int
    update_count: int
    is_external: bool
    ap_ip: str
    channel: int
    firmware_version: int

    _LUT_NAMES: ClassVar[dict[int, str]] = {
        0: "Default",
        1: "No repeats",
        2: "Fast (no reds)",
        3: "Fast",
        0x10: "OTA",
    }
    _ROTATE_NAMES: ClassVar[dict[int, str]] = {0: "None", 1: "90°", 2: "180°", 3: "270°"}
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
    def content_mode_label(self) -> str:
        """Human-readable content mode name."""
        try:
            return ContentMode(self.content_mode).name.replace("_", " ").title()
        except ValueError:
            return str(self.content_mode)

    @property
    def wakeup_reason_label(self) -> str:
        """Human-readable wakeup reason name."""
        try:
            return WakeupReason(self.wakeup_reason).name.replace("_", " ").title()
        except ValueError:
            return str(self.wakeup_reason)

    @property
    def lut_label(self) -> str:
        """Human-readable LUT mode name."""
        return self._LUT_NAMES.get(self.lut, str(self.lut))

    @property
    def rotate_label(self) -> str:
        """Human-readable rotation label."""
        return self._ROTATE_NAMES.get(self.rotate, str(self.rotate))

    @property
    def capabilities_list(self) -> list[str]:
        """Names of all active capability bits."""
        return [name for bit, name in self._CAPABILITIES if self.capabilities & bit]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Tag":
        """Parse a tag dict as returned by the AP /get_db endpoint."""
        return cls(
            mac=data["mac"],
            alias=data["alias"],
            hw_type=data["hwType"],
            last_seen=data["lastseen"],
            next_update=data["nextupdate"],
            next_checkin=data["nextcheckin"],
            pending=data["pending"],
            content_mode=data["contentMode"],
            lqi=data["LQI"],
            rssi=data["RSSI"],
            temperature=data["temperature"],
            battery_mv=data["batteryMv"],
            wakeup_reason=data["wakeupReason"],
            capabilities=data["capabilities"],
            rotate=data["rotate"],
            lut=data["lut"],
            update_count=data["updatecount"],
            is_external=bool(data["isexternal"]),
            ap_ip=data["apip"],
            channel=data["ch"],
            firmware_version=data["ver"],
        )


@dataclass
class APStatus:
    """Snapshot of AP system status as reported by WebSocket 'sys' messages."""

    current_time: int
    heap: int
    record_count: int
    ap_state: APState
    run_state: RunStatus
    rssi: int
    wifi_ssid: str
    uptime: int
    db_size: int
    little_fs_free: int
    ps_ram_free: int | None  # absent on boards without PSRAM
    wifi_status: int
    low_battery_count: int
    timeout_count: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "APStatus":
        """Parse a sys-message dict from the AP WebSocket."""
        return cls(
            current_time=data["currtime"],
            heap=data["heap"],
            record_count=data["recordcount"],
            ap_state=APState(data["apstate"]),
            run_state=RunStatus(data["runstate"]),
            rssi=data["rssi"],
            wifi_ssid=data["wifissid"],
            uptime=data["uptime"],
            db_size=data["dbsize"],
            little_fs_free=data["littlefsfree"],
            ps_ram_free=data.get("psfree"),  # conditional on BOARD_HAS_PSRAM
            wifi_status=data["wifistatus"],
            low_battery_count=data["lowbattcount"],
            timeout_count=data["timeoutcount"],
        )


@dataclass
class APInfo:
    """Static info about the AP hardware and firmware (from /sysinfo)."""

    alias: str
    env: str
    build_version: str
    build_time: str
    ap_version: str
    psram_size: int
    flash_size: int
    has_c6: bool
    has_h2: bool
    can_rollback: bool

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "APInfo":
        return cls(
            alias=data["alias"],
            env=data["env"],
            build_version=data["buildversion"],
            build_time=data["buildtime"],
            ap_version=str(data["ap_version"]),
            psram_size=data["psramsize"],
            flash_size=data["flashsize"],
            has_c6=bool(data["hasC6"]),
            has_h2=bool(data["hasH2"]),
            can_rollback=bool(data["rollback"]),
        )


@dataclass
class APConfig:
    """Mutable AP configuration (from /get_ap_config, written via /save_apcfg).

    Capability fields (``has_*``) are read-only flags reported by the AP firmware.
    Config fields are writable via :meth:`to_dict` / ``save_apcfg``.
    """

    # Writable config
    alias: str
    channel: int
    subghz_channel: int
    led_brightness: int
    tft_brightness: int
    language: int
    max_sleep: int
    stop_sleep: int
    timezone: str
    preview: bool
    nightly_reboot: bool
    lock: bool
    wifi_power: int
    sleep_time1: int
    sleep_time2: int
    ble_enabled: bool
    repo: str
    env: str
    discovery: bool
    show_timestamp: bool
    # Read-only hardware capability flags (sent as string "0"/"1" by the AP)
    has_ble: bool
    has_c6: bool
    has_h2: bool
    has_sub_ghz: bool

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
        def _flag(key: str) -> bool:
            """Capability flags are sent as string '0'/'1'; absent = False."""
            return str(data.get(key, "0")) == "1"

        return cls(
            alias=data["alias"],
            channel=data["channel"],
            subghz_channel=data["subghzchannel"],
            led_brightness=data["led"],
            tft_brightness=data["tft"],
            language=data["language"],
            max_sleep=data["maxsleep"],
            stop_sleep=data["stopsleep"],
            timezone=data["timezone"],
            preview=bool(data["preview"]),
            nightly_reboot=bool(data["nightlyreboot"]),
            lock=bool(data["lock"]),
            wifi_power=data["wifipower"],
            sleep_time1=data["sleeptime1"],
            sleep_time2=data["sleeptime2"],
            ble_enabled=bool(data["ble"]),
            repo=data["repo"],
            env=data["env"],
            discovery=bool(data["discovery"]),
            show_timestamp=bool(data["showtimestamp"]),
            has_ble=_flag("hasBLE"),
            has_c6=_flag("C6"),
            has_h2=_flag("H2"),
            has_sub_ghz=_flag("hasSubGhz"),
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

    @classmethod
    def from_dict(cls, type_id: int, data: dict[str, Any]) -> "TagType":
        return cls(
            type_id=type_id,
            version=data.get("version", 1),
            name=data.get("name", f"Unknown Type {type_id}"),
            width=data["width"],
            height=data["height"],
            rotatebuffer=data.get("rotatebuffer", 0),
            bpp=data.get("bpp", 2),
            color_table=data.get("colortable", {"white": [255, 255, 255], "black": [0, 0, 0]}),
            short_lut=data.get("shortlut", 2),
            options=data.get("options", []),
            content_ids=data.get("contentids", []),
            template=data.get("template", {}),
            use_template=data.get("usetemplate"),
            zlib_compression=data.get("zlib_compression"),
        )
