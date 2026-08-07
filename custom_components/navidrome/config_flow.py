import logging

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import NavidromeAPI, NavidromeAuthError, NavidromeError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class NavidromeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}

        if user_input is not None:
            url = user_input["url"].rstrip("/")
            await self.async_set_unique_id(url.lower())
            self._abort_if_unique_id_configured()

            session = async_get_clientsession(self.hass)
            api = NavidromeAPI(url, user_input["username"], user_input["password"], session)

            try:
                await api.authenticate()
            except NavidromeAuthError:
                errors["base"] = "invalid_auth"
            except NavidromeError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during setup")
                errors["base"] = "unknown"

            if not errors:
                return self.async_create_entry(
                    title=url.split("//", 1)[-1],
                    data={**user_input, "url": url},
                )

        schema = vol.Schema(
            {
                vol.Required("url"): str,
                vol.Required("username"): str,
                vol.Required("password"): str,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_reauth(self, entry_data):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        errors = {}

        if user_input is not None:
            entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
            url = entry.data["url"]

            session = async_get_clientsession(self.hass)
            api = NavidromeAPI(url, user_input["username"], user_input["password"], session)

            try:
                await api.authenticate()
            except NavidromeAuthError:
                errors["base"] = "invalid_auth"
            except NavidromeError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during reauth")
                errors["base"] = "unknown"

            if not errors:
                self.hass.config_entries.async_update_entry(
                    entry,
                    data={**entry.data, **user_input},
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        schema = vol.Schema(
            {
                vol.Required("username"): str,
                vol.Required("password"): str,
            }
        )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=schema,
            errors=errors,
        )
