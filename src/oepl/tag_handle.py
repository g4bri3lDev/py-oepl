"""Per-tag convenience handle — binds (client, mac) so callers stop threading MACs everywhere."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable, Literal

from PIL import Image, ImageOps

from .enums import TagCommand
from .led import LEDPattern
from .models import Tag, TagType

if TYPE_CHECKING:
    from .client import OEPLClient

_LOGGER = logging.getLogger(__name__)

FitMode = Literal["strict", "contain", "cover"]


class TagHandle:
    """Convenience wrapper bound to a single tag MAC.

    Thin and stateless beyond ``(client, mac)`` — every method here delegates
    straight back to the owning :class:`~oepl.client.OEPLClient`. Obtain one
    via :meth:`OEPLClient.tag`, not by constructing directly.
    """

    def __init__(self, client: "OEPLClient", mac: str) -> None:
        self._client = client
        self._mac = mac.upper()

    @property
    def mac(self) -> str:
        """The tag's MAC address, normalized to uppercase."""
        return self._mac

    @property
    def info(self) -> Tag | None:
        """Live view of this tag's cached :class:`Tag` record (``client.tags.get(mac)``).

        ``None`` if the tag hasn't been fetched/seen yet. Not a live-updating
        object itself — each access re-reads the client's current cache.
        """
        return self._client.tags.get(self._mac)

    async def get_type(self) -> TagType | None:
        """Fetch this tag's :class:`TagType` (hardware geometry) definition.

        Uses the cached :attr:`info` if available; otherwise fetches the tag
        record first. Returns ``None`` if the tag itself is unknown to the AP,
        or the AP has no type definition for its ``hw_type``.
        """
        tag = self.info
        if tag is None:
            tag = await self._client.get_tag(self._mac)
        if tag is None:
            return None
        return await self._client.get_tag_type(tag.hw_type)

    async def upload_image(
        self,
        image: "Image.Image | bytes",
        *,
        fit: FitMode = "strict",
        wait: bool = False,
        wait_timeout: float = 90.0,
        **kwargs: Any,
    ) -> None:
        """Upload an image to this tag, with size validation/fitting.

        The AP performs no scaling of its own — an uploaded image that
        doesn't exactly match the tag's native resolution renders as garbage
        (verified on hardware). This wrapper looks up the tag's expected
        ``(width, height)`` (via :meth:`get_type`) and enforces or fixes it up
        before delegating to :meth:`OEPLClient.upload_image`:

        - ``fit="strict"`` (default): raise :class:`ValueError` (naming both
          the actual and expected size) on any mismatch.
        - ``fit="contain"``: letterbox the image onto a white
          ``(width, height)`` canvas, preserving aspect ratio
          (``PIL.ImageOps.contain`` + centered paste).
        - ``fit="cover"``: resize and center-crop to exactly
          ``(width, height)`` (``PIL.ImageOps.fit``).

        Size validation only applies to :class:`PIL.Image.Image` input — raw
        ``bytes`` are passed straight through unvalidated (there's no way to
        introspect the pixel dimensions of an arbitrary encoded blob without
        decoding it, which this method doesn't do).

        If the tag or its tag type is unknown (no DB record for this MAC, or
        no type definition on the AP), size can't be computed: ``fit="strict"``
        raises :class:`ValueError`; ``fit="contain"``/``"cover"`` instead log a
        ``warning`` and upload the image unresized.

        Args:
            image: PIL Image or raw image bytes to upload.
            fit: How to reconcile a size mismatch; see above.
            wait: Forwarded to :meth:`OEPLClient.upload_image` — block until
                the tag reports render completion.
            wait_timeout: Forwarded to :meth:`OEPLClient.upload_image`.
            **kwargs: Forwarded to :meth:`OEPLClient.upload_image` (``ttl``,
                ``rotate``, ``lut``, ``dither_mode``, etc).

        Raises:
            ValueError: ``fit="strict"`` and the image size doesn't match the
                tag's expected size, or the expected size couldn't be
                determined at all.
        """
        if isinstance(image, Image.Image):
            tag_type = await self.get_type()
            if tag_type is None:
                if fit == "strict":
                    raise ValueError(
                        f"Cannot validate image size for tag {self._mac}: tag or tag type is "
                        "unknown to the AP (no DB record, or no type definition). Pass "
                        "fit='contain'/'cover' to upload anyway (unresized, at your own risk)."
                    )
                _LOGGER.warning(
                    "Tag type unknown for %s; uploading image unresized (fit=%r cannot compute a target size).",
                    self._mac,
                    fit,
                )
            else:
                expected = (tag_type.width, tag_type.height)
                actual = image.size
                if actual != expected:
                    if fit == "strict":
                        raise ValueError(
                            f"Image size {actual} does not match tag {self._mac}'s expected size "
                            f"{expected} (fit='strict'). Resize the image yourself, or pass "
                            "fit='contain' (letterbox) / fit='cover' (crop) to fit automatically."
                        )
                    if fit == "contain":
                        fitted = ImageOps.contain(image, expected)
                        canvas = Image.new("RGB", expected, "white")
                        offset = ((expected[0] - fitted.width) // 2, (expected[1] - fitted.height) // 2)
                        canvas.paste(fitted, offset)
                        image = canvas
                    else:  # "cover"
                        image = ImageOps.fit(image, expected)
        else:
            _LOGGER.debug("Raw bytes image for %s: size validation skipped (fit=%r has no effect).", self._mac, fit)

        await self._client.upload_image(self._mac, image, wait=wait, wait_timeout=wait_timeout, **kwargs)

    async def upload_json(self, data: dict[str, Any] | str, *, ttl: int = 0) -> None:
        """Push a JSON payload for content mode 19. See :meth:`OEPLClient.upload_json`."""
        await self._client.upload_json(self._mac, data, ttl=ttl)

    async def set_led(self, pattern: LEDPattern) -> None:
        """Flash an LED pattern on this tag. See :meth:`OEPLClient.set_led`."""
        await self._client.set_led(self._mac, pattern)

    async def set_alias(self, alias: str) -> None:
        """Set this tag's display alias. See :meth:`OEPLClient.set_alias`."""
        await self._client.set_alias(self._mac, alias)

    async def save_config(self, **kwargs: Any) -> None:
        """Update this tag's stored configuration. See :meth:`OEPLClient.save_tag_config`."""
        await self._client.save_tag_config(self._mac, **kwargs)

    async def refresh(self) -> None:
        """Force this tag to redraw its current content."""
        await self._client.send_tag_cmd(self._mac, TagCommand.REFRESH)

    async def clear_pending(self) -> None:
        """Clear this tag's pending update."""
        await self._client.send_tag_cmd(self._mac, TagCommand.CLEAR)

    async def reboot(self) -> None:
        """Reboot this tag."""
        await self._client.send_tag_cmd(self._mac, TagCommand.REBOOT)

    async def scan(self) -> None:
        """Trigger a channel scan on this tag."""
        await self._client.send_tag_cmd(self._mac, TagCommand.SCAN)

    async def deep_sleep(self) -> None:
        """Put this tag into deep sleep until woken by button press or NFC."""
        await self._client.send_tag_cmd(self._mac, TagCommand.DEEPSLEEP)

    async def delete(self) -> None:
        """Delete this tag's record from the AP's database. See :meth:`OEPLClient.delete_tag`."""
        await self._client.delete_tag(self._mac)

    async def get_image(self) -> "Image.Image | None":
        """Fetch and decode this tag's currently stored image. See :meth:`OEPLClient.get_image`."""
        return await self._client.get_image(self._mac)

    async def wait_for_checkin(self, *, timeout: float = 90.0) -> Tag:
        """Wait for the next WebSocket tag-update message for this tag. See :meth:`OEPLClient.wait_for_checkin`."""
        return await self._client.wait_for_checkin(self._mac, timeout=timeout)

    def on_update(self, cb: Callable[[Tag], None]) -> Callable[[], None]:
        """Subscribe to update events for this tag only.

        Equivalent to ``client.on_tag_update(cb, mac=self.mac)``.

        Returns:
            Callable that removes the subscription when called.
        """
        return self._client.on_tag_update(cb, mac=self._mac)
