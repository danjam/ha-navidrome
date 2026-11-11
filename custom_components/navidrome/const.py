from homeassistant.const import Platform

DOMAIN = "navidrome"

PLATFORMS = [Platform.MEDIA_PLAYER, Platform.SENSOR, Platform.BUTTON]

FALLBACK_POLL_INTERVAL = 300
# Library (genres/artists/playlists) is refetched at most this often by the
# poll, and change bursts from SSE are coalesced over the debounce cooldown.
LIBRARY_MAX_AGE = 270  # under the 300s poll, which can fire slightly early
LIBRARY_REFRESH_COOLDOWN = 30
SSE_INITIAL_RECONNECT_DELAY = 5
SSE_MAX_RECONNECT_DELAY = 60
SSE_KEEPALIVE_TIMEOUT = 90
STALE_PLAYBACK_BUFFER = 120
