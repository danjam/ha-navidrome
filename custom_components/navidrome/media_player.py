import hashlib
from datetime import datetime, timezone

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, STALE_PLAYBACK_BUFFER

STATE_MAP = {
    "starting": MediaPlayerState.PLAYING,
    "playing": MediaPlayerState.PLAYING,
    "paused": MediaPlayerState.PAUSED,
    "stopped": None,
}


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([NavidromeMediaPlayer(coordinator, entry)])


class NavidromeMediaPlayer(CoordinatorEntity, MediaPlayerEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "now_playing"
    _attr_supported_features = MediaPlayerEntityFeature(0)

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_media_player"
        self._cover_cache = None

    @property
    def state(self):
        track = self._get_current_track()
        if not track:
            return MediaPlayerState.IDLE

        server_state = track.get("state")
        if server_state is not None:
            mapped = STATE_MAP.get(server_state)
            if mapped is None:
                return MediaPlayerState.IDLE
            return mapped

        return MediaPlayerState.PLAYING

    @property
    def device_info(self) -> DeviceInfo:
        system = (
            self.coordinator.data.get("system", {})
            if self.coordinator.data
            else {}
        )
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Navidrome",
            manufacturer="Navidrome",
            model="Music Server",
            sw_version=system.get("serverVersion"),
            configuration_url=self.coordinator.api.base_url,
        )

    def _get_current_track(self):
        data = self.coordinator.data
        if not data:
            return None
        tracks = data.get("now_playing")
        if not tracks:
            return None

        active = []
        for t in tracks:
            server_state = t.get("state")
            if server_state is not None:
                if server_state in ("starting", "playing", "paused"):
                    active.append(t)
            else:
                max_stale_minutes = 10
                minutes_ago = t.get("minutesAgo", 0)
                duration = t.get("duration", 0)
                if duration > 0:
                    if (minutes_ago * 60) <= (duration + STALE_PLAYBACK_BUFFER):
                        active.append(t)
                elif minutes_ago <= max_stale_minutes:
                    active.append(t)

        if not active:
            return None

        active.sort(key=lambda t: t.get("minutesAgo", 0))
        return active[0]

    def _get(self, key):
        track = self._get_current_track()
        if not track:
            return None
        return track.get(key)

    @property
    def media_title(self):
        return self._get("title")

    @property
    def media_artist(self):
        return self._get("displayArtist") or self._get("artist")

    @property
    def media_album_name(self):
        return self._get("album")

    @property
    def media_duration(self):
        return self._get("duration")

    @property
    def media_position(self):
        position_ms = self._get("positionMs")
        if position_ms is not None:
            return position_ms // 1000
        return None

    @property
    def media_position_updated_at(self):
        if self._get("positionMs") is not None and self.state == MediaPlayerState.PLAYING:
            return datetime.now(timezone.utc)
        return None

    @property
    def media_content_type(self):
        if self._get_current_track():
            return MediaType.MUSIC
        return None

    @property
    def media_content_id(self):
        return self._get("id")

    @property
    def media_image_hash(self):
        cover_id = self._get("coverArt")
        if not cover_id:
            return None
        return hashlib.sha1(cover_id.encode()).hexdigest()[:8]

    async def async_get_media_image(self):
        # Served directly (no media_image_url) so HA never holds the
        # token-bearing cover art URL. Keeps the last image to avoid refetching.
        cover_id = self._get("coverArt")
        if not cover_id:
            return None, None
        if self._cover_cache and self._cover_cache[0] == cover_id:
            return self._cover_cache[1]
        image = await self.coordinator.api.get_cover_art(cover_id)
        if image[0] is not None:
            self._cover_cache = (cover_id, image)
        return image

    @property
    def extra_state_attributes(self):
        track = self._get_current_track()
        if not track:
            return {}

        attrs = {
            "track_number": track.get("track"),
            "year": track.get("year"),
            "genre": track.get("genre"),
            "bitrate": track.get("bitRate"),
            "suffix": track.get("suffix"),
            "sampling_rate": track.get("samplingRate"),
            "channel_count": track.get("channelCount"),
            "player_name": track.get("playerName"),
            "username": track.get("username"),
            "playback_rate": track.get("playbackRate"),
        }
        return {k: v for k, v in attrs.items() if v is not None}
