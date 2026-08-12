"""OEPLClient — async client for the OpenEPaperLink AP."""

from __future__ import annotations

import asyncio
import io
import json
import logging
import time
from typing import Any, Callable

import aiohttp
from PIL import Image

from ._http import _HTTPClient, quote_query_value
from .enums import LUT, ContentMode, Rotation, TagCommand
from .exceptions import OEPLConnectionError, OEPLTimeoutError
from .files import Files
from .image import decode_image_pil
from .led import LEDPattern
from .models import (
    APConfig,
    APInfo,
    APListItem,
    APStatus,
    SSIDList,
    Tag,
    TagType,
    UploadProgress,
    WifiConfig,
)
from .tag_handle import TagHandle
from .websocket import _WebSocketHandler

try:
    from epaper_dithering import ColorScheme, DitherMode, dither_image
except ImportError:
    DitherMode = None  # type: ignore[assignment,misc]
    ColorScheme = None  # type: ignore[assignment,misc]
    dither_image = None  # type: ignore[assignment]

_LOGGER = logging.getLogger(__name__)

# /update_ota and /update_c6 launch a background FreeRTOS task and ack almost
# immediately ("In progress"/"Ok") rather than blocking for the real transfer,
# but a generous timeout is still used defensively in case the AP is busy
# with other single-threaded work at that exact moment (see docstrings).
_OTA_TIMEOUT = aiohttp.ClientTimeout(total=30)


