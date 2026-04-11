"""Data models for the oepl library."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .enums import APState, RunStatus


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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Tag":
        """Parse a tag dict as returned by the AP /get_db endpoint."""
        return cls(
            mac=data.get("mac", ""),
            alias=data.get("alias", ""),
            hw_type=data.get("hwType", 0),
            last_seen=data.get("lastseen", 0),
            next_update=data.get("nextupdate", 0),
            next_checkin=data.get("nextcheckin", 0),
            pending=data.get("pending", 0),
            content_mode=data.get("contentMode", 0),
            lqi=data.get("LQI", 0),
            rssi=data.get("RSSI", 0),
            temperature=data.get("temperature", 0),
            battery_mv=data.get("batteryMv", 0),
            wakeup_reason=data.get("wakeupReason", 0),
            capabilities=data.get("capabilities", 0),
            rotate=data.get("rotate", 0),
            lut=data.get("lut", 0),
            update_count=data.get("updatecount", 0),
            is_external=bool(data.get("isexternal", False)),
            ap_ip=data.get("apip", ""),
            channel=data.get("ch", 0),
            firmware_version=data.get("ver", 0),
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
    ps_ram_free: int
    temp: float
    wifi_status: int
    low_battery_count: int
    timeout_count: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "APStatus":
        """Parse a sys-message dict from the AP WebSocket."""
        return cls(
            current_time=data.get("currtime", 0),
            heap=data.get("heap", 0),
            record_count=data.get("recordcount", 0),
            ap_state=APState(data.get("apstate", 0)),
            run_state=RunStatus(data.get("runstate", 0)),
            rssi=data.get("rssi", 0),
            wifi_ssid=data.get("wifissid", ""),
            uptime=data.get("uptime", 0),
            db_size=data.get("dbsize", 0),
            little_fs_free=data.get("littlefsfree", 0),
            ps_ram_free=data.get("psfree", 0),
            temp=float(data.get("temp", 0.0)),
            wifi_status=data.get("wifistatus", 0),
            low_battery_count=data.get("lowbattcount", 0),
            timeout_count=data.get("timeoutcount", 0),
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
    has_ble: bool
    can_rollback: bool

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "APInfo":
        return cls(
            alias=data.get("alias", ""),
            env=data.get("env", ""),
            build_version=data.get("buildversion", ""),
            build_time=data.get("buildtime", ""),
            ap_version=str(data.get("ap_version", "")),
            psram_size=data.get("psramsize", 0),
            flash_size=data.get("flashsize", 0),
            has_c6=bool(data.get("hasC6", False)),
            has_h2=bool(data.get("hasH2", False)),
            has_ble=False,  # not reported by /sysinfo; capability is in /get_ap_config
            can_rollback=bool(data.get("rollback", False)),
        )


@dataclass
class APConfig:
    """Mutable AP configuration (from /get_ap_config, written via /save_apcfg)."""

    alias: str
    channel: int
    led_brightness: int
    tft_brightness: int
    max_sleep: int
    timezone: str
    preview: bool
    nightly_reboot: bool
    ble_enabled: bool
    repo: str
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "APConfig":
        known = {
            "alias", "channel", "led", "tft",
            "maxsleep", "timezone", "preview", "nightlyreboot", "ble", "repo",
        }
        extra = {k: v for k, v in data.items() if k not in known}
        return cls(
            alias=data.get("alias", ""),
            channel=data.get("channel", 11),
            led_brightness=data.get("led", 0),
            tft_brightness=data.get("tft", 0),
            max_sleep=data.get("maxsleep", 60),
            timezone=data.get("timezone", ""),
            preview=bool(data.get("preview", False)),
            nightly_reboot=bool(data.get("nightlyreboot", False)),
            ble_enabled=bool(data.get("ble", False)),
            repo=data.get("repo", ""),
            extra=extra,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize back to the AP's field names for /save_apcfg."""
        d: dict[str, Any] = {
            "alias": self.alias,
            "channel": self.channel,
            "led": self.led_brightness,
            "tft": self.tft_brightness,
            "maxsleep": self.max_sleep,
            "timezone": self.timezone,
            "preview": int(self.preview),
            "nightlyreboot": int(self.nightly_reboot),
            "ble": int(self.ble_enabled),
            "repo": self.repo,
        }
        d.update(self.extra)
        return d


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
    color_table: dict[str, list[int]] = field(default_factory=lambda: {
        "white": [255, 255, 255],
        "black": [0, 0, 0],
    })
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
            width=data.get("width", 296),
            height=data.get("height", 128),
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
