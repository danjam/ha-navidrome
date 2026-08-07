import asyncio
import hashlib
import logging
import secrets
import string
from urllib.parse import urlencode

import aiohttp

_LOGGER = logging.getLogger(__name__)


class NavidromeError(Exception):
    pass


class NavidromeAuthError(NavidromeError):
    pass


class NavidromeAPI:
    def __init__(self, base_url: str, username: str, password: str, session: aiohttp.ClientSession):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self._password = password
        self._session = session
        self._token: str | None = None
        self._auth_lock = asyncio.Lock()

    async def authenticate(self):
        async with self._auth_lock:
            if self._token:
                return

            try:
                async with self._session.post(
                    f"{self.base_url}/auth/login",
                    json={"username": self.username, "password": self._password},
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status == 401:
                        raise NavidromeAuthError("Invalid username or password")
                    if resp.status != 200:
                        raise NavidromeError(f"Auth failed with status {resp.status}")
                    data = await resp.json()
            except NavidromeError:
                raise
            except (aiohttp.ClientError, TimeoutError) as err:
                raise NavidromeError(f"Connection error: {err}") from err

            token = data.get("token")
            if not token:
                raise NavidromeAuthError("No token in auth response")

            self._token = token

    def invalidate_token(self):
        self._token = None

    async def _ensure_auth(self):
        if not self._token:
            await self.authenticate()

    def _subsonic_salt_token(self):
        alphabet = string.ascii_letters + string.digits
        salt = "".join(secrets.choice(alphabet) for _ in range(16))
        token = hashlib.md5((self._password + salt).encode()).hexdigest()
        return salt, token

    async def _subsonic_request(self, endpoint: str, params: dict | None = None):
        salt, token = self._subsonic_salt_token()

        base_params = {
            "u": self.username,
            "t": token,
            "s": salt,
            "v": "1.16.1",
            "c": "ha-navidrome",
            "f": "json",
        }
        if params:
            base_params.update(params)

        try:
            async with self._session.get(
                f"{self.base_url}/rest/{endpoint}",
                params=base_params,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise NavidromeError(f"Request failed: {err}") from err

        if not isinstance(data, dict):
            raise NavidromeError("Unexpected response format")

        subsonic_resp = data.get("subsonic-response", {})
        if subsonic_resp.get("status") != "ok":
            error = subsonic_resp.get("error", {})
            code = error.get("code", 0)
            msg = error.get("message", "Unknown error")
            if code in (40, 41, 44):
                raise NavidromeAuthError(msg)
            raise NavidromeError(f"API error {code}: {msg}")

        return subsonic_resp

    async def get_now_playing(self) -> list:
        data = await self._subsonic_request("getNowPlaying.view")
        return data.get("nowPlaying", {}).get("entry", [])

    async def get_scan_status(self) -> dict:
        data = await self._subsonic_request("getScanStatus.view")
        return data.get("scanStatus", {})

    async def get_system_info(self) -> dict:
        data = await self._subsonic_request("ping.view")
        return data

    async def start_scan(self):
        await self._subsonic_request("startScan.view")

    async def get_genres(self) -> list:
        data = await self._subsonic_request("getGenres.view")
        return data.get("genres", {}).get("genre", [])

    async def get_artists(self) -> list:
        data = await self._subsonic_request("getArtists.view")
        return data.get("artists", {}).get("index", [])

    async def get_playlists(self) -> list:
        data = await self._subsonic_request("getPlaylists.view")
        return data.get("playlists", {}).get("playlist", [])

    def get_cover_art_url(self, cover_id: str) -> str:
        salt, token = self._subsonic_salt_token()
        params = urlencode({
            "id": cover_id,
            "u": self.username,
            "t": token,
            "s": salt,
            "v": "1.16.1",
            "c": "ha-navidrome",
        })
        return f"{self.base_url}/rest/getCoverArt.view?{params}"

    @property
    def sse_headers(self) -> dict:
        return {"x-nd-authorization": f"Bearer {self._token}"}
