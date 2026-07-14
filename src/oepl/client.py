"""OEPLClient — async client for the OpenEPaperLink AP."""

from __future__ import annotations

import asyncio
import io
import logging
from typing import Any, Callable

import aiohttp
from PIL import Image

from ._http import _HTTPClient
from .enums import LUT, Rotation, TagCommand
from .led import LEDPattern
from .models import APConfig, APInfo, APListItem, APStatus, Tag, TagType, UploadProgress
from .websocket import _WebSocketHandler

try:
    from epaper_dithering import ColorScheme, DitherMode, dither_image
except ImportError:
    DitherMode = None  # type: ignore[assignment,misc]
    ColorScheme = None  # type: ignore[assignment,misc]
    dither_image = None  # type: ignore[assignment]

_LOGGER = logging.getLogger(__name__)


class OEPLClient:
    """Async client for the OpenEPaperLink Access Point (AP).

    Usage::

        async with OEPLClient("192.168.1.100") as client:
            client.on_tag_update(lambda tag: print(tag))
            tags = client.tags

    Args:
        host: Hostname or IP address of the AP (without scheme).
        session: Optional existing ``aiohttp.ClientSession``. When omitted, an
            owned session is lazily created on first use (via the
            :attr:`session` property) and closed on :meth:`disconnect`. An
            injected session is never created, closed, or otherwise mutated by
            the client. Note: first access of an owned session must happen
            inside a running event loop.
        reconnect_interval: Seconds between WebSocket reconnection attempts.
    """

    def __init__(
        self,
        host: str,
        *,
        session: aiohttp.ClientSession | None = None,
        reconnect_interval: float = 30.0,
    ) -> None:
        self.host = host
        self._owned_session = session is None
        self._session: aiohttp.ClientSession | None = session
        self._http = _HTTPClient(host, lambda: self.session)
        self._ws_handler = _WebSocketHandler(self, reconnect_interval)
        self._ws_task: asyncio.Task[None] | None = None
        self._connected = False
        self._tags: dict[str, Tag] = {}

        # Callback registries
        self._tag_update_cbs: list[Callable[[Tag], None]] = []
        self._ap_status_cbs: list[Callable[[APStatus], None]] = []
        self._connection_change_cbs: list[Callable[[bool], None]] = []
        self._log_cbs: list[Callable[[str], None]] = []
        self._ap_item_cbs: list[Callable[[APListItem], None]] = []
        self._upload_progress_cbs: list[Callable[[UploadProgress], None]] = []
        self._touch_cbs: list[Callable[[dict[str, Any]], None]] = []
        self._console_cbs: list[Callable[[str], None]] = []
        self._raw_message_cbs: list[Callable[[dict[str, Any]], None]] = []

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "OEPLClient":
        await self.connect()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.disconnect()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Start the WebSocket connection to the AP."""
        if self._ws_task and not self._ws_task.done():
            return
        self._ws_task = asyncio.create_task(self._ws_handler.run())

    async def disconnect(self) -> None:
        """Stop the WebSocket connection and release resources."""
        self._ws_handler.stop()
        if self._ws_task:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                _LOGGER.debug("WebSocket task raised during disconnect: %s", exc)
            self._ws_task = None
        if self._owned_session and self._session is not None:
            await self._session.close()
            self._session = None

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    @property
    def session(self) -> aiohttp.ClientSession:
        """The ``aiohttp.ClientSession`` used for all requests.

        Returns the injected session if one was passed to the constructor.
        Otherwise, lazily creates (and owns) a new session on first access.
        This first access must happen inside a running event loop.
        """
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self._session

    @property
    def connected(self) -> bool:
        """True when the WebSocket is connected to the AP."""
        return self._connected

    @property
    def tags(self) -> dict[str, Tag]:
        """Snapshot of the current tag cache, keyed by MAC."""
        return dict(self._tags)

    # ------------------------------------------------------------------
    # Callback subscriptions — all return an unsubscribe callable
    # ------------------------------------------------------------------

    def on_tag_update(self, cb: Callable[[Tag], None]) -> Callable[[], None]:
        """Subscribe to tag update events.

        Args:
            cb: Called with the updated :class:`Tag` on each WebSocket tag message.

        Returns:
            Callable that removes the subscription when called.
        """
        self._tag_update_cbs.append(cb)
        return lambda: self._tag_update_cbs.remove(cb)

    def on_ap_status(self, cb: Callable[[APStatus], None]) -> Callable[[], None]:
        """Subscribe to AP system status updates."""
        self._ap_status_cbs.append(cb)
        return lambda: self._ap_status_cbs.remove(cb)

    def on_connection_change(self, cb: Callable[[bool], None]) -> Callable[[], None]:
        """Subscribe to connection state changes (True=connected, False=disconnected)."""
        self._connection_change_cbs.append(cb)
        return lambda: self._connection_change_cbs.remove(cb)

    def on_log(self, cb: Callable[[str], None]) -> Callable[[], None]:
        """Subscribe to log/error messages from the AP WebSocket."""
        self._log_cbs.append(cb)
        return lambda: self._log_cbs.remove(cb)

    def on_ap_item(self, cb: Callable[[APListItem], None]) -> Callable[[], None]:
        """Subscribe to mesh AP announcement events ('apitem' WS messages)."""
        self._ap_item_cbs.append(cb)
        return lambda: self._ap_item_cbs.remove(cb)

    def on_upload_progress(self, cb: Callable[[UploadProgress], None]) -> Callable[[], None]:
        """Subscribe to image-transfer progress events ('upload' WS messages)."""
        self._upload_progress_cbs.append(cb)
        return lambda: self._upload_progress_cbs.remove(cb)

    def on_touch(self, cb: Callable[[dict[str, Any]], None]) -> Callable[[], None]:
        """Subscribe to touchscreen events ('touch' WS messages, raw dict passthrough)."""
        self._touch_cbs.append(cb)
        return lambda: self._touch_cbs.remove(cb)

    def on_console(self, cb: Callable[[str], None]) -> Callable[[], None]:
        """Subscribe to serial console mirror text ('console' WS messages)."""
        self._console_cbs.append(cb)
        return lambda: self._console_cbs.remove(cb)

    def on_raw_message(self, cb: Callable[[dict[str, Any]], None]) -> Callable[[], None]:
        """Subscribe to every parsed WebSocket message dict, before typed routing.

        This is an escape hatch that fires for all messages, including types
        this library doesn't know how to parse.
        """
        self._raw_message_cbs.append(cb)
        return lambda: self._raw_message_cbs.remove(cb)

    # ------------------------------------------------------------------
    # Tag operations
    # ------------------------------------------------------------------

    async def get_tags(self) -> list[Tag]:
        """Fetch all tags from the AP database (paginated).

        Updates the internal tag cache and fires ``on_tag_update`` callbacks
        for each tag. Returns the full list of tags.
        """
        pos = 0
        result: list[Tag] = []
        while True:
            path = f"get_db?pos={pos}" if pos > 0 else "get_db"
            data = await self._http.get_json(path)
            for tag_dict in data.get("tags", []):
                tag = Tag.from_dict(tag_dict)
                self._tags[tag.mac] = tag
                self._fire_tag_update(tag)
                result.append(tag)
            cont = data.get("continu", 0)
            if not cont:
                break
            pos = cont
        return result

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
    ) -> None:
        """Upload an image to a tag through the AP.

        If *image* is a :class:`PIL.Image.Image` and *dither_mode* is not
        ``DitherMode.NONE``, client-side dithering is applied before upload
        (only when *epaper-dithering* is installed). PIL images are always
        encoded as JPEG (``quality=100, subsampling=0``) before upload; the AP
        decodes uploaded images exclusively with TJpgDec, which cannot read
        PNG.

        The AP performs **no scaling** of the uploaded image — it must already
        match the tag's native resolution, or the display renders garbage.
        ``/imgupload`` returns an empty body on success, so a failed upload
        (e.g. malformed multipart body, unsupported image) is generally *not*
        detectable from the HTTP response alone; a later API adds effect-based
        waiting to confirm the tag actually redrew.

        ``rotate``, ``lut``, ``invert`` and ``alias`` are omission-sensitive:
        the AP persists whichever of these fields are present onto the tag's
        stored record, so they are only sent when explicitly passed. Leaving
        them at their ``None`` default leaves the tag's existing configuration
        untouched.

        Args:
            mac: Tag MAC address (case-insensitive).
            image: PIL Image or raw image bytes to upload.
            dither_mode: Client-side dithering mode. Defaults to
                ``DitherMode.FLOYD_STEINBERG`` when *epaper-dithering* is
                installed, or no dithering if not installed. Only applies to
                PIL image input.
            color_scheme: Color scheme for dithering. Defaults to
                ``ColorScheme.BWR`` when *epaper-dithering* is installed. Only
                applies to PIL image input.
            dither: AP-side dithering mode (``0``=none, ``1``=Burkes,
                ``2``=ordered/pattern). When omitted: if *image* is a PIL
                image that was client-side dithered, ``0`` is sent (to avoid
                double-dithering); otherwise the field is omitted entirely and
                the firmware defaults to ``1`` (Burkes).
            ttl: Tag sleep interval in seconds. Converted to minutes internally.
                ``0`` → AP uses the tag's default sleep interval.
            content_mode: Tag content mode to assign (default ``24`` = static
                image; ``25`` = external/Home-Assistant-managed image).
            rotate: Image rotation applied server-side. Omitted (and left
                unchanged on the tag) unless explicitly passed.
            lut: Display refresh LUT mode. Omitted (and left unchanged on the
                tag) unless explicitly passed.
            invert: Invert the image colors. Omitted (and left unchanged on
                the tag) unless explicitly passed.
            alias: Display alias to set for the tag. Omitted (and left
                unchanged on the tag) unless explicitly passed.
            preload_type: Type for image preloading (``0`` = disabled).
            preload_lut: LUT for preloaded image.
        """
        client_dithered = False
        if isinstance(image, Image.Image):
            if dither_image is not None:
                _dm = dither_mode if dither_mode is not None else DitherMode.FLOYD_STEINBERG
                _cs = color_scheme if color_scheme is not None else ColorScheme.BWR
                if _dm != DitherMode.NONE:
                    image = dither_image(image, _cs, _dm)
                    client_dithered = True
            buf = io.BytesIO()
            image.convert("RGB").save(buf, format="JPEG", quality=100, subsampling=0)
            image_bytes = buf.getvalue()
            filename, content_type = "image.jpg", "image/jpeg"
        else:
            image_bytes = image
            filename, content_type = "image.jpg", "image/jpeg"

        ttl_minutes = max(1, ttl // 60) if ttl > 0 else 0

        fields: dict[str, Any] = {
            "mac": mac.upper(),
            "contentmode": str(content_mode),
            "ttl": str(ttl_minutes),
        }
        if rotate is not None:
            fields["rotate"] = str(rotate.value)
        if lut is not None:
            fields["lut"] = str(lut.value)
        if invert is not None:
            fields["invert"] = "1" if invert else "0"
        if alias is not None:
            fields["alias"] = alias
        if preload_type > 0:
            fields["preloadtype"] = str(preload_type)
            fields["preloadlut"] = str(preload_lut)

        if dither is not None:
            fields["dither"] = str(dither)
        elif client_dithered:
            fields["dither"] = "0"

        fields["image"] = (filename, image_bytes, content_type)

        await self._http.post_multipart("imgupload", fields)

    async def set_alias(self, mac: str, alias: str) -> None:
        """Set the display alias for a tag."""
        await self._http.post_form("save_cfg", {"mac": mac.upper(), "alias": alias})

    async def send_tag_cmd(self, mac: str, cmd: TagCommand) -> None:
        """Send a command to a tag (clear, refresh, reboot, scan)."""
        await self._http.post_form("tag_cmd", {"mac": mac.upper(), "cmd": cmd.value})

    async def set_led(self, mac: str, pattern: LEDPattern) -> None:
        """Flash an LED pattern on a tag."""
        encoded = pattern.encode()
        await self._http.get_text(f"led_flash?mac={mac.upper()}&pattern={encoded}")

    async def get_tag_type(self, hw_type: int) -> TagType | None:
        """Fetch the tag type definition for a given hw_type from the AP.

        The AP serves its own copy of tag type definitions under ``/tagtypes/``,
        so this works entirely offline — no GitHub or internet access required.

        Returns ``None`` if the AP has no definition for this hw_type (404).
        """
        import json

        data = await self._http.get_raw(f"tagtypes/{hw_type:02X}.json")
        if data is None:
            return None
        return TagType.from_dict(hw_type, json.loads(data))

    async def get_image_raw(self, mac: str) -> bytes | None:
        """Fetch the raw stored image for a tag from the AP.

        Returns ``None`` if the AP returns 404 (no image stored yet).
        Callers are responsible for decoding with :func:`oepl.decode_image`.
        """
        return await self._http.get_raw(f"current/{mac.upper()}.raw")

    # ------------------------------------------------------------------
    # AP operations
    # ------------------------------------------------------------------

    async def get_sysinfo(self) -> APInfo:
        """Fetch static AP hardware/firmware info from /sysinfo."""
        data = await self._http.get_json("sysinfo")
        return APInfo.from_dict(data)

    async def get_ap_config(self) -> APConfig:
        """Fetch the current AP configuration from /get_ap_config."""
        data = await self._http.get_json("get_ap_config")
        return APConfig.from_dict(data)

    async def save_ap_config(self, config: APConfig) -> None:
        """Write an AP configuration to /save_apcfg."""
        await self._http.post_form("save_apcfg", config.to_dict())

    async def reboot_ap(self) -> None:
        """Reboot the AP."""
        await self._http.post_form("reboot", {})

    async def set_time(self, epoch: int) -> None:
        """Sync the AP clock to a Unix epoch timestamp."""
        await self._http.post_form("set_time", {"epoch": str(epoch)})

    # ------------------------------------------------------------------
    # Internal helpers (called by _WebSocketHandler)
    # ------------------------------------------------------------------

    def _set_connected(self, value: bool) -> None:
        if self._connected != value:
            self._connected = value
            for cb in list(self._connection_change_cbs):
                try:
                    cb(value)
                except Exception as exc:
                    _LOGGER.debug("on_connection_change callback error: %s", exc)

    def _fire_tag_update(self, tag: Tag) -> None:
        for cb in list(self._tag_update_cbs):
            try:
                cb(tag)
            except Exception as exc:
                _LOGGER.debug("on_tag_update callback error: %s", exc)

    def _fire_ap_status(self, status: APStatus) -> None:
        for cb in list(self._ap_status_cbs):
            try:
                cb(status)
            except Exception as exc:
                _LOGGER.debug("on_ap_status callback error: %s", exc)

    def _fire_log(self, message: str) -> None:
        for cb in list(self._log_cbs):
            try:
                cb(message)
            except Exception as exc:
                _LOGGER.debug("on_log callback error: %s", exc)

    def _fire_ap_item(self, item: APListItem) -> None:
        for cb in list(self._ap_item_cbs):
            try:
                cb(item)
            except Exception as exc:
                _LOGGER.debug("on_ap_item callback error: %s", exc)

    def _fire_upload_progress(self, progress: UploadProgress) -> None:
        for cb in list(self._upload_progress_cbs):
            try:
                cb(progress)
            except Exception as exc:
                _LOGGER.debug("on_upload_progress callback error: %s", exc)

    def _fire_touch(self, data: dict[str, Any]) -> None:
        for cb in list(self._touch_cbs):
            try:
                cb(data)
            except Exception as exc:
                _LOGGER.debug("on_touch callback error: %s", exc)

    def _fire_console(self, text: str) -> None:
        for cb in list(self._console_cbs):
            try:
                cb(text)
            except Exception as exc:
                _LOGGER.debug("on_console callback error: %s", exc)

    def _fire_raw_message(self, data: dict[str, Any]) -> None:
        for cb in list(self._raw_message_cbs):
            try:
                cb(data)
            except Exception as exc:
                _LOGGER.debug("on_raw_message callback error: %s", exc)
