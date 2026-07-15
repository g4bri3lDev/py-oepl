# oepl

Async Python client for the [OpenEPaperLink](https://github.com/jjwbruijn/OpenEPaperLink) Access Point (AP).

- Full async/await API via `aiohttp`
- Live tag updates over WebSocket
- Image upload (client-side and/or AP-side dithering)
- Raw image download and decoding (G5, zlib, bitmap)
- LED flash control
- CLI for interactive use

## Installation

```bash
pip install py-oepl
```

The base install is a minimal library dependency (`aiohttp`, `pillow`, `numpy`). Two optional
extras add functionality:

```bash
pip install py-oepl[cli]      # oepl command-line tool (rich)
pip install py-oepl[dither]   # client-side dithering (epaper-dithering)
pip install py-oepl[cli,dither]
pip install py-oepl[all]      # both extras
```

- **`cli`** — required to run the `oepl` command. Without it, `oepl` prints an error and exits;
  the library itself (`import oepl`) works fine without this extra.
- **`dither`** — enables client-side dithering in `upload_image()` via the `epaper-dithering`
  package. Without it, `upload_image()` still works: the AP applies its own Burkes dithering
  server-side by default. See [Image dithering](#image-dithering) below.

`numpy` is a hard dependency used only by the G5 raw-image decoder (`oepl.decode_image`); this may
change in a future release.

## Quick start

```python
import asyncio
from oepl import OEPLClient

async def main():
    async with OEPLClient("192.168.1.100") as client:
        tags = await client.get_tags()
        for tag in tags:
            print(tag.mac, tag.alias, tag.battery_mv, "mV")

asyncio.run(main())
```

## CLI

Requires the `cli` extra (`pip install py-oepl[cli]`).

Set `OEPL_HOST` to avoid passing `--host` every time:

```bash
export OEPL_HOST=192.168.1.100
```

### List tags

```bash
oepl --host 192.168.1.100 tags
oepl tags --json          # machine-readable JSON
oepl tags --watch         # live stream via WebSocket
```

### Tag detail

```bash
oepl tag AABBCCDDEEFF
oepl tag AABBCCDDEEFF --json
```

### AP info

```bash
oepl ap                   # hardware info + current config
oepl ap --json
```

### Upload an image

```bash
oepl upload AABBCCDDEEFF image.png
oepl upload AABBCCDDEEFF image.png --lut fast --rotate 90 --ttl 300
```

`--lut` choices: `default` (0), `no-repeat` (1), `fast-no-reds` (2), `fast` (3), `ota` (0x10)
`--rotate` choices: `0`, `90`, `180`, `270`
`--ttl` is in seconds; `0` lets the AP use the tag's default sleep interval.

The image must already match the tag's native resolution — see the warning under
[`upload_image`](#upload_image) below; the CLI does not resize.

### Send a command

```bash
oepl cmd AABBCCDDEEFF refresh
oepl cmd AABBCCDDEEFF clear
oepl cmd AABBCCDDEEFF reboot
oepl cmd AABBCCDDEEFF scan
```

### Flash LEDs

```bash
oepl led AABBCCDDEEFF --color 255 0 0
oepl led AABBCCDDEEFF --color 0 255 0 --flash-speed 0.5 --flash-count 3
oepl led AABBCCDDEEFF --color 0 0 255 --brightness 3 --repeats 4
```

### Download and decode the stored image

```bash
oepl get-image AABBCCDDEEFF              # writes <mac>.jpg
oepl get-image AABBCCDDEEFF -o out.jpg   # save to a specific path
```

Tag type definitions are fetched directly from the AP — no internet access required. If no tag
type definition can be found, the raw bytes are saved as `<mac>.raw` instead.

## Python API

### `OEPLClient`

```python
from oepl import OEPLClient

client = OEPLClient(
    host="192.168.1.100",
    session=None,            # optional: supply an existing aiohttp.ClientSession
    reconnect_interval=30.0, # seconds between WebSocket reconnect attempts
)
```

Use as an async context manager (recommended, calls `connect()`/`disconnect()` automatically) or
call `connect()` / `disconnect()` manually.

#### Session injection (e.g. Home Assistant)

If you already manage an `aiohttp.ClientSession` — for example Home Assistant's shared session —
pass it in and the client will use it for every request:

```python
from homeassistant.helpers.aiohttp_client import async_get_clientsession

client = OEPLClient(host, session=async_get_clientsession(hass))
```

The client **never closes or otherwise mutates an injected session** (`disconnect()` leaves it
open). When no session is passed, an owned session is created lazily on first use (the `session`
property) and closed automatically by `disconnect()`. Because it's created lazily, the first
access must happen inside a running event loop — don't construct `OEPLClient` and touch
`client.session` outside of `asyncio.run(...)` or similar.

#### Tag operations

```python
# Fetch all tags (paginated); populates internal cache; fires on_tag_update callbacks
tags: list[Tag] = await client.get_tags()

# Fetch a single tag by MAC; same cache/callback behavior as get_tags(). None if unknown.
tag: Tag | None = await client.get_tag("AABBCCDDEEFF")

# Upload an image (PIL Image or raw bytes)
from PIL import Image
from oepl import Rotation, LUT

img = Image.open("label.png")
await client.upload_image(
    "AABBCCDDEEFF",
    img,
    ttl=300,             # seconds; 0 = tag default
    rotate=Rotation.R90,
    lut=LUT.FAST,
)

# Set the alias shown in the AP web UI (delegates to save_tag_config)
await client.set_alias("AABBCCDDEEFF", "my-display")

# Update tag config fields — only the ones you pass are sent/changed (omission-sensitive)
from oepl import ContentMode
await client.save_tag_config(
    "AABBCCDDEEFF",
    content_mode=ContentMode.TODAY,
    rotate=Rotation.R90,
    lut=LUT.FAST,
    invert=True,
)

# Send a command
from oepl import TagCommand
await client.send_tag_cmd("AABBCCDDEEFF", TagCommand.REFRESH)

# Delete a single tag (removes it from the AP's database and the local cache)
await client.delete_tag("AABBCCDDEEFF")

# Bulk-delete ALL stale tags AP-wide (never checked in, unseen for 24h, or
# >10min overdue) — cannot be scoped to one tag; refreshes the local cache
await client.purge_stale_tags()

# Flash LEDs
from oepl import Color, LEDPattern
pattern = LEDPattern.single(Color(255, 0, 0), repeats=3)
await client.set_led("AABBCCDDEEFF", pattern)

# Push a JSON payload for content mode 19 (custom/JSON rendering)
await client.upload_json("AABBCCDDEEFF", {"text": "hello"}, ttl=300)

# Fetch the tag type definition (served by the AP, works offline)
tag_type = await client.get_tag_type(0x16)  # returns TagType | None

# Download and decode the stored image for a tag
from oepl import decode_image
raw = await client.get_image_raw("AABBCCDDEEFF")  # bytes | None
if raw and tag_type:
    jpeg_bytes = decode_image(raw, tag_type)

# Fetch raw image bytes directly (optionally by queued md5 hash)
data = await client.get_image_data("AABBCCDDEEFF")  # bytes | None
```

##### `upload_image`

```python
async def upload_image(
    self,
    mac: str,
    image: "Image.Image | bytes",
    *,
    dither_mode: "DitherMode | None" = None,
    color_scheme: "ColorScheme | None" = None,
    dither: int | None = None,
    ttl: int = 0,
    content_mode: int = 24,
    rotate: Rotation | None = None,
    lut: LUT | None = None,
    invert: bool | None = None,
    alias: str | None = None,
    preload_type: int = 0,
    preload_lut: int = 0,
) -> None: ...
```

> **The AP does no scaling.** The uploaded image must already match the tag's native resolution
> (see `TagType.width`/`TagType.height` via `get_tag_type()`) or the display will render garbage.
> `oepl` never resizes images for you.

Key points:

- `image` may be a `PIL.Image.Image` or raw bytes. PIL images are always converted and encoded as
  JPEG (`quality=100, subsampling=0`) before upload — the AP decodes uploaded images exclusively
  with TJpgDec, which cannot read PNG or other formats.
- `content_mode` selects the tag content mode assigned by this upload: `24` (default) is a static
  AP-managed image; `25` marks it as an externally/Home-Assistant-managed image.
- `rotate`, `lut`, `invert`, and `alias` are **omission-sensitive**: the AP persists whichever of
  these fields are present in the request onto the tag's stored record. Leaving them at their
  `None` default means the field is not sent at all, and the tag's existing configuration for
  that field is left untouched. Passing e.g. `rotate=Rotation.NONE` explicitly *will* overwrite
  whatever rotation was previously stored.
- `dither` is the **AP-side** dithering mode: `0` = none, `1` = Burkes, `2` = ordered/pattern.
  When omitted: if `image` was a PIL image that this call already dithered client-side (see
  below), `0` is sent automatically to avoid double-dithering; otherwise the field is omitted
  entirely and the firmware defaults to `1` (Burkes). This interacts with the optional
  `epaper-dithering`-based client-side dithering (`dither_mode`/`color_scheme`, PIL input only) —
  the two are mutually exclusive per upload; whichever one actually ran is the one whose result
  reaches the tag.
- `/imgupload` **returns an empty body on success**, so a failed upload (malformed multipart body,
  unsupported image data, etc.) is generally *not* detectable from the HTTP response alone — the
  call will not raise just because the tag didn't actually redraw.

#### AP operations

```python
info   = await client.get_sysinfo()    # APInfo — static hardware/firmware info
config = await client.get_ap_config()  # APConfig — current settings
await client.save_ap_config(config)
await client.set_time()                # defaults to the current time; pass epoch=... to override
await client.reboot_ap()

# Change a single config item without touching the rest (omission-safe on the AP)
await client.set_ap_config_item("alias", "kitchen-ap")
await client.set_ap_config_item("preview", True)   # bools are sent as "1"/"0"

# Nightly no-refresh window (hours 0-23, AP-local; equal hours = off)
await client.set_sleep_window(23, 6)
await client.set_sleep_window(0, 0)   # disable

# Template variables usable as {key} in JSON templates / content definitions
await client.set_variable("owner", "alice")
await client.set_variables({"owner": "alice", "room": "kitchen"})

# WiFi settings
wifi = await client.get_wifi_config()   # WifiConfig — includes the stored password in cleartext
scan = await client.get_ssid_list()     # SSIDList — poll repeatedly; scan_status settles asynchronously
await client.save_wifi_config("my-ssid", password="my-pass", ip="192.168.1.50")

# Tag database backup/restore
backup = await client.backup_db()        # bytes (raw tagDB JSON)
await client.restore_db(backup)          # DESTRUCTIVE — replaces the tag database, cannot be undone
```

> **`save_wifi_config` always reboots the AP**, on every call, regardless of which fields
> changed (the firmware unconditionally restarts at the end of its handler). Passing
> `ssid="factory"` is even more destructive — it wipes WiFi credentials, the tag database, and
> OTA files before rebooting — so this method raises `ValueError` for `ssid="factory"` unless you
> pass `force=True`.

> **`set_ap_config_item` refuses `sleeptime1`/`sleeptime2`** (raises `ValueError`): the firmware
> reads `sleeptime2` unguarded whenever `sleeptime1` is present in a `/save_apcfg` POST
> (web.cpp:659-662), so posting either key alone can crash the AP. Use `set_sleep_window()`,
> which always sends the pair in a single request.

#### Files

`client.files` browses and edits the AP's LittleFS content filesystem, via the firmware's `/edit`
(`SPIFFSEditor.cpp`) and `/check_file`/`/littlefs_put` (`ota.cpp`) handlers:

```python
# List entries directly under a directory (non-recursive)
entries = await client.files.list("/")            # list[FileEntry]
for e in entries:
    print(e.type, e.name, e.size)                  # size is None for directories

# Download raw bytes; None if the AP 404s (missing file or directory)
data = await client.files.download("current/AABBCCDDEEFF.raw")

# Write bytes to a path (via /littlefs_put, not /edit's own upload — see below)
await client.files.upload("/temp/scratch.bin", b"...")

# Delete a path (the AP always answers 200 here, whether or not it existed — see below)
await client.files.delete("temp/scratch.bin")

# Query size + MD5 without downloading
info = await client.files.check("/temp/scratch.bin")   # {"filesize": int, "md5": str} | None
```

> **Path convention differs between the two underlying endpoints** (verified against firmware
> source, not docs): `list()`/`download()`/`delete()` go through `/edit`, which always prepends a
> `/` to the path you give it internally, so this library strips a leading slash before sending.
> `check()`/`upload()` go through `/check_file`/`/littlefs_put`, which use the path exactly as
> given with **no** normalization, so this library adds a leading slash if one is missing. In
> practice you can pass paths with or without a leading `/` to any of the five methods and they'll
> behave consistently with each other and with what `list()` returns.

> **`upload()` deliberately uses `/littlefs_put`, not `/edit`'s own POST.** `/edit`'s upload
> requires the multipart file field to be named `data` with the target path as its filename, and
> its "success" response is just a post-hoc `_fs.exists()` check. `/littlefs_put` streams straight
> to disk and reports `507` on a real write failure (e.g. disk full), which is a more useful
> signal.

> **`delete()` always responds `200`, even for a path that never existed** — `SPIFFSEditor.cpp`
> calls `_fs.remove()` without checking (or reporting) whether it actually succeeded. A successful
> call doesn't guarantee anything was actually removed.

> **`check()` never 404s.** Unlike almost every other AP endpoint, a missing file gets a `200`
> response with `{"filesize": 0, "md5": ""}` (`ota.cpp:73-107`) instead of a 404. This library
> treats that specific sentinel (empty `md5`) as "doesn't exist" and returns `None` — a genuinely
> empty *existing* file still hashes to `d41d8cd98f00b204e9800998ecf8427e`, never `""`.

#### OTA / firmware update

**All of these flash firmware and/or reboot the AP. There is no confirmation step or dry-run —
calling one is a commitment, and none of them are exercised against a real AP by this library's
test suite.**

```python
# Flash new AP firmware downloaded (by the AP itself) from a URL, then reboot
await client.update_ota("http://example.com/firmware.bin", md5="deadbeef...", size=1234567)

# Roll back to the previously running firmware image, then reboot
await client.rollback()

# Run any pending post-update cleanup (deletes files listed in /update_actions.json)
await client.run_update_actions()

# Flash the companion C6/H2 sub-GHz radio (only on AP builds that have one)
await client.update_c6("http://example.com/c6-firmware.bin")
```

> **The HTTP response from `update_ota`/`update_c6` comes back almost immediately** — the AP
> launches a background task and acks ("In progress" / "Ok") before the download or flash actually
> happens, so these calls do not block for the duration of the update. Progress and completion are
> reported only over the WebSocket (`wsSerial` log lines ending in a literal `[reboot]` marker for
> a full reboot) — subscribe to `on_log()` and especially `on_connection_change()` to track when
> the AP actually finishes and comes back.

> **`rollback()` and `update_c6()` fail with `OEPLResponseError` (HTTP 400)** if there's no
> rollback image available, or the AP build wasn't compiled with C6/H2 support, respectively.
> Check `get_sysinfo()`'s `rollback`/`hasC6`/`hasH2` fields (or `client.rollback`/hardware docs)
> before calling if you want to avoid the round trip.

#### Live updates via WebSocket

```python
async with OEPLClient("192.168.1.100") as client:
    client.on_tag_update(lambda tag: print("updated:", tag.mac))
    client.on_ap_status(lambda s: print("AP heap:", s.heap))
    client.on_connection_change(lambda ok: print("connected:", ok))
    client.on_log(lambda msg: print("AP log:", msg))
    client.on_ap_item(lambda item: print("mesh AP:", item.ip, item.alias))
    client.on_upload_progress(lambda p: print("upload:", p.src, p.current, "/", p.total))
    client.on_touch(lambda data: print("touch:", data))
    client.on_console(lambda text: print("console:", text))
    client.on_raw_message(lambda data: print("raw:", data))

    # Callbacks fire as WebSocket messages arrive.
    # on_tag_update also fires for each tag returned by get_tags().
    tags = await client.get_tags()
    await asyncio.sleep(60)
```

Available subscriptions:

| Method | Fires on | Payload |
|---|---|---|
| `on_tag_update` | `tags` WS message, or any `get_tags()` call | `Tag` |
| `on_ap_status` | `sys` WS message | `APStatus` |
| `on_connection_change` | WebSocket connect/disconnect | `bool` |
| `on_log` | `logMsg`/`errMsg` WS message | `str` |
| `on_ap_item` | `apitem` WS message (mesh AP announcement) | `APListItem` |
| `on_upload_progress` | `upload` WS message | `UploadProgress` |
| `on_touch` | `touch` WS message | `dict[str, Any]` (raw passthrough) |
| `on_console` | `console` WS message | `str` |
| `on_raw_message` | every parsed WS message, before typed routing | `dict[str, Any]` |

`on_raw_message` is an escape hatch: it fires for *every* message, including message types this
library doesn't parse into a typed model, which is useful while the wire protocol evolves.

Each `on_*` method returns an unsubscribe callable:

```python
unsub = client.on_tag_update(my_callback)
# later:
unsub()
```

### Models

Every model dataclass carries a `raw: dict[str, Any]` field holding the untouched dict the AP
sent, in case a field you need hasn't been mapped to a typed attribute yet.

| Class | Key fields |
|---|---|
| `Tag` | `mac`, `alias`, `hw_type`, `last_seen`, `next_update`, `next_checkin`, `pending`, `content_mode`, `lqi`, `rssi`, `temperature`, `battery_mv`, `wakeup_reason`, `capabilities`, `rotate`, `lut`, `update_count`, `is_external`, `ap_ip`, `channel`, `firmware_version`, `hash`, `modecfgjson`, `invert`, `update_last`, `raw` |
| `APInfo` | `alias`, `env`, `build_version`, `build_time`, `ap_version`, `psram_size`, `flash_size`, `has_c6`, `has_h2`, `can_rollback`, `sha`, `has_tslr`, `has_flasher`, `raw` |
| `APConfig` | `alias`, `channel`, `subghz_channel`, `led_brightness`, `tft_brightness`, `language`, `max_sleep`, `stop_sleep`, `timezone`, `preview`, `nightly_reboot`, `lock`, `wifi_power`, `sleep_time1`, `sleep_time2`, `ble_enabled`, `repo`, `env`, `discovery`, `show_timestamp`, plus read-only `has_ble`/`has_c6`/`has_h2`/`has_sub_ghz`/`ap_state`/`tlsr`/`save_space`/`has_flasher`, `raw` |
| `APStatus` | `current_time`, `heap`, `record_count`, `ap_state`, `run_state`, `rssi`, `wifi_ssid`, `uptime`, `db_size`, `little_fs_free`, `ps_ram_free`, `wifi_status`, `low_battery_count`, `timeout_count`, `raw` |
| `APListItem` | `ip`, `alias`, `count`, `channel`, `version`, `raw` |
| `UploadProgress` | `src` (tag MAC), `current`, `total`, `done` (property), `raw` |
| `TagType` | `type_id`, `width`, `height`, `bpp`, `version`, `name`, `rotatebuffer`, `color_table`, `short_lut`, `options`, `content_ids`, `template`, `raw` |
| `WifiConfig` | `ssid`, `password`, `ip`, `mask`, `gateway`, `dns`, `mac`, `raw` |
| `WifiNetwork` | `ssid`, `channel`, `rssi`, `encryption`, `raw` |
| `SSIDList` | `scan_status`, `networks` (`list[WifiNetwork]`), `raw` |
| `FileEntry` | `type` (`"file"`/`"dir"`), `name`, `size` (`None` for directories), `raw` |

Notes:

- `Tag` exposes `hash` (image content hash), `modecfgjson` (raw content-mode config JSON string),
  `invert`, and `update_last` in addition to the obvious fields.
- `Tag` has `last_seen_at`, `next_update_at`, `next_checkin_at`, and `update_last_at` properties
  that convert the corresponding epoch-int field to an aware UTC `datetime` (or `None` when the
  epoch is `0`/unset).
- `APConfig` has read-only, human-readable label properties: `wifi_power_label`,
  `led_brightness_label`, `tft_brightness_label`, `max_sleep_label`, `language_label`.
- `Tag.capabilities_list` decodes the `capabilities` bitmask into human names (e.g. `"LED"`,
  `"NFC"`).

### Enums

```python
from oepl import LUT, Rotation, TagCommand, APState, RunStatus, ContentMode, WakeupReason
```

| Enum | Values |
|---|---|
| `APState` | `OFFLINE`, `ONLINE`, `FLASHING`, `WAIT_RESET`, `REQUIRED_POWER_CYCLE`, `FAILED`, `COMING_ONLINE`, `NO_RADIO` |
| `RunStatus` | `STOP`, `PAUSE`, `RUN`, `INIT` |
| `Rotation` | `NONE`, `R90`, `R180`, `R270` |
| `LUT` | `DEFAULT` (0), `NO_REPEAT` (1), `FAST_NO_REDS` (2), `FAST` (3), `OTA` (0x10) |
| `TagCommand` | `CLEAR`, `REFRESH`, `REBOOT`, `SCAN` |
| `WakeupReason` | `TIMED`, `GPIO`, `NFC`, `BUTTON1`, `BUTTON2`, `RF`, `FAILED_OTA`, `FIRST_BOOT`, `NETWORK_SCAN`, `WDT_RESET` |
| `ContentMode` | `NOT_CONFIGURED`, `TODAY`, `COUNT_DAYS`, `COUNT_HOURS`, `WEATHER`, `FIRMWARE`, `IMAGE_URL`, `FORECAST`, `RSS_FEED`, `QR_CODE`, `CALENDAR`, `REMOTE_AP`, `SEG_STATIC`, `NFC_URL`, `BUIENRADAR`, `TAG_COMMAND`, `TAG_CONFIG`, `JSON_TEMPLATE`, `DISPLAY_COPY`, `AP_INFO`, `STATIC_IMAGE`, `STATIC_IMAGE_ADV`, `EXTERNAL_IMAGE`, `HOME_ASSISTANT`, `TIMESTAMP`, `DAY_AHEAD`, `TIME_RAW` |

#### Open enums

All of the enums above (except `TagCommand`, which is a plain `str` enum for commands *sent to*
the AP) are "open": firmware evolves faster than this library, so parsing an unrecognized integer
value never raises `ValueError`. Instead a pseudo-member is synthesized on the fly, e.g.
`APState(99)` produces a member named `UNKNOWN_0x63` that still behaves like a normal `IntEnum`
member for comparisons, `int()`, and identity.

Use `enum_label()` to get a human-readable label for any of these enum members, including unknown
ones:

```python
from oepl.enums import enum_label

enum_label(LUT.FAST_NO_REDS)      # "Fast No Reds"
enum_label(APState(99))           # "Unknown 0x63"
```

### LED patterns

```python
from oepl import Color, LEDPattern
from oepl.led import LEDSegment, LEDPatternMode

# Single-color flash, convenience constructor
pattern = LEDPattern.single(Color(255, 0, 0), flash_count=3, repeats=2, brightness=4)
await client.set_led(mac, pattern)

# Stop any running pattern
await client.set_led(mac, LEDPattern.off())

# Multi-segment pattern built by hand (1-3 segments)
pattern = LEDPattern(
    segments=[
        LEDSegment(Color.from_hex("#ff0000"), flash_speed=0.2, flash_count=2),
        LEDSegment(Color.from_hex("00ff00"), flash_speed=0.5, flash_count=1, delay=1.0),
    ],
    repeats=3,
    brightness=8,          # 1-16
    mode=LEDPatternMode.FLASH,
)
await client.set_led(mac, pattern)
```

`LEDPattern.encode()` produces the 24-hex-character wire format for `/led_flash`
(`struct ledFlash` in `oepl-proto.h`). Byte 0 packs two things: the HIGH nibble is
`brightness - 1` (1-16 → 0x0-0xF) and the LOW nibble is the pattern mode
(`LEDPatternMode.OFF` = stop any running pattern, `LEDPatternMode.FLASH` = play the segments).
`LEDPattern.off()` is a convenience for sending the `OFF` mode.

### Exceptions

```python
from oepl.exceptions import (
    OEPLError,           # base
    OEPLConnectionError, # could not reach AP
    OEPLTimeoutError,    # request timed out (after retries, for uploads)
    OEPLNotFoundError,   # 404
    OEPLResponseError,   # AP-reported error (has .status and .body)
)
```

`OEPLResponseError` is raised both for ordinary non-2xx HTTP responses *and* for the AP's
"200-but-actually-an-error" convention: some endpoints (e.g. `/save_cfg` with an unknown MAC)
return HTTP 200 with a body starting with `"Error"`/`"error"`. In that case
`OEPLResponseError.status` will be `200` — don't assume a caught `OEPLResponseError` always means
a non-2xx HTTP status.

### Image dithering

Client-side dithering requires the `dither` extra (`pip install py-oepl[dither]`), which installs
`epaper-dithering`. When it's installed, `upload_image()` applies Floyd-Steinberg dithering to PIL
image input by default. Override with:

```python
from oepl import DitherMode, ColorScheme

await client.upload_image(
    mac,
    pil_image,
    dither_mode=DitherMode.NONE,
    color_scheme=ColorScheme.BW,
)
```

`DitherMode` and `ColorScheme` are `None` when `epaper-dithering` is not installed.

Whether or not client-side dithering ran, the AP also applies its own dithering server-side
unless told otherwise — see the `dither` parameter under [`upload_image`](#upload_image) above for
how the two interact (they're mutually exclusive per upload; client-side dithering, when it runs,
forces the AP-side `dither` field to `0`/none for that upload).

## Development

```bash
uv sync --extra dev --extra cli --extra dither
uv run pytest
uv run ruff check src tests
uv run mypy src
```

## License

MIT
