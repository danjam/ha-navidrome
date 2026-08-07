import logging

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import NavidromeAPI, NavidromeAuthError, NavidromeError
from .const import DOMAIN, PLATFORMS
from .coordinator import NavidromeCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    hass.data.setdefault(DOMAIN, {})

    session = async_get_clientsession(hass)
    api = NavidromeAPI(
        entry.data["url"],
        entry.data["username"],
        entry.data["password"],
        session,
    )

    try:
        await api.authenticate()
    except NavidromeAuthError as err:
        raise ConfigEntryAuthFailed(err) from err
    except (NavidromeError, aiohttp.ClientError, TimeoutError) as err:
        raise ConfigEntryNotReady(err) from err

    coordinator = NavidromeCoordinator(hass, api, entry)
    await coordinator.async_config_entry_first_refresh()
    await coordinator.start_sse()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.stop_sse()

    return unload_ok
