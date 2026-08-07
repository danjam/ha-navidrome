from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            NavidromeScanStatusSensor(coordinator, entry),
            NavidromeLastScanSensor(coordinator, entry),
            NavidromeTotalGenresSensor(coordinator, entry),
            NavidromeTotalArtistsSensor(coordinator, entry),
            NavidromeTotalSongsSensor(coordinator, entry),
            NavidromeTotalPlaylistsSensor(coordinator, entry),
        ]
    )


class BaseNavidromeSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry = entry

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


class NavidromeScanStatusSensor(BaseNavidromeSensor):
    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_has_entity_name = True
        self._attr_translation_key = "scan_status"
        self._attr_unique_id = f"{entry.entry_id}_scan_status"
        self._attr_device_class = SensorDeviceClass.ENUM
        self._attr_options = ["scanning", "idle"]

    @property
    def native_value(self):
        data = self.coordinator.data
        if not data:
            return None
        scan = data.get("scan_status")
        if not scan:
            return None
        return "scanning" if scan.get("scanning") else "idle"


class NavidromeLastScanSensor(BaseNavidromeSensor):
    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_has_entity_name = True
        self._attr_translation_key = "last_scan"
        self._attr_unique_id = f"{entry.entry_id}_last_scan"
        self._attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self):
        data = self.coordinator.data
        if not data:
            return None
        scan = data.get("scan_status")
        if not scan:
            return None
        last_scan = scan.get("lastScan")
        if not last_scan:
            return None
        return dt_util.parse_datetime(last_scan)


class NavidromeTotalGenresSensor(BaseNavidromeSensor):
    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_has_entity_name = True
        self._attr_translation_key = "total_genres"
        self._attr_unique_id = f"{entry.entry_id}_total_genres"
        self._attr_icon = "mdi:music"

    @property
    def native_value(self):
        data = self.coordinator.data
        if not data:
            return 0
        return len(data.get("genres", []))


class NavidromeTotalArtistsSensor(BaseNavidromeSensor):
    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_has_entity_name = True
        self._attr_translation_key = "total_artists"
        self._attr_unique_id = f"{entry.entry_id}_total_artists"
        self._attr_icon = "mdi:account-music"

    @property
    def native_value(self):
        data = self.coordinator.data
        if not data:
            return 0
        indexes = data.get("artists", [])
        return sum(len(index.get("artist", [])) for index in indexes)


class NavidromeTotalSongsSensor(BaseNavidromeSensor):
    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_has_entity_name = True
        self._attr_translation_key = "total_songs"
        self._attr_unique_id = f"{entry.entry_id}_total_songs"
        self._attr_icon = "mdi:music"

    @property
    def native_value(self):
        data = self.coordinator.data
        if not data:
            return 0
        genres = data.get("genres", [])
        return sum(g.get("songCount", 0) for g in genres)


class NavidromeTotalPlaylistsSensor(BaseNavidromeSensor):
    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_has_entity_name = True
        self._attr_translation_key = "total_playlists"
        self._attr_unique_id = f"{entry.entry_id}_total_playlists"
        self._attr_icon = "mdi:playlist-music"

    @property
    def native_value(self):
        data = self.coordinator.data
        if not data:
            return 0
        return len(data.get("playlists", []))
