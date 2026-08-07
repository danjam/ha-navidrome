from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .api import NavidromeAPI
from .const import CONF_PASSWORD, CONF_URL, CONF_USERNAME, DOMAIN, PLATFORMS
from .coordinator import NavidromeCoordinator


async def async_setup(hass: HomeAssistant, config: dict):
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    hass.data.setdefault(DOMAIN, {})

    api = NavidromeAPI(
        entry.data[CONF_URL],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )

    await api.authenticate()

    coordinator = NavidromeCoordinator(hass, api, entry.entry_id)
    await coordinator.async_config_entry_first_refresh()
    await coordinator.start_sse()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    await coordinator.stop_sse()
    await coordinator.api.close()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
