import voluptuous as vol

from homeassistant import config_entries

from .api import NavidromeAPI, NavidromeAuthError, NavidromeError
from .const import CONF_PASSWORD, CONF_URL, CONF_USERNAME, DOMAIN


class NavidromeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}

        if user_input is not None:
            url = user_input[CONF_URL].rstrip("/")
            await self.async_set_unique_id(url)
            self._abort_if_unique_id_configured()

            api = NavidromeAPI(url, user_input[CONF_USERNAME], user_input[CONF_PASSWORD])

            try:
                await api.authenticate()
            except NavidromeAuthError:
                errors["base"] = "invalid_auth"
            except (NavidromeError, Exception):
                errors["base"] = "cannot_connect"
            finally:
                await api.close()

            if not errors:
                return self.async_create_entry(
                    title=url.split("//", 1)[-1],
                    data=user_input,
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_URL): str,
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )
