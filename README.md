# oepl

Async Python client for the [OpenEPaperLink](https://github.com/jjwbruijn/OpenEPaperLink) Access Point (AP).

- Full async/await API via `aiohttp`
- Live tag updates over WebSocket
- Image upload with optional client-side dithering
- Raw image download and decoding (G5, zlib, bitmap)
- LED flash control
- CLI for interactive use

## Installation

```bash
pip install py-oepl
```

With client-side dithering support:

```bash
pip install py-oepl epaper-dithering
```

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

`--lut` choices: `default`, `no-repeat`, `fast-no-reds`, `fast`
`--rotate` choices: `0`, `90`, `180`, `270`
`--ttl` is in seconds; `0` lets the AP use the tag's default sleep interval.

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
oepl get-image AABBCCDDEEFF              # prints decoded JPEG to stdout
oepl get-image AABBCCDDEEFF -o out.jpg   # save to file
```

Tag type definitions are fetched directly from the AP — no internet access required.

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

Use as an async context manager (recommended) or call `connect()` / `disconnect()` manually.

#### Tag operations

```python
# Fetch all tags (paginated); populates internal cache; fires on_tag_update callbacks
tags: list[Tag] = await client.get_tags()

# Upload an image (PIL Image or raw bytes)
from PIL import Image
img = Image.open("label.png")
await client.upload_image(
    "AABBCCDDEEFF",
    img,
    ttl=300,             # seconds; 0 = tag default
    rotate=Rotation.R90,
    lut=LUT.FAST,
)

# Set the alias shown in the AP web UI
await client.set_alias("AABBCCDDEEFF", "my-display")

# Send a command
from oepl import TagCommand
await client.send_tag_cmd("AABBCCDDEEFF", TagCommand.REFRESH)

# Flash LEDs
from oepl.led import Color, LEDPattern, LEDSegment
pattern = LEDPattern([LEDSegment(Color(255, 0, 0))], repeats=3)
await client.set_led("AABBCCDDEEFF", pattern)

# Fetch the tag type definition (served by the AP, works offline)
tag_type = await client.get_tag_type(0x16)  # returns TagType | None

# Download and decode the stored image for a tag
from oepl import decode_image
raw = await client.get_image_raw("AABBCCDDEEFF")  # bytes | None
if raw and tag_type:
    jpeg_bytes = decode_image(raw, tag_type)
```

#### AP operations

```python
info   = await client.get_sysinfo()    # APInfo — hardware/firmware
config = await client.get_ap_config()  # APConfig — current settings
await client.save_ap_config(config)
await client.set_time(int(time.time()))
await client.reboot_ap()
```

#### Live updates via WebSocket

```python
async with OEPLClient("192.168.1.100") as client:
    client.on_tag_update(lambda tag: print("updated:", tag.mac))
    client.on_ap_status(lambda s: print("AP free heap:", s.free_heap))
    client.on_connection_change(lambda ok: print("connected:", ok))
    client.on_log(lambda msg: print("AP log:", msg))

    # Callbacks fire as WebSocket messages arrive.
    # on_tag_update also fires for each tag returned by get_tags().
    tags = await client.get_tags()
    await asyncio.sleep(60)
```

Each `on_*` method returns an unsubscribe callable:

```python
unsub = client.on_tag_update(my_callback)
# later:
unsub()
```

### Models

| Class | Key fields |
|---|---|
| `Tag` | `mac`, `alias`, `hw_type`, `last_seen`, `battery_mv`, `lqi`, `rssi`, `channel`, `content_mode`, `firmware_version` |
| `APInfo` | `alias`, `env`, `build_version`, `ap_version`, `psram_size`, `flash_size`, `has_c6`, `has_ble` |
| `APConfig` | `ap_channel`, `led`, `maxsleep`, `tz`, `preview`, `night_start`, `night_end` |
| `APStatus` | `ip`, `heap`, `free_heap`, `run_status`, `temp`, `wifi_rssi`, `record_count` |
| `TagType` | `type_id`, `width`, `height`, `bpp`, `color_table`, `short_lut` |

### Enums

```python
from oepl import LUT, Rotation, TagCommand
from oepl.enums import APState, RunStatus
```

| Enum | Values |
|---|---|
| `LUT` | `NO_REPEAT`, `DEFAULT`, `FAST_NO_REDS`, `FAST` |
| `Rotation` | `NONE`, `R90`, `R180`, `R270` |
| `TagCommand` | `CLEAR`, `REFRESH`, `REBOOT`, `SCAN` |
| `APState` | `OFFLINE`, `ONLINE`, `FLASHING`, `WAIT_CHECKIN`, `WAIT_SETTIME`, `IDLE`, `DOWNLOADING`, `NO_RADIO` |

### Exceptions

```python
from oepl.exceptions import (
    OEPLError,           # base
    OEPLConnectionError, # could not reach AP
    OEPLTimeoutError,    # request timed out (after retries)
    OEPLNotFoundError,   # 404
    OEPLResponseError,   # other non-2xx (has .status and .body)
)
```

### Image dithering

When `epaper-dithering` is installed, `upload_image` applies Floyd-Steinberg dithering automatically for BWR displays. Override with:

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

## Development

```bash
uv sync
uv run pytest
```

## License

MIT
