import voluptuous as vol
from homeassistant import config_entries

from .const import DOMAIN


class HueDimmerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Philips Hue Smooth Dimmer."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step when the user clicks 'Add Integration'."""
        if user_input is not None:
            return self.async_create_entry(title="Philips Hue Smooth Dimmer", data={})

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({}),
        )
