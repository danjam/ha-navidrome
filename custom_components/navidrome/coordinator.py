import asyncio
import codecs
import json
import logging
import time
from datetime import timedelta

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import NavidromeAPI, NavidromeAuthError, NavidromeError
from .const import (
    FALLBACK_POLL_INTERVAL,
    LIBRARY_MAX_AGE,
    LIBRARY_REFRESH_COOLDOWN,
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
        self._library_refreshed_at = 0.0
        self._library_debouncer = Debouncer(
            hass,
            _LOGGER,
            cooldown=LIBRARY_REFRESH_COOLDOWN,
            immediate=True,
            function=self._library_changed,
        )

    async def _async_update_data(self) -> dict:
        try:
            now_playing, scan_status, system = await asyncio.gather(
                self.api.get_now_playing(),
                self.api.get_scan_status(),
                self.api.get_system_info(),
            )

            # This also runs on every SSE-triggered refresh, so gate on age:
            # playlist edits emit no event and are picked up here.
            if (
                not self._library_data
                or time.monotonic() - self._library_refreshed_at > LIBRARY_MAX_AGE
            ):
                await self._refresh_library()

            return {
                "now_playing": now_playing,
                "scan_status": scan_status,
                "system": system,
                **self._library_data,
            }
        except NavidromeAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
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
        self._library_refreshed_at = time.monotonic()

    async def _library_changed(self):
        # Runs from the debouncer, which logs any exception as an ERROR with a
        # traceback; a transient server error here isn't worth that.
        try:
            await self._refresh_library()
        except NavidromeError as err:
            _LOGGER.debug("Library refresh failed: %s", err)
        await self.async_request_refresh()

    async def start_sse(self):
        if self._sse_task is None or self._sse_task.done():
            self._sse_task = asyncio.create_task(self._sse_loop())

    async def stop_sse(self):
        self._library_debouncer.async_shutdown()
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
            except NavidromeAuthError:
                try:
                    await self.api.authenticate()
                    _LOGGER.debug("SSE re-authenticated after token expiry")
                    delay = SSE_INITIAL_RECONNECT_DELAY
                    first_failure = True
                except NavidromeAuthError:
                    _LOGGER.warning("SSE credentials invalid, starting reauth")
                    self.config_entry.async_start_reauth(self.hass)
                    return
                except NavidromeError as err:
                    _LOGGER.debug("SSE re-auth failed (server unavailable): %s", err)
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
                f"{self.api.base_url}/api/events",
                headers=self.api.sse_headers,
                timeout=aiohttp.ClientTimeout(
                    total=None,
                    sock_connect=10,
                    sock_read=SSE_KEEPALIVE_TIMEOUT,
                ),
            ) as resp:
                if resp.status in (401, 403):
                    self.api.invalidate_token()
                    raise NavidromeAuthError("SSE authentication failed")

                if resp.status != 200:
                    raise NavidromeError(f"SSE connection failed with status {resp.status}")

                _LOGGER.debug("SSE connected to Navidrome")

                decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
                buffer = ""
                async for chunk in resp.content.iter_any():
                    buffer += decoder.decode(chunk, final=False)
                    buffer = buffer.replace("\r\n", "\n")
                    while "\n\n" in buffer:
                        event_block, buffer = buffer.split("\n\n", 1)
                        await self._handle_sse_block(event_block)
        finally:
            if self._sse_session and not self._sse_session.closed:
                await self._sse_session.close()
                self._sse_session = None

    async def _handle_sse_block(self, block: str):
        event_type = None
        data_lines = []

        for line in block.split("\n"):
            line = line.rstrip("\r")
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
        if event_type in ("nowPlayingCount", "serverStart"):
            # serverStart is sent on every new SSE subscription, so a
            # reconnect after a Navidrome restart resyncs immediately.
            await self.async_request_refresh()
        elif event_type == "scanStatus":
            # Refresh scan state now; the library refresh may be held by the
            # debouncer's cooldown.
            await self.async_request_refresh()
            if isinstance(data, dict) and not data.get("scanning", True):
                await self._library_debouncer.async_call()
        elif event_type == "refreshResource":
            # Payload maps resource type to ids. Scrobbles and annotations send
            # song/album/artist, which don't change library totals; only a
            # scan ("*") or library change does.
            if not isinstance(data, dict) or not ({"*", "library"} & data.keys()):
                return
            scanning = (
                self.data
                and self.data.get("scan_status", {}).get("scanning", False)
            )
            if not scanning:
                await self._library_debouncer.async_call()
