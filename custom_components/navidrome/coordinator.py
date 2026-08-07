import asyncio
import json
import logging
from datetime import timedelta

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import NavidromeAPI, NavidromeAuthError, NavidromeError
from .const import (
    FALLBACK_POLL_INTERVAL,
    SSE_INITIAL_RECONNECT_DELAY,
    SSE_KEEPALIVE_TIMEOUT,
    SSE_MAX_RECONNECT_DELAY,
)

_LOGGER = logging.getLogger(__name__)


class NavidromeCoordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, api: NavidromeAPI, entry: ConfigEntry):
        super().__init__(
            hass,
            _LOGGER,
            name="navidrome",
            update_interval=timedelta(seconds=FALLBACK_POLL_INTERVAL),
            config_entry=entry,
        )
        self.api = api
        self._sse_task: asyncio.Task | None = None
        self._sse_session: aiohttp.ClientSession | None = None
        self._library_data: dict = {}
        self._library_refresh_pending = False

    async def _async_update_data(self) -> dict:
        try:
            now_playing, scan_status, system = await asyncio.gather(
                self.api.get_now_playing(),
                self.api.get_scan_status(),
                self.api.get_system_info(),
            )

            if not self._library_data:
                await self._refresh_library()

            return {
                "now_playing": now_playing,
                "scan_status": scan_status,
                "system": system,
                **self._library_data,
            }
        except NavidromeAuthError as err:
            raise UpdateFailed(str(err)) from err
        except NavidromeError as err:
            raise UpdateFailed(str(err)) from err

    async def _refresh_library(self):
        genres, artists, playlists = await asyncio.gather(
            self.api.get_genres(),
            self.api.get_artists(),
            self.api.get_playlists(),
        )
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
        if self._sse_session and not self._sse_session.closed:
            await self._sse_session.close()
            self._sse_session = None

    async def _sse_loop(self):
        delay = SSE_INITIAL_RECONNECT_DELAY
        first_failure = True

        while True:
            try:
                await self._sse_listen()
                delay = SSE_INITIAL_RECONNECT_DELAY
                first_failure = True
            except asyncio.CancelledError:
                raise
            except Exception as err:
                if first_failure:
                    _LOGGER.warning("SSE connection lost: %s", err)
                    first_failure = False
                else:
                    _LOGGER.debug("SSE reconnect failed: %s", err)
                await asyncio.sleep(delay)
                delay = min(delay * 2, SSE_MAX_RECONNECT_DELAY)

    async def _sse_listen(self):
        await self.api._ensure_auth()

        if self._sse_session and not self._sse_session.closed:
            await self._sse_session.close()

        self._sse_session = aiohttp.ClientSession()

        try:
            async with self._sse_session.get(
                f"{self.api.base_url}/events",
                headers=self.api.sse_headers,
                timeout=aiohttp.ClientTimeout(
                    total=None,
                    sock_connect=10,
                    sock_read=SSE_KEEPALIVE_TIMEOUT,
                ),
            ) as resp:
                if resp.status in (401, 403):
                    _LOGGER.debug("SSE auth failed, re-authenticating")
                    self.api.invalidate_token()
                    return

                if resp.status != 200:
                    _LOGGER.warning("SSE connection failed with status %s", resp.status)
                    return

                _LOGGER.debug("SSE connected to Navidrome")

                buffer = ""
                async for chunk in resp.content.iter_any():
                    buffer += chunk.decode("utf-8", errors="replace").replace("\r\n", "\n")
                    while "\n\n" in buffer:
                        event_block, buffer = buffer.split("\n\n", 1)
                        await self._handle_sse_block(event_block)
        except (aiohttp.ClientError, TimeoutError):
            raise
        finally:
            if self._sse_session and not self._sse_session.closed:
                await self._sse_session.close()
                self._sse_session = None

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

        try:
            await self._process_event(event_type, data)
        except Exception:
            _LOGGER.debug("Error processing SSE event %s", event_type, exc_info=True)

    async def _process_event(self, event_type: str, data):
        if event_type == "nowPlayingCount":
            await self.async_request_refresh()
        elif event_type == "scanStatus":
            if isinstance(data, dict) and not data.get("scanning", True):
                await self._refresh_library()
            await self.async_request_refresh()
        elif event_type == "refreshResource":
            scanning = (
                self.data
                and self.data.get("scan_status", {}).get("scanning", False)
            )
            if not scanning:
                await self._refresh_library()
                await self.async_request_refresh()
