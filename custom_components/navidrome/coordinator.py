import asyncio
import json
import logging
from datetime import timedelta

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import NavidromeAPI, NavidromeError
from .const import FALLBACK_POLL_INTERVAL, SSE_RECONNECT_DELAY

_LOGGER = logging.getLogger(__name__)


class NavidromeCoordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, api: NavidromeAPI, entry_id: str):
        super().__init__(
            hass,
            _LOGGER,
            name="navidrome",
            update_interval=timedelta(seconds=FALLBACK_POLL_INTERVAL),
        )
        self.api = api
        self.entry_id = entry_id
        self._sse_task: asyncio.Task | None = None
        self._sse_connected = False
        self._library_data: dict = {}

    async def _async_update_data(self) -> dict:
        try:
            now_playing = await self.api.get_now_playing()
            scan_status = await self.api.get_scan_status()
            system = await self.api.get_system_info()

            if not self._library_data:
                await self._refresh_library()

            return {
                "now_playing": now_playing,
                "scan_status": scan_status,
                "system": system,
                **self._library_data,
            }
        except NavidromeError as err:
            raise UpdateFailed(str(err)) from err
        except Exception as err:
            raise UpdateFailed(str(err)) from err

    async def _refresh_library(self):
        genres = await self.api.get_genres()
        artists = await self.api.get_artists()
        playlists = await self.api.get_playlists()
        self._library_data = {
            "genres": genres,
            "artists": artists,
            "playlists": playlists,
        }

    async def start_sse(self):
        if self._sse_task is None or self._sse_task.done():
            self._sse_task = asyncio.create_task(self._sse_loop())

    async def stop_sse(self):
        if self._sse_task and not self._sse_task.done():
            self._sse_task.cancel()
            try:
                await self._sse_task
            except asyncio.CancelledError:
                pass
        self._sse_connected = False

    async def _sse_loop(self):
        while True:
            try:
                await self._sse_listen()
            except asyncio.CancelledError:
                raise
            except Exception:
                _LOGGER.debug("SSE connection lost, reconnecting in %ss", SSE_RECONNECT_DELAY)
                self._sse_connected = False
                await asyncio.sleep(SSE_RECONNECT_DELAY)

    async def _sse_listen(self):
        await self.api._ensure_auth()
        url = self.api.sse_url

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    _LOGGER.warning("SSE connection failed with status %s", resp.status)
                    return

                self._sse_connected = True
                _LOGGER.debug("SSE connected to Navidrome")

                buffer = ""
                async for chunk in resp.content.iter_any():
                    buffer += chunk.decode("utf-8", errors="replace")
                    while "\n\n" in buffer:
                        event_block, buffer = buffer.split("\n\n", 1)
                        await self._handle_sse_block(event_block)

    async def _handle_sse_block(self, block: str):
        event_type = None
        data_lines = []

        for line in block.split("\n"):
            if line.startswith("event:"):
                event_type = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].strip())

        if not event_type:
            return

        data_str = "\n".join(data_lines)
        data = None
        if data_str:
            try:
                data = json.loads(data_str)
            except json.JSONDecodeError:
                data = data_str

        await self._process_event(event_type, data)

    async def _process_event(self, event_type: str, data):
        if event_type == "nowPlayingCount":
            await self.async_request_refresh()
        elif event_type == "scanStatus":
            if isinstance(data, dict) and not data.get("scanning", True):
                await self._refresh_library()
            await self.async_request_refresh()
        elif event_type == "refreshResource":
            await self._refresh_library()
            await self.async_request_refresh()
        elif event_type == "keepAlive":
            pass
