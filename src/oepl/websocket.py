"""WebSocket handler for the OpenEPaperLink AP."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

import aiohttp

from .models import APListItem, APStatus, Tag, UploadProgress

if TYPE_CHECKING:
    from .client import OEPLClient

_LOGGER = logging.getLogger(__name__)


class _WebSocketHandler:
    """Manages the WebSocket connection lifecycle and message routing."""

    def __init__(self, client: "OEPLClient", reconnect_interval: float) -> None:
        self._client = client
        self._reconnect_interval = reconnect_interval
        self._stop = asyncio.Event()

    def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        """Connect to the AP WebSocket and process messages until stopped."""
        while not self._stop.is_set():
            try:
                ws_url = f"ws://{self._client.host}/ws"
                async with self._client.session.ws_connect(ws_url, heartbeat=30) as ws:
                    _LOGGER.debug("WebSocket connected to %s", ws_url)
                    self._client._set_connected(True)

                    # Prime the tag cache immediately after connect
                    try:
                        await self._client.get_tags()
                    except Exception as exc:
                        _LOGGER.warning("Failed to prime tag cache on connect: %s", exc)

                    while not self._stop.is_set():
                        try:
                            msg = await ws.receive()
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                should_disconnect = await self._handle_message(msg.data)
                                if should_disconnect:
                                    break
                            elif msg.type in (
                                aiohttp.WSMsgType.ERROR,
                                aiohttp.WSMsgType.CLOSING,
                                aiohttp.WSMsgType.CLOSED,
                            ):
                                _LOGGER.debug("WebSocket closed/error: %s", msg.type)
                                break
                        except asyncio.CancelledError:
                            raise
                        except Exception as exc:
                            _LOGGER.error("Error handling WebSocket message: %s", exc)

            except asyncio.CancelledError:
                raise
            except aiohttp.ClientError as exc:
                _LOGGER.error("WebSocket connection error: %s", exc)
            except Exception as exc:
                _LOGGER.error("Unexpected WebSocket error: %s", exc)
            finally:
                self._client._set_connected(False)

            if not self._stop.is_set():
                _LOGGER.debug("Reconnecting in %s seconds", self._reconnect_interval)
                await asyncio.sleep(self._reconnect_interval)

    async def _handle_message(self, raw: str) -> bool:
        """Parse and route a raw WebSocket message from the AP.

        Returns ``True`` if the caller should break out of the receive loop
        (currently only after an ``errMsg: REBOOTING`` notification, so the
        outer loop in :meth:`run` reconnects).
        """
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            _LOGGER.debug("Could not parse WebSocket message: %.80s", raw)
            return False

        self._client._fire_raw_message(data)

        if "tags" in data:
            try:
                for tag_data in data["tags"]:
                    tag = Tag.from_dict(tag_data)
                    self._client._tags[tag.mac] = tag
                    self._client._fire_tag_update(tag)
            except Exception as exc:
                _LOGGER.warning("Could not parse 'tags' WebSocket message: %s", exc)

        elif "sys" in data:
            try:
                status = APStatus.from_dict(data["sys"])
                self._client._fire_ap_status(status)
            except Exception as exc:
                _LOGGER.warning("Could not parse 'sys' WebSocket message: %s", exc)

        elif "logMsg" in data:
            self._client._fire_log(data["logMsg"])

        elif "errMsg" in data:
            msg = data["errMsg"]
            self._client._fire_log(f"errMsg: {msg}")
            if msg == "REBOOTING":
                _LOGGER.info("AP is rebooting; waiting before reconnecting")
                self._client._set_connected(False)
                # Wait extra time for the AP to come back up, then signal the
                # caller to break out of the inner receive loop so the outer
                # loop reconnects.
                await asyncio.sleep(5)
                return True

        elif "apitem" in data:
            try:
                item = APListItem.from_dict(data["apitem"])
                self._client._fire_ap_item(item)
            except Exception as exc:
                _LOGGER.warning("Could not parse 'apitem' WebSocket message: %s", exc)

        elif "upload" in data:
            try:
                progress = UploadProgress.from_dict(data["upload"])
                self._client._fire_upload_progress(progress)
            except Exception as exc:
                _LOGGER.warning("Could not parse 'upload' WebSocket message: %s", exc)

        elif "touch" in data:
            self._client._fire_touch(data["touch"])

        elif "console" in data:
            self._client._fire_console(data["console"])

        else:
            _LOGGER.debug("Unknown WebSocket message type: %s", list(data.keys()))

        return False
