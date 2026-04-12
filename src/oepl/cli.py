"""Command-line interface for oepl."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import NoReturn

from rich.console import Console
from rich.logging import RichHandler
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.tree import Tree

from . import __version__
from .client import OEPLClient
from .enums import LUT, Rotation, TagCommand, WakeupReason, ContentMode
from .exceptions import OEPLConnectionError, OEPLError, OEPLTimeoutError
from .image import decode_image
from .led import Color, LEDPattern, LEDSegment
from .models import Tag

_console = Console(stderr=True)   # interactive UI → stderr
_stdout = Console()               # --json output  → stdout

_LUT_CHOICES = {m.name.lower(): m for m in LUT}
_ROTATE_CHOICES = {"0": Rotation.NONE, "90": Rotation.R90, "180": Rotation.R180, "270": Rotation.R270}
_CMD_CHOICES = {c.value: c for c in TagCommand}


def _run(coro) -> None:  # type: ignore[type-arg]
    asyncio.run(coro)


def _error(msg: str) -> NoReturn:
    _console.print(f"[bold red]Error:[/bold red] {msg}")
    sys.exit(1)


def _spinner() -> Progress:
    return Progress(SpinnerColumn(), TextColumn("{task.description}"), transient=True, console=_console)


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[RichHandler(console=_console, rich_tracebacks=True)],
        force=True,
    )


def _host(args: argparse.Namespace) -> str:
    host = args.host or os.environ.get("OEPL_HOST")
    if not host:
        _error("AP host required. Pass --host or set OEPL_HOST.")
    return host


def _ts(epoch: int) -> str:
    if not epoch:
        return "—"
    try:
        return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(epoch)


def _add_host(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--host",
        metavar="IP",
        default=None,
        help="AP hostname or IP (or set OEPL_HOST env var)",
    )


# ── tags ──────────────────────────────────────────────────────────────────────


def _add_tags_parser(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    p = sub.add_parser("tags", help="List all tags registered on the AP")
    _add_host(p)
    p.add_argument("--watch", action="store_true", help="Stream live tag updates via WebSocket")
    p.add_argument("--json", dest="output_json", action="store_true", help="Output as JSON")
    p.set_defaults(func=_cmd_tags)


def _cmd_tags(args: argparse.Namespace) -> None:
    _run(_tags(_host(args), args.watch, args.output_json))


def _tag_row(tag: Tag) -> list[str]:
    alias = tag.alias or "—"
    batt = f"{tag.battery_mv} mV" if tag.battery_mv else "—"
    rssi = f"{tag.rssi} dBm" if tag.rssi else "—"
    return [tag.mac.lower(), alias, f"0x{tag.hw_type:02x}", batt, rssi, _ts(tag.last_seen)]


async def _tags(host: str, watch: bool, output_json: bool) -> None:
    async with OEPLClient(host) as client:
        with _spinner() as p:
            p.add_task("Fetching tags...", total=None)
            tags = await client.get_tags()

    if not watch:
        if output_json:
            rows = [
                {
                    "mac": t.mac,
                    "alias": t.alias,
                    "hw_type": t.hw_type,
                    "battery_mv": t.battery_mv,
                    "rssi": t.rssi,
                    "last_seen": t.last_seen,
                    "next_checkin": t.next_checkin,
                    "update_count": t.update_count,
                }
                for t in sorted(tags, key=lambda t: t.alias or t.mac)
            ]
            _stdout.print_json(json.dumps({"tags": rows}))
            return

        table = Table(show_header=True, header_style="bold")
        for col in ("MAC", "Alias", "HW Type", "Battery", "RSSI", "Last Seen"):
            table.add_column(col)
        for tag in sorted(tags, key=lambda t: t.alias or t.mac):
            table.add_row(*_tag_row(tag))
        _console.print(table)
        return

    # --watch: stay connected, print a row for each incoming update
    _console.print("[dim]Watching for tag updates (Ctrl-C to stop)…[/dim]")

    def on_update(tag: Tag) -> None:
        _console.print("  ".join(_tag_row(tag)))

    async with OEPLClient(host) as client:
        client.on_tag_update(on_update)
        client.on_connection_change(
            lambda c: _console.print(
                f"[green]Connected[/green]" if c else "[yellow]Reconnecting…[/yellow]"
            )
        )
        try:
            await asyncio.Event().wait()  # run forever
        except asyncio.CancelledError:
            pass


# ── ap ────────────────────────────────────────────────────────────────────────


def _add_ap_parser(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    p = sub.add_parser("ap", help="Show AP system info and configuration")
    _add_host(p)
    p.add_argument("--json", dest="output_json", action="store_true", help="Output as JSON")
    p.set_defaults(func=_cmd_ap)


def _cmd_ap(args: argparse.Namespace) -> None:
    _run(_ap(_host(args), args.output_json))


async def _ap(host: str, output_json: bool) -> None:
    try:
        with _spinner() as p:
            p.add_task("Connecting…", total=None)
            async with OEPLClient(host) as client:
                info = await client.get_sysinfo()
                cfg = await client.get_ap_config()
    except OEPLConnectionError as exc:
        _error(f"Cannot connect to AP: {exc}")
    except OEPLTimeoutError:
        _error("Connection timed out")

    if output_json:
        _stdout.print_json(
            json.dumps(
                {
                    "info": {
                        "env": cfg.env or info.env,
                        "build_version": info.build_version,
                        "ap_version": info.ap_version,
                        "psram_size": info.psram_size,
                        "flash_size": info.flash_size,
                        "can_rollback": info.can_rollback,
                        "has_c6": cfg.has_c6,
                        "has_h2": cfg.has_h2,
                        "has_ble": cfg.has_ble,
                        "has_sub_ghz": cfg.has_sub_ghz,
                    },
                    "config": {
                        "alias": cfg.alias,
                        "channel": cfg.channel,
                        "subghz_channel": cfg.subghz_channel,
                        "led_brightness": cfg.led_brightness,
                        "tft_brightness": cfg.tft_brightness,
                        "language": cfg.language,
                        "max_sleep": cfg.max_sleep,
                        "stop_sleep": cfg.stop_sleep,
                        "timezone": cfg.timezone,
                        "preview": cfg.preview,
                        "nightly_reboot": cfg.nightly_reboot,
                        "lock": cfg.lock,
                        "wifi_power": cfg.wifi_power,
                        "sleep_time1": cfg.sleep_time1,
                        "sleep_time2": cfg.sleep_time2,
                        "ble_enabled": cfg.ble_enabled,
                        "repo": cfg.repo,
                        "discovery": cfg.discovery,
                        "show_timestamp": cfg.show_timestamp,
                    },
                }
            )
        )
        return

    _WIFI_POWER: dict[int, str] = {
        78: "19.5 dBm", 76: "19.0 dBm", 74: "18.5 dBm", 68: "17.0 dBm",
        60: "15.0 dBm", 52: "13.0 dBm", 44: "11.0 dBm", 34: "8.5 dBm",
        28: "7.0 dBm", 20: "5.0 dBm", 8: "2.0 dBm",
    }
    _LED_BRIGHT: dict[int, str] = {0: "off", 15: "10%", 31: "25%", 127: "50%", 191: "75%", 255: "100%"}
    _TFT_BRIGHT: dict[int, str] = {0: "off", 20: "10%", 64: "25%", 128: "50%", 192: "75%", 255: "100%"}
    _MAX_SLEEP: dict[int, str] = {0: "shortest (40 sec)", 5: "5 min", 10: "10 min", 30: "30 min", 60: "1 hour"}
    _LANGUAGE: dict[int, str] = {
        0: "English", 1: "Nederlands", 2: "Deutsch", 3: "Norsk", 4: "Français",
        5: "Čeština", 6: "Slovenčina", 7: "Polski", 8: "Español",
        9: "Svenska", 10: "Dansk", 11: "Eesti",
    }

    tree = Tree(f"AP  [bold]{host}[/bold]", guide_style="cyan dim")

    hw = tree.add("[bold]Hardware[/bold]")
    hw.add(f"Env         {cfg.env or info.env or '—'}")
    hw.add(f"Version     {info.build_version or info.ap_version or '—'}")
    hw.add(f"PSRAM       {info.psram_size // 1024 // 1024} MB" if info.psram_size else "PSRAM       —")
    hw.add(f"Flash       {info.flash_size // 1024 // 1024} MB" if info.flash_size else "Flash       —")
    hw.add(f"Rollback    {'[green]yes[/green]' if info.can_rollback else '[dim]no[/dim]'}")
    caps = [name for flag, name in [(cfg.has_c6, "C6"), (cfg.has_h2, "H2"), (cfg.has_ble, "BLE"), (cfg.has_sub_ghz, "SubGHz")] if flag]
    if caps:
        hw.add(f"Features    {', '.join(caps)}")

    net = tree.add("[bold]Network[/bold]")
    net.add(f"Channel     {cfg.channel}" + (f" / SubGHz {cfg.subghz_channel}" if cfg.has_sub_ghz else ""))
    net.add(f"WiFi power  {_WIFI_POWER.get(cfg.wifi_power, str(cfg.wifi_power))}")
    if cfg.ble_enabled:
        net.add("BLE         [green]enabled[/green]")

    disp = tree.add("[bold]Display[/bold]")
    disp.add(f"Alias       {cfg.alias or '—'}")
    disp.add(f"RGB LED     {_LED_BRIGHT.get(cfg.led_brightness, str(cfg.led_brightness))}")
    disp.add(f"TFT         {_TFT_BRIGHT.get(cfg.tft_brightness, str(cfg.tft_brightness))}")
    disp.add(f"Language    {_LANGUAGE.get(cfg.language, str(cfg.language))}")
    disp.add(f"Preview     {'[green]on[/green]' if cfg.preview else '[dim]off[/dim]'}")
    disp.add(f"Timestamp   {'[green]on[/green]' if cfg.show_timestamp else '[dim]off[/dim]'}")

    sched = tree.add("[bold]Schedule[/bold]")
    sched.add(f"Max sleep           {_MAX_SLEEP.get(cfg.max_sleep, f'{cfg.max_sleep} min')}")
    sched.add(f"Shorten during cfg  {'[green]yes[/green]' if cfg.stop_sleep else '[dim]no[/dim]'}")
    if cfg.sleep_time1 or cfg.sleep_time2:
        sched.add(f"No updates          {cfg.sleep_time1:02d}:00–{cfg.sleep_time2:02d}:00")
    sched.add(f"Nightly reboot      {'[green]yes[/green]' if cfg.nightly_reboot else '[dim]no[/dim]'}")

    adv = tree.add("[bold]Advanced[/bold]")
    adv.add(f"Timezone    {cfg.timezone or '—'}")
    adv.add(f"Repo        {cfg.repo or '—'}")
    adv.add(f"Discovery   {'[green]on[/green]' if cfg.discovery else '[dim]off[/dim]'}")
    if cfg.lock:
        adv.add("[yellow]Locked[/yellow]")

    _console.print(tree)


# ── upload ────────────────────────────────────────────────────────────────────


def _add_upload_parser(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    p = sub.add_parser("upload", help="Upload an image to a tag")
    _add_host(p)
    p.add_argument("mac", metavar="MAC", help="Tag MAC address")
    p.add_argument("image", metavar="IMAGE", help="Path to image file")
    p.add_argument(
        "--lut",
        choices=list(_LUT_CHOICES),
        default="default",
        help="Display refresh LUT mode (default: default)",
    )
    p.add_argument(
        "--rotate",
        choices=list(_ROTATE_CHOICES),
        default="0",
        help="Image rotation in degrees (default: 0)",
    )
    p.add_argument(
        "--ttl",
        type=int,
        default=0,
        metavar="SECS",
        help="Tag sleep interval override in seconds (0 = tag default)",
    )
    p.set_defaults(func=_cmd_upload)


def _cmd_upload(args: argparse.Namespace) -> None:
    _run(_upload(_host(args), args.mac, args.image, _LUT_CHOICES[args.lut], _ROTATE_CHOICES[args.rotate], args.ttl))


async def _upload(host: str, mac: str, image_path: str, lut: LUT, rotate: Rotation, ttl: int) -> None:
    try:
        from PIL import Image, UnidentifiedImageError
        try:
            image = Image.open(image_path)
        except FileNotFoundError:
            _error(f"Image file not found: {image_path}")
        except UnidentifiedImageError:
            _error(f"Cannot open image: {image_path}")
    except ImportError:
        _error("Pillow is required for image upload.")

    try:
        with _spinner() as p:
            p.add_task(f"Uploading to {mac}…", total=None)
            async with OEPLClient(host) as client:
                await client.upload_image(mac, image, lut=lut, rotate=rotate, ttl=ttl)
    except OEPLError as exc:
        _error(str(exc))

    _console.print(f"[green]✓[/green] Uploaded to [bold]{mac}[/bold]")


# ── cmd ───────────────────────────────────────────────────────────────────────


def _add_cmd_parser(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    p = sub.add_parser("cmd", help="Send a command to a tag")
    _add_host(p)
    p.add_argument("mac", metavar="MAC", help="Tag MAC address")
    p.add_argument("command", choices=list(_CMD_CHOICES), help="Command to send")
    p.set_defaults(func=_cmd_cmd)


def _cmd_cmd(args: argparse.Namespace) -> None:
    _run(_send_cmd(_host(args), args.mac, _CMD_CHOICES[args.command]))


async def _send_cmd(host: str, mac: str, cmd: TagCommand) -> None:
    try:
        with _spinner() as p:
            p.add_task(f"Sending {cmd.value} to {mac}…", total=None)
            async with OEPLClient(host) as client:
                await client.send_tag_cmd(mac, cmd)
    except OEPLError as exc:
        _error(str(exc))
    _console.print(f"[green]✓[/green] Sent [bold]{cmd.value}[/bold] to [bold]{mac}[/bold]")


# ── led ───────────────────────────────────────────────────────────────────────


def _add_led_parser(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    p = sub.add_parser("led", help="Flash an LED pattern on a tag")
    _add_host(p)
    p.add_argument("mac", metavar="MAC", help="Tag MAC address")
    p.add_argument(
        "--color",
        nargs=3,
        type=int,
        metavar=("R", "G", "B"),
        default=[255, 0, 0],
        help="RGB color 0-255 (default: 255 0 0)",
    )
    p.add_argument("--flash-speed", type=float, default=0.2, metavar="SECS", help="Flash speed in seconds (default: 0.2)")
    p.add_argument("--flash-count", type=int, default=2, metavar="N", help="Flashes per cycle (default: 2)")
    p.add_argument("--brightness", type=int, default=2, metavar="1-16", help="LED brightness 1-16 (default: 2)")
    p.add_argument("--repeats", type=int, default=2, metavar="N", help="Pattern repeat count (default: 2)")
    p.set_defaults(func=_cmd_led)


def _cmd_led(args: argparse.Namespace) -> None:
    r, g, b = args.color
    pattern = LEDPattern(
        segments=[LEDSegment(Color(r, g, b), flash_speed=args.flash_speed, flash_count=args.flash_count)],
        brightness=max(1, min(16, args.brightness)),
        repeats=args.repeats,
    )
    _run(_led(_host(args), args.mac, pattern))


async def _led(host: str, mac: str, pattern: LEDPattern) -> None:
    try:
        with _spinner() as p:
            p.add_task(f"Flashing LED on {mac}…", total=None)
            async with OEPLClient(host) as client:
                await client.set_led(mac, pattern)
    except OEPLError as exc:
        _error(str(exc))
    _console.print(f"[green]✓[/green] LED pattern sent to [bold]{mac}[/bold]")


# ── get-image ─────────────────────────────────────────────────────────────────


def _add_get_image_parser(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    p = sub.add_parser("get-image", help="Download and decode the current image from a tag")
    _add_host(p)
    p.add_argument("mac", metavar="MAC", help="Tag MAC address")
    p.add_argument(
        "-o", "--output",
        metavar="FILE",
        default=None,
        help="Output path (default: <mac>.jpg)",
    )
    p.set_defaults(func=_cmd_get_image)


def _cmd_get_image(args: argparse.Namespace) -> None:
    _run(_get_image(_host(args), args.mac, args.output))


async def _get_image(host: str, mac: str, output: str | None) -> None:
    try:
        with _spinner() as p:
            p.add_task(f"Fetching image for {mac}…", total=None)
            async with OEPLClient(host) as client:
                raw = await client.get_image_raw(mac)
                if raw is None:
                    _error(f"No image stored for {mac}")

                tag_type = None
                tags = await client.get_tags()
                tag = next((t for t in tags if t.mac.upper() == mac.upper()), None)
                if tag:
                    tag_type = await client.get_tag_type(tag.hw_type)

    except OEPLError as exc:
        _error(str(exc))

    if tag_type is None:
        _console.print("[yellow]Warning:[/yellow] No tag type definition found; saving raw bytes.")
        out = output or f"{mac.lower()}.raw"
        with open(out, "wb") as f:
            f.write(raw)
        _console.print(f"[green]✓[/green] Raw image saved to [bold]{out}[/bold] ({len(raw)} bytes)")
        return

    try:
        jpeg = decode_image(raw, tag_type)
    except Exception as exc:
        _error(f"Decode failed: {exc}")

    out = output or f"{mac.lower()}.jpg"
    with open(out, "wb") as f:
        f.write(jpeg)
    _console.print(
        f"[green]✓[/green] {tag_type.name}  {tag_type.width}x{tag_type.height}  "
        f"raw={len(raw)}B → [bold]{out}[/bold] ({len(jpeg)}B)"
    )


# ── tag ───────────────────────────────────────────────────────────────────────


def _add_tag_parser(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    p = sub.add_parser("tag", help="Show detailed info for a single tag")
    _add_host(p)
    p.add_argument("mac", metavar="MAC", help="Tag MAC address")
    p.add_argument("--json", dest="output_json", action="store_true", help="Output as JSON")
    p.set_defaults(func=_cmd_tag)


def _cmd_tag(args: argparse.Namespace) -> None:
    _run(_tag(_host(args), args.mac, args.output_json))


async def _tag(host: str, mac: str, output_json: bool) -> None:
    mac = mac.upper()
    try:
        with _spinner() as p:
            p.add_task(f"Fetching tag {mac}…", total=None)
            async with OEPLClient(host) as client:
                tags = await client.get_tags()
                tag = next((t for t in tags if t.mac.upper() == mac), None)
                if tag is None:
                    _error(f"Tag {mac} not found on AP")
                tag_type = await client.get_tag_type(tag.hw_type)
    except OEPLError as exc:
        _error(str(exc))

    if output_json:
        _stdout.print_json(json.dumps({
            "mac": tag.mac,
            "alias": tag.alias,
            "hw_type": tag.hw_type,
            "hw_name": tag_type.name if tag_type else None,
            "width": tag_type.width if tag_type else None,
            "height": tag_type.height if tag_type else None,
            "battery_mv": tag.battery_mv,
            "rssi": tag.rssi,
            "lqi": tag.lqi,
            "temperature": tag.temperature,
            "channel": tag.channel,
            "firmware_version": tag.firmware_version,
            "last_seen": tag.last_seen,
            "next_update": tag.next_update,
            "next_checkin": tag.next_checkin,
            "pending": tag.pending,
            "update_count": tag.update_count,
            "content_mode": tag.content_mode,
            "wakeup_reason": tag.wakeup_reason,
            "capabilities": tag.capabilities,
            "rotate": tag.rotate,
            "lut": tag.lut,
            "is_external": tag.is_external,
            "ap_ip": tag.ap_ip,
        }))
        return

    hw_label = f"0x{tag.hw_type:02x}"
    if tag_type:
        hw_label += f"  {tag_type.name}  {tag_type.width}×{tag_type.height}  {tag_type.bpp}bpp"

    tree = Tree(f"Tag  [bold]{tag.mac.lower()}[/bold]", guide_style="cyan dim")

    info = tree.add("[bold]Identity[/bold]")
    info.add(f"Alias       {tag.alias or '—'}")
    info.add(f"Hardware    {hw_label}")
    info.add(f"Firmware    {tag.firmware_version}")
    if tag.is_external:
        info.add(f"External    via {tag.ap_ip}")

    radio = tree.add("[bold]Radio[/bold]")
    radio.add(f"Channel     {tag.channel}")
    radio.add(f"RSSI        {tag.rssi} dBm")
    radio.add(f"LQI         {tag.lqi}")

    status = tree.add("[bold]Status[/bold]")
    status.add(f"Battery     {tag.battery_mv} mV")
    if tag.temperature:
        status.add(f"Temp        {tag.temperature} °C")
    status.add(f"Last seen   {_ts(tag.last_seen)}")
    status.add(f"Next update {_ts(tag.next_update)}")
    status.add(f"Next checkin {_ts(tag.next_checkin)}")
    if tag.pending:
        status.add(f"[yellow]Pending     {tag.pending}[/yellow]")
    status.add(f"Updates     {tag.update_count}")

    _LUT_NAMES = {0: "Default", 1: "No repeats", 2: "Fast (no reds)", 3: "Fast", 0x10: "OTA"}
    _ROTATE_NAMES = {0: "None", 1: "90°", 2: "180°", 3: "270°"}

    def _enum_label(cls: type, val: int) -> str:
        try:
            return cls(val).name.replace("_", " ").title()
        except ValueError:
            return str(val)

    cfg = tree.add("[bold]Config[/bold]")
    cfg.add(f"Content mode  {_enum_label(ContentMode, tag.content_mode)}")
    cfg.add(f"Wakeup reason {_enum_label(WakeupReason, tag.wakeup_reason)}")
    cfg.add(f"Rotate        {_ROTATE_NAMES.get(tag.rotate, str(tag.rotate))}")
    cfg.add(f"LUT           {_LUT_NAMES.get(tag.lut, str(tag.lut))}")

    _CAPABILITIES = [
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
    active = [name for bit, name in _CAPABILITIES if tag.capabilities & bit]
    caps_branch = cfg.add(f"Capabilities  0x{tag.capabilities:04x}")
    for name in active:
        caps_branch.add(name)
    if not active:
        caps_branch.add("[dim]none[/dim]")

    _console.print(tree)


# ── entry point ───────────────────────────────────────────────────────────────


def main() -> None:
    """Entry point for the oepl CLI."""
    parser = argparse.ArgumentParser(
        prog="oepl",
        description="OpenEPaperLink AP command-line tool",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    sub = parser.add_subparsers(dest="command", required=True)

    _add_tags_parser(sub)
    _add_tag_parser(sub)
    _add_ap_parser(sub)
    _add_upload_parser(sub)
    _add_cmd_parser(sub)
    _add_led_parser(sub)
    _add_get_image_parser(sub)

    args = parser.parse_args()
    _setup_logging(args.verbose)
    args.func(args)


if __name__ == "__main__":
    main()
