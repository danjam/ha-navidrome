import hashlib

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([NavidromeMediaPlayer(coordinator, entry)])


class NavidromeMediaPlayer(CoordinatorEntity, MediaPlayerEntity):
    _attr_has_entity_name = True
    _attr_name = "Now Playing"
    _attr_supported_features = MediaPlayerEntityFeature(0)

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_media_player"
        self._cached_cover_url: str | None = None
        self._cached_cover_id: str | None = None

    @property
    def state(self):
        track = self._get_current_track()
        if not track:
            return MediaPlayerState.IDLE
        return MediaPlayerState.PLAYING

    @property
    def device_info(self):
        system = (
            self.coordinator.data.get("system", {})
            if self.coordinator.data
            else {}
        )
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "Navidrome",
            "manufacturer": "Navidrome",
            "model": "Music Server",
            "sw_version": system.get("serverVersion"),
            "configuration_url": self.coordinator.api.base_url,
        }

    def _get_current_track(self):
        data = self.coordinator.data
        if not data:
            return None
        tracks = data.get("now_playing")
        if not tracks:
            return None
        return tracks[0]

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
        return None

    @property
    def media_position_updated_at(self):
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
    def media_image_url(self):
        cover_id = self._get("coverArt")
        if not cover_id:
            self._cached_cover_url = None
            self._cached_cover_id = None
            return None

        if cover_id != self._cached_cover_id:
            self._cached_cover_url = self.coordinator.api.get_cover_art_url(cover_id)
            self._cached_cover_id = cover_id

        return self._cached_cover_url

    @property
    def media_image_hash(self):
        cover_id = self._get("coverArt")
        if not cover_id:
            return None
        return hashlib.sha1(cover_id.encode()).hexdigest()[:8]

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
        }
        return {k: v for k, v in attrs.items() if v is not None}
