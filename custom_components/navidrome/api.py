import logging

import aiohttp

_LOGGER = logging.getLogger(__name__)


class NavidromeError(Exception):
    pass


class NavidromeAuthError(NavidromeError):
    pass


class NavidromeAPI:
    def __init__(self, base_url: str, username: str, password: str):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self._password = password
        self._token: str | None = None
        self._subsonic_salt: str | None = None
        self._subsonic_token: str | None = None
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def authenticate(self):
        session = await self._get_session()
        async with session.post(
            f"{self.base_url}/auth/login",
            json={"username": self.username, "password": self._password},
        ) as resp:
            if resp.status == 401:
                raise NavidromeAuthError("Invalid username or password")
            if resp.status != 200:
                raise NavidromeError(f"Auth failed with status {resp.status}")
            data = await resp.json()

        self._token = data.get("token")
        self._subsonic_salt = data.get("subsonicSalt")
        self._subsonic_token = data.get("subsonicToken")

        if not self._token:
            raise NavidromeAuthError("No token in auth response")

    def _update_token(self, resp_headers):
        new_token = resp_headers.get("x-nd-authorization")
        if new_token and new_token.startswith("Bearer "):
            self._token = new_token[7:]

    async def _ensure_auth(self):
        if not self._token:
            await self.authenticate()

    async def _native_request(self, method: str, endpoint: str, **kwargs):
        await self._ensure_auth()
        session = await self._get_session()
        headers = {"x-nd-authorization": f"Bearer {self._token}"}

        async with session.request(
            method, f"{self.base_url}/api/{endpoint}", headers=headers, **kwargs
        ) as resp:
            self._update_token(resp.headers)
            if resp.status == 401:
                await self.authenticate()
                headers["x-nd-authorization"] = f"Bearer {self._token}"
                async with session.request(
                    method,
                    f"{self.base_url}/api/{endpoint}",
                    headers=headers,
                    **kwargs,
                ) as retry_resp:
                    self._update_token(retry_resp.headers)
                    retry_resp.raise_for_status()
                    return await retry_resp.json()
            resp.raise_for_status()
            return await resp.json()

    async def _subsonic_request(self, endpoint: str, params: dict | None = None):
        await self._ensure_auth()
        session = await self._get_session()

        base_params = {
            "u": self.username,
            "s": self._subsonic_salt,
            "t": self._subsonic_token,
            "v": "1.16.1",
            "c": "ha-navidrome",
            "f": "json",
        }
        if params:
            base_params.update(params)

        async with session.get(
            f"{self.base_url}/rest/{endpoint}",
            params=base_params,
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()

        subsonic_resp = data.get("subsonic-response", {})
        if subsonic_resp.get("status") != "ok":
            error = subsonic_resp.get("error", {})
            code = error.get("code", 0)
            msg = error.get("message", "Unknown error")
            if code in (40, 41, 44):
                self._token = None
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
        return (
            f"{self.base_url}/rest/getCoverArt.view"
            f"?id={cover_id}"
            f"&u={self.username}"
            f"&s={self._subsonic_salt}"
            f"&t={self._subsonic_token}"
            f"&v=1.16.1"
            f"&c=ha-navidrome"
        )

    @property
    def sse_url(self) -> str:
        return f"{self.base_url}/events?jwt={self._token}"
