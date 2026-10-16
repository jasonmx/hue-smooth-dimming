import functools

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .services import SERVICES


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    for svc_name, (handler, schema, supports_resp) in SERVICES.items():
        hass.services.async_register(
            DOMAIN,
            svc_name,
            functools.partial(handler, hass),
            schema=schema,
            supports_response=supports_resp,
        )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    for svc_name in SERVICES:
        hass.services.async_remove(DOMAIN, svc_name)
    return True
