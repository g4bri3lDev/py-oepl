"""WebSocket handler for the OpenDisplay AP."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Callable

import aiohttp

from .models import APStatus, Tag

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
                async with self._client._session.ws_connect(ws_url, heartbeat=30) as ws:
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
                                await self._handle_message(msg.data)
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

    async def _handle_message(self, raw: str) -> None:
        """Parse and route a raw WebSocket message from the AP.

        The AP prepends garbage bytes before the JSON object, so we strip
        everything up to and including the first '{'.
        """
        try:
            data = json.loads("{" + raw.split("{", 1)[-1])
        except json.JSONDecodeError:
            _LOGGER.debug("Could not parse WebSocket message: %.80s", raw)
            return

        if "tags" in data:
            for tag_data in data["tags"]:
                tag = Tag.from_dict(tag_data)
                self._client._tags[tag.mac] = tag
                self._client._fire_tag_update(tag)

        elif "sys" in data:
            try:
                status = APStatus.from_dict(data["sys"])
                self._client._fire_ap_status(status)
            except Exception as exc:
                _LOGGER.debug("Could not parse sys message: %s", exc)

        elif "logMsg" in data:
            self._client._fire_log(data["logMsg"])

        elif "errMsg" in data:
            msg = data["errMsg"]
            self._client._fire_log(f"errMsg: {msg}")
            if msg == "REBOOTING":
                _LOGGER.info("AP is rebooting; waiting before reconnecting")
                self._client._set_connected(False)
                # Wait extra time for the AP to come back up, then break out of
                # the inner receive loop so the outer loop reconnects.
                await asyncio.sleep(5)

        elif "apitem" in data:
            # Config change notifications are ignored; callers re-fetch on demand.
            pass

        else:
            _LOGGER.debug("Unknown WebSocket message type: %s", list(data.keys()))
