from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([NavidromeStartScanButton(coordinator, entry)])


class NavidromeStartScanButton(CoordinatorEntity, ButtonEntity):
    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_has_entity_name = True
        self._attr_translation_key = "start_scan"
        self._attr_unique_id = f"{entry.entry_id}_start_scan"
        self._attr_icon = "mdi:database-refresh"

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

    @property
    def available(self):
        if not self.coordinator.data:
            return False
        scan = self.coordinator.data.get("scan_status", {})
        return not scan.get("scanning", False)

    async def async_press(self):
        await self.coordinator.api.start_scan()
        await self.coordinator.async_request_refresh()