class OEPLClient:
    """Async client for the OpenEPaperLink Access Point (AP).

    Usage::

        async with OEPLClient("192.168.1.100") as client:
            client.on_tag_update(lambda tag: print(tag))
            tags = client.tags
            listing = await client.files.list()

    Attributes:
        files: :class:`~oepl.files.Files` — browse/read/write/delete files on
            the AP's LittleFS content filesystem (``/edit``, ``/check_file``,
            ``/littlefs_put``).

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
        self.files = Files(self._http)
        self._ws_handler = _WebSocketHandler(self, reconnect_interval)
        self._ws_task: asyncio.Task[None] | None = None
        self._connected = False
        self._tags: dict[str, Tag] = {}
        self._tag_type_cache: dict[int, TagType | None] = {}

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

    def on_tag_update(self, cb: Callable[[Tag], None], *, mac: str | None = None) -> Callable[[], None]:
        """Subscribe to tag update events.

        Args:
            cb: Called with the updated :class:`Tag` on each WebSocket tag message.
            mac: When given, *cb* only fires for updates to this MAC
                (case-insensitive). Omitted (default) subscribes to all tags,
                matching prior behavior.

        Returns:
            Callable that removes the subscription when called.
        """
        registered: Callable[[Tag], None]
        if mac is not None:
            mac_upper = mac.upper()

            def _filtered(tag: Tag) -> None:
                if tag.mac == mac_upper:
                    cb(tag)

            registered = _filtered
        else:
            registered = cb
        self._tag_update_cbs.append(registered)
        return lambda: self._tag_update_cbs.remove(registered)

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

    async def get_tag(self, mac: str) -> Tag | None:
        """Fetch a single tag from the AP database by MAC.

        Updates the internal tag cache and fires ``on_tag_update`` on success,
        consistent with :meth:`get_tags`. Returns ``None`` if the AP has no
        record for this MAC (``/get_db?mac=...`` responds with an empty
        ``tags`` list rather than 404).
        """
        data = await self._http.get_json(f"get_db?mac={quote_query_value(mac.upper())}")
        tags = data.get("tags", [])
        if not tags:
            return None
        tag = Tag.from_dict(tags[0])
        self._tags[tag.mac] = tag
        self._fire_tag_update(tag)
        return tag

    def tag(self, mac: str) -> TagHandle:
        """Return a :class:`~oepl.tag_handle.TagHandle` bound to a single tag MAC.

        A thin, stateless-except-``(client, mac)`` convenience wrapper — every
        method on the handle delegates back to this client. *mac* is
        normalized to uppercase once, at construction time.
        """
        return TagHandle(self, mac)

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
        wait: bool = False,
        wait_timeout: float = 90.0,
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
            content_mode: Tag content mode to assign (default ``24`` =
                ``ContentMode.EXTERNAL_IMAGE``, an AP-managed static image;
                ``25`` = ``ContentMode.HOME_ASSISTANT``, an
                externally/Home-Assistant-managed image).
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
            wait: If ``True``, block after the upload until the tag actually
                redraws: the AP's WebSocket ``tags`` message for this MAC
                reports a changed ``hash`` *and* ``pending == 0`` (the
                on-hardware-verified render-complete signature — a changed
                hash alone can still be mid-transfer). Requires the
                WebSocket to already be connected (:attr:`connected`); raises
                :class:`~oepl.exceptions.OEPLConnectionError` immediately
                (before uploading) if it isn't, rather than hanging until
                *wait_timeout*.
            wait_timeout: Seconds to wait for render completion when
                ``wait=True``. Raises
                :class:`~oepl.exceptions.OEPLTimeoutError` if exceeded.

        Raises:
            OEPLConnectionError: If ``wait=True`` but the WebSocket isn't
                connected.
            OEPLTimeoutError: If ``wait=True`` and the tag doesn't report
                render completion within *wait_timeout* seconds.
        """
        if wait and not self._connected:
            raise OEPLConnectionError(
                "upload_image(wait=True) requires an active WebSocket connection to observe "
                "render completion (tags messages); call connect()/use 'async with' first."
            )

        mac_upper = mac.upper()
        pre_hash = self._tags[mac_upper].hash if mac_upper in self._tags else None

        client_dithered = False
        if isinstance(image, Image.Image):
            if dither_image is not None:
                _dm = dither_mode if dither_mode is not None else DitherMode.FLOYD_STEINBERG
                _cs = color_scheme if color_scheme is not None else ColorScheme.BWR
                if _dm != DitherMode.NONE:
                    image = dither_image(image, _cs, mode=_dm)
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
            "mac": mac_upper,
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

        if wait:
            await self._wait_for_render_complete(mac_upper, pre_hash, wait_timeout)

    async def save_tag_config(
        self,
        mac: str,
        *,
        content_mode: ContentMode | int | None = None,
        alias: str | None = None,
        mode_cfg_json: dict[str, Any] | str | None = None,
        rotate: Rotation | None = None,
        lut: LUT | None = None,
        invert: bool | None = None,
    ) -> None:
        """Update a tag's stored configuration via ``/save_cfg``.

        All keyword fields are omission-sensitive: the AP only touches the
        fields present in the POST body (``request->hasParam(...)`` per
        field), so omitted arguments leave the tag's existing configuration
        untouched. Passing no keyword arguments sends only ``mac`` and is a
        no-op on the AP.

        Args:
            mac: Tag MAC address (case-insensitive).
            content_mode: New content mode for the tag.
            alias: New display alias.
            mode_cfg_json: Content-mode-specific config. A ``dict`` is
                serialized with ``json.dumps``; a ``str`` is sent as-is.
            rotate: Image rotation.
            lut: Display refresh LUT mode.
            invert: Invert the image colors.

        Raises:
            OEPLResponseError: If the AP reports the MAC was not found
                (``200 "Error while saving: mac not found"``).
        """
        fields: dict[str, Any] = {"mac": mac.upper()}
        if content_mode is not None:
            fields["contentmode"] = str(int(content_mode))
        if alias is not None:
            fields["alias"] = alias
        if mode_cfg_json is not None:
            fields["modecfgjson"] = json.dumps(mode_cfg_json) if isinstance(mode_cfg_json, dict) else mode_cfg_json
        if rotate is not None:
            fields["rotate"] = str(rotate.value)
        if lut is not None:
            fields["lut"] = str(lut.value)
        if invert is not None:
            fields["invert"] = "1" if invert else "0"

        await self._http.post_form("save_cfg", fields)

    async def set_alias(self, mac: str, alias: str) -> None:
        """Set the display alias for a tag."""
        await self.save_tag_config(mac, alias=alias)

    async def send_tag_cmd(self, mac: str, cmd: TagCommand) -> None:
        """Send a command to a tag (clear, refresh, reboot, scan, ...)."""
        await self._http.post_form("tag_cmd", {"mac": mac.upper(), "cmd": cmd.value})

    async def delete_tag(self, mac: str) -> None:
        """Delete a single tag record from the AP's database.

        Sends ``TagCommand.DEL`` via :meth:`send_tag_cmd`, then removes
        *mac* from the local tag cache. The firmware sends no WebSocket
        message for tag deletion (``SYNC_DELETE`` only goes out over the
        mesh radio protocol, not to web clients), so the cache update here
        is the only signal this library gets.

        To bulk-delete stale tags, see :meth:`purge_stale_tags`.
        """
        await self.send_tag_cmd(mac, TagCommand.DEL)
        self._tags.pop(mac.upper(), None)

    async def purge_stale_tags(self) -> None:
        """Delete ALL stale tags from the AP's database. Cannot be scoped to one tag.

        Sends ``TagCommand.PURGE``. The firmware deletes every tag that
        never checked in, hasn't been seen for 24 hours, or is more than 10
        minutes overdue for its expected checkin — the entire database is
        swept in one go (``/tag_cmd`` handler, ``purge`` branch).

        The firmware's parameter guard still requires a ``mac`` form field
        naming a *currently registered* tag just to reach the command branch
        (it responds 400 "Error: mac not found" otherwise), even though the
        purge itself ignores that MAC. This method therefore first fetches
        the tag list and sends the MAC of an arbitrary registered tag; if
        the AP has no tags at all, there is nothing to purge (and no valid
        MAC to send), so it returns without issuing the command.

        The firmware sends no WebSocket deletion messages to web clients, so
        after the purge this method clears the local tag cache and re-fetches
        it via :meth:`get_tags` (firing ``on_tag_update`` for each surviving
        tag) so :attr:`tags` reflects the server-side deletions.
        """
        tags = await self.get_tags()
        if not tags:
            return
        await self.send_tag_cmd(tags[0].mac, TagCommand.PURGE)
        self._tags.clear()
        await self.get_tags()

    async def set_led(self, mac: str, pattern: LEDPattern) -> None:
        """Flash an LED pattern on a tag."""
        encoded = pattern.encode()
        await self._http.get_text(
            f"led_flash?mac={quote_query_value(mac.upper())}&pattern={quote_query_value(encoded)}"
        )

    async def get_tag_type(self, hw_type: int, *, use_cache: bool = True) -> TagType | None:
        """Fetch the tag type definition for a given hw_type from the AP.

        The AP serves its own copy of tag type definitions under ``/tagtypes/``,
        so this works entirely offline — no GitHub or internet access required.

        Results (including "no definition for this hw_type" misses) are cached
        in-memory per :class:`OEPLClient` instance, since tag type definitions
        are static for a given AP/firmware. Pass ``use_cache=False`` to bypass
        the cache and re-fetch/refresh the cached value.

        Returns ``None`` if the AP has no definition for this hw_type (404).
        """
        if use_cache and hw_type in self._tag_type_cache:
            return self._tag_type_cache[hw_type]
        data = await self._http.get_raw(f"tagtypes/{hw_type:02X}.json")
        result = TagType.from_dict(hw_type, json.loads(data)) if data is not None else None
        self._tag_type_cache[hw_type] = result
        return result

    async def get_image_raw(self, mac: str) -> bytes | None:
        """Fetch the raw stored image for a tag from the AP.

        Returns ``None`` if the AP returns 404 (no image stored yet).
        Callers are responsible for decoding with :func:`oepl.decode_image`.
        """
        return await self._http.get_raw(f"current/{mac.upper()}.raw")

    async def get_image(self, mac: str) -> "Image.Image | None":
        """Fetch and decode a tag's currently stored image in one call.

        Replaces the manual chain of :meth:`get_tag`/cache, :meth:`get_tag_type`,
        :meth:`get_image_raw`, and :func:`oepl.decode_image_pil`. Uses the
        cached :class:`Tag` (from :attr:`tags`) if available, otherwise fetches
        it; tag type lookups go through :meth:`get_tag_type`'s cache.

        Returns ``None`` if the AP has no record for *mac*, or no image stored
        for it yet (404 on ``current/<mac>.raw``) — checked *before* the tag
        type lookup below, so a tag with both an unrecognized ``hw_type`` and
        no stored image still returns ``None`` rather than raising: there's
        nothing to decode either way, and "no image" is the more specific,
        more useful answer.

        Raises:
            ValueError: If an image *is* stored for *mac* but the AP has no
                tag type definition for its ``hw_type`` — decoding requires
                the type's geometry (width/height/bpp/color table) and can't
                proceed without it.
        """
        mac_upper = mac.upper()
        tag = self._tags.get(mac_upper)
        if tag is None:
            tag = await self.get_tag(mac_upper)
        if tag is None:
            return None

        raw = await self.get_image_raw(mac_upper)
        if raw is None:
            return None

        tag_type = await self.get_tag_type(tag.hw_type)
        if tag_type is None:
            raise ValueError(
                f"No tag type definition for hw_type {tag.hw_type} (tag {mac_upper}); "
                "cannot decode image without tag geometry."
            )

        return decode_image_pil(raw, tag_type)

    async def wait_for_checkin(self, mac: str, *, timeout: float = 90.0) -> Tag:
        """Wait for the next WebSocket tag-update message for *mac*.

        Subscribes a temporary, MAC-filtered :meth:`on_tag_update` callback
        (always unsubscribed before returning/raising, success or failure) and
        resolves with the next :class:`Tag` reported for that MAC — not
        necessarily one reflecting any particular change; just the next
        check-in/update the AP reports. Requires the WebSocket to be
        connected to ever resolve.

        Raises:
            OEPLTimeoutError: If no update arrives within *timeout* seconds.
        """
        mac_upper = mac.upper()
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Tag] = loop.create_future()

        def _on_update(tag: Tag) -> None:
            if not future.done():
                future.set_result(tag)

        unsubscribe = self.on_tag_update(_on_update, mac=mac_upper)
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise OEPLTimeoutError(f"Timed out after {timeout}s waiting for {mac_upper} to check in") from exc
        finally:
            unsubscribe()

    async def _wait_for_render_complete(self, mac: str, pre_hash: str | None, timeout: float) -> None:
        """Wait until *mac* reports a changed image hash and pending == 0.

        This hash-change-plus-pending-zero pair is the render-complete signal
        verified against real hardware: a hash change alone can still be a
        transfer in progress, but firmware clears ``pending`` only once the
        tag has actually redrawn with the new content.
        """
        if pre_hash is None:
            _LOGGER.warning(
                "upload_image(wait=True): no cached hash baseline for %s (tag wasn't in the "
                "local cache at upload time); the render-complete check is weakened to just "
                "'pending == 0', which can resolve on an unrelated pending transition rather "
                "than the actual new render. Call get_tag(%s) first to warm the cache and "
                "restore the full 'hash changed AND pending == 0' guarantee.",
                mac,
                mac,
            )
        loop = asyncio.get_running_loop()
        future: asyncio.Future[None] = loop.create_future()

        def _on_update(tag: Tag) -> None:
            if not future.done() and tag.hash != pre_hash and tag.pending == 0:
                future.set_result(None)

        unsubscribe = self.on_tag_update(_on_update, mac=mac)
        try:
            await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise OEPLTimeoutError(
                f"Timed out after {timeout}s waiting for {mac} to finish rendering the uploaded image"
            ) from exc
        finally:
            unsubscribe()

    async def upload_json(self, mac: str, data: dict[str, Any] | str, *, ttl: int = 0) -> None:
        """Push a JSON payload to a tag for content mode 19 (JSON/custom rendering).

        POSTs to ``/jsonupload`` (``doJsonUpload``, web.cpp:1023-1060). The AP
        writes *data* verbatim to ``/current/<mac>.json`` on its filesystem,
        sets the tag's content mode to ``19``, and stores
        ``{"filename": "/current/<mac>.json", "interval": "<ttl>"}`` as the
        tag's ``modecfgjson``. Unlike ``upload_image``'s ``ttl`` (converted to
        minutes), *ttl* here is passed straight through as the raw
        ``interval`` value the firmware writes — verify the unit against the
        content-mode-19 renderer if precise timing matters; the endpoint
        itself performs no conversion.

        Args:
            mac: Tag MAC address (case-insensitive).
            data: JSON payload. A ``dict`` is serialized with ``json.dumps``;
                a ``str`` is sent as-is (must already be valid JSON).
            ttl: Value stored verbatim as the tag's ``interval`` config field.
                ``0`` means unset/default.

        Raises:
            OEPLResponseError: If the AP reports the MAC was not found.
        """
        json_str = json.dumps(data) if isinstance(data, dict) else data
        await self._http.post_form(
            "jsonupload",
            {"mac": mac.upper(), "json": json_str, "ttl": str(ttl)},
        )

    async def get_image_data(self, mac: str, *, md5: str | None = None) -> bytes | None:
        """Fetch the raw image bytes queued/stored for a tag from ``/getdata``.

        Without *md5*, returns the tag's currently stored image
        (``taginfo->data``/``taginfo->filename``) — the "older version
        without queue" path in the firmware. With *md5* (an 8-byte hash as
        hex, matching a queued image's content hash), looks up that specific
        queued item instead, letting callers fetch a not-yet-delivered image
        version by its hash rather than whatever is currently live.

        Returns ``None`` if the AP responds 404 (no queue item for that
        *md5*, or no file backing the stored/queued image). Note the AP also
        returns a plain-text 400 (not 404) if *mac* is missing/malformed or
        unknown to the AP entirely; that surfaces as ``OEPLResponseError``.
        """
        path = f"getdata?mac={quote_query_value(mac.upper())}"
        if md5 is not None:
            path += f"&md5={quote_query_value(md5)}"
        return await self._http.get_raw(path)

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

    async def set_ap_config_item(self, key: str, value: str | int | bool) -> None:
        """Set a single AP configuration item via ``/save_apcfg``.

        Sends a POST containing only *key* — the firmware reads each config
        param behind its own ``hasParam`` guard (web.cpp:613-688), so absent
        params are left unchanged and single-key writes are safe... with one
        exception: when ``sleeptime1`` is present, the firmware reads
        ``sleeptime2`` **unguarded** (web.cpp:659-662 — no ``hasParam`` check
        of its own), so posting ``sleeptime1`` without ``sleeptime2``
        dereferences a null ``AsyncWebParameter*`` and can crash the AP.
        This method therefore refuses both keys — use
        :meth:`set_sleep_window`, which always sends the pair together.

        Valid keys: ``alias``, ``channel``, ``subghzchannel``, ``led``,
        ``tft``, ``language``, ``maxsleep``, ``stopsleep``, ``preview``,
        ``nightlyreboot``, ``lock``, ``ble``, ``wifipower``, ``timezone``,
        ``discovery``, ``showtimestamp``, ``repo``, ``env``
        (plus ``sleeptime1``/``sleeptime2`` via :meth:`set_sleep_window` only).

        Args:
            key: Config item name (the AP's wire name, see list above).
            value: New value. ``bool`` is coerced to ``"1"``/``"0"``;
                ``int`` and ``str`` are sent as-is.

        Raises:
            ValueError: If *key* is ``"sleeptime1"`` or ``"sleeptime2"``.
        """
        if key in ("sleeptime1", "sleeptime2"):
            raise ValueError(
                "sleeptime1/sleeptime2 must be set together; use set_sleep_window(). "
                "Posting sleeptime1 alone crashes the AP firmware (web.cpp:659-662 "
                "reads sleeptime2 unguarded whenever sleeptime1 is present)."
            )
        coerced = ("1" if value else "0") if isinstance(value, bool) else str(value)
        await self._http.post_form("save_apcfg", {key: coerced})

    async def set_sleep_window(self, start_hour: int, end_hour: int) -> None:
        """Set the AP's nightly no-refresh ("sleep") window via ``/save_apcfg``.

        Always posts ``sleeptime1`` and ``sleeptime2`` together in a single
        request — the firmware reads ``sleeptime2`` unconditionally whenever
        ``sleeptime1`` is present (web.cpp:659-662), so the pair must never
        be split across requests (see :meth:`set_ap_config_item`).

        During the window (whole hours, AP-local time) the AP suspends
        content refreshes. Equal values disable the window entirely — the
        firmware's ``util::isSleeping`` returns false when
        ``sleeptime1 == sleeptime2`` (util.h:115) — so
        ``set_sleep_window(0, 0)`` turns it off, matching the web UI's "off"
        state. The window may wrap midnight (e.g. ``start_hour=23,
        end_hour=6``).

        Args:
            start_hour: Hour (0-23) the sleep window begins.
            end_hour: Hour (0-23) the sleep window ends.

        Raises:
            ValueError: If either hour is outside 0-23.
        """
        for name, hour in (("start_hour", start_hour), ("end_hour", end_hour)):
            if not 0 <= hour <= 23:
                raise ValueError(f"{name} must be in 0-23, got {hour}")
        await self._http.post_form(
            "save_apcfg",
            {"sleeptime1": str(start_hour), "sleeptime2": str(end_hour)},
        )

    async def reboot_ap(self) -> None:
        """Reboot the AP."""
        await self._http.post_form("reboot", {})

    async def set_time(self, epoch: int | None = None) -> None:
        """Sync the AP clock to a Unix epoch timestamp.

        Args:
            epoch: Unix timestamp (seconds) to set. Defaults to the current
                time (``int(time.time())``) when omitted. The firmware
                rejects (400) any value at or before ~2020-09-13
                (``web.cpp``'s sanity check, epoch <= 1600000000).
        """
        if epoch is None:
            epoch = int(time.time())
        await self._http.post_form("set_time", {"epoch": str(epoch)})

    async def set_variable(self, key: str, value: str) -> None:
        """Set a single template variable usable as ``{key}`` in JSON templates/content defs.

        POSTs to ``/set_var`` (web.cpp:712-722).
        """
        await self._http.post_form("set_var", {"key": key, "val": value})

    async def set_variables(self, variables: dict[str, str]) -> None:
        """Set multiple template variables at once via ``/set_vars`` (web.cpp:723-741).

        *variables* is serialized to JSON and sent as the ``json`` form field;
        the firmware iterates the object and calls the same per-key setter as
        :meth:`set_variable` for each entry.
        """
        await self._http.post_form("set_vars", {"json": json.dumps(variables)})

    async def get_wifi_config(self) -> WifiConfig:
        """Fetch the AP's stored WiFi/network settings from ``/get_wifi_config``.

        Includes the stored WiFi password in cleartext (as the firmware
        stores and returns it) — handle the result accordingly.
        """
        data = await self._http.get_json("get_wifi_config")
        return WifiConfig.from_dict(data)

    async def get_ssid_list(self) -> SSIDList:
        """Fetch nearby WiFi networks from ``/get_ssid_list`` (web.cpp:764-788).

        Each call also (re)starts a background scan on the AP if the last one
        is stale (>30s) or was never started, so ``scan_status`` may read
        ``-1`` (scanning) or ``-2`` (not started) on the first call(s) before
        settling to a network count — poll again after a short delay to get
        results.
        """
        data = await self._http.get_json("get_ssid_list")
        return SSIDList.from_dict(data)

    async def save_wifi_config(
        self,
        ssid: str,
        *,
        password: str | None = None,
        ip: str | None = None,
        mask: str | None = None,
        gateway: str | None = None,
        dns: str | None = None,
        force: bool = False,
    ) -> None:
        """Write WiFi/network settings via ``/save_wifi_config`` and reboot the AP.

        POSTs a **JSON body** (not form data) to ``/save_wifi_config``
        (``AsyncCallbackJsonWebHandler``, web.cpp:790-839). Only the keys
        passed are included in the body; the firmware only overwrites a
        stored preference when the corresponding JSON key is present and a
        string, so omitted keyword arguments leave that setting unchanged —
        except that **the AP unconditionally restarts at the end of this
        handler**, every time, regardless of which fields were sent.

        DANGER: if *ssid* is the literal string ``"factory"``, the firmware
        does not just update WiFi settings — it wipes the stored WiFi
        credentials, destroys the tag database, deletes OTA/update files and
        logs, and reboots into a factory-reset state (web.cpp:808-830). To
        guard against this being triggered by an accidental/templated value,
        this method raises :class:`ValueError` when ``ssid == "factory"``
        unless *force* is explicitly ``True``.

        Args:
            ssid: Network SSID to connect to.
            password: Network password.
            ip: Static IP address (empty/omitted for DHCP).
            mask: Static subnet mask.
            gateway: Static gateway address.
            dns: Static DNS server address.
            force: Must be ``True`` to allow ``ssid == "factory"``.

        Raises:
            ValueError: If ``ssid == "factory"`` and *force* is not ``True``.
        """
        if ssid == "factory" and not force:
            raise ValueError(
                "ssid='factory' triggers a firmware factory reset (wipes WiFi credentials, "
                "the tag database, and OTA files, then reboots) — pass force=True to confirm "
                "this is intentional."
            )
        payload: dict[str, Any] = {"ssid": ssid}
        if password is not None:
            payload["pw"] = password
        if ip is not None:
            payload["ip"] = ip
        if mask is not None:
            payload["mask"] = mask
        if gateway is not None:
            payload["gw"] = gateway
        if dns is not None:
            payload["dns"] = dns
        await self._http.post_json("save_wifi_config", payload)

    async def backup_db(self) -> bytes:
        """Download the AP's tag database as JSON bytes from ``/backup_db``.

        Raises:
            OEPLNotFoundError: If the AP responds 404.
        """
        return await self._http.get_bytes("backup_db")

    async def restore_db(self, data: bytes) -> None:
        """Replace the AP's tag database from a previously downloaded backup.

        POSTs *data* as a multipart file upload to ``/restore_db``
        (``dotagDBUpload``, web.cpp:1062-1078) under the ``file`` field name
        (matching the AP's own web UI). The AP destroys its current tag
        database and reloads it from the uploaded content immediately —
        **this is destructive and cannot be undone.** ``check_body=True`` so a
        200 response carrying an AP-reported error body (malformed backup,
        etc.) still surfaces as :class:`~oepl.exceptions.OEPLResponseError`
        instead of being swallowed as a silent success.
        """
        await self._http.post_multipart(
            "restore_db", {"file": ("tagDB.json", data, "application/json")}, check_body=True
        )

    # ------------------------------------------------------------------
    # OTA / firmware update — ALL of these flash firmware and/or reboot the
    # AP. There is no confirmation step; calling one of these methods is a
    # commitment. None of them are exercised against a real AP by this
    # library's test suite.
    # ------------------------------------------------------------------

    async def update_ota(self, url: str, md5: str, size: int) -> None:
        """Flash new AP firmware downloaded from *url*, then reboot. **DESTRUCTIVE.**

        POSTs to ``/update_ota`` (``handleUpdateOTA``, ``ota.cpp:195``). The
        HTTP response ("In progress") comes back almost immediately — the AP
        launches a background FreeRTOS task (``firmwareUpdateTask``) that
        downloads *url*, verifies it against *md5*/*size*, writes it via the
        ``Update`` library, and reboots; this call does **not** block for
        that duration. Progress and completion are reported only over the
        WebSocket (``wsSerial`` log lines, ending in ``"Reboot system now"``
        + a literal ``[reboot]`` marker) — use :meth:`on_log` and especially
        :meth:`on_connection_change` to track when the AP actually comes back.

        Args:
            url: HTTP(S) URL the AP itself will download the firmware image
                from (must be reachable from the AP, not from this process).
            md5: Expected MD5 hash of the firmware image (``Update.setMD5``).
            size: Firmware image size in bytes (``Update.begin(size)``).

        Raises:
            OEPLResponseError: If *url*/*md5*/*size* are missing (400) or the
                AP reports a download/flash error in the response body.
        """
        await self._http.post_form(
            "update_ota",
            {"url": url, "md5": md5, "size": str(size)},
            timeout=_OTA_TIMEOUT,
        )

    async def rollback(self) -> None:
        """Roll back to the previously running firmware image, then reboot. **DESTRUCTIVE.**

        POSTs to ``/rollback`` (``handleRollback``, ``ota.cpp:288``). Only
        succeeds if the AP has a rollback image available
        (``Update.canRollBack()``); otherwise the AP responds ``400``
        ("Rollback not allowed" / "Rollback failed"), surfaced here as
        :class:`~oepl.exceptions.OEPLResponseError`. On success the AP waits
        ~1s in-line then reboots — use :meth:`on_connection_change` to track
        it.

        Raises:
            OEPLResponseError: If no rollback image is available, or the
                rollback itself fails.
        """
        await self._http.post_form("rollback", {})

    async def run_update_actions(self) -> None:
        """Run post-update cleanup steps from ``/update_actions.json``. **Deletes files.**

        POSTs to ``/update_actions`` (``handleUpdateActions``,
        ``ota.cpp:401``). Reads a ``{"deletefile": [...]}`` manifest (left
        behind by some OTA updates to clean up files made obsolete by the
        new firmware) and deletes each listed path from the AP's
        filesystem, then removes the manifest itself. Always responds
        ``200`` — "No update actions needed" if there's no manifest, "Clean
        up finished" otherwise — so it's safe to call speculatively after
        any update, even if nothing needs cleaning up. Does not reboot.
        """
        await self._http.post_form("update_actions", {})

    async def update_c6(self, url: str) -> None:
        """Flash the companion C6/H2 sub-GHz radio from *url*. **DESTRUCTIVE.**

        POSTs to ``/update_c6`` (``handleUpdateC6``, ``ota.cpp:382``). Only
        implemented on AP builds compiled with sub-GHz radio support
        (``C6_OTA_FLASHING``); other builds respond ``400`` ("... flashing
        not implemented"), surfaced as
        :class:`~oepl.exceptions.OEPLResponseError` — check
        :attr:`~oepl.models.APConfig` (or ``get_sysinfo()``'s ``hasC6``)
        before calling this. Like :meth:`update_ota`, the HTTP response
        ("Ok") returns quickly once the flashing task launches; the AP then
        stops its serial task, flashes the sub-radio over the shared UART,
        and reinitializes it, coming back online without necessarily
        rebooting the whole AP. Track completion via :meth:`on_log`.

        Args:
            url: HTTP(S) URL the AP will download the sub-radio firmware
                image from.

        Raises:
            OEPLResponseError: If *url* is missing (400), or this AP build
                doesn't support C6/H2 flashing (400).
        """
        await self._http.post_form("update_c6", {"url": url}, timeout=_OTA_TIMEOUT)

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
