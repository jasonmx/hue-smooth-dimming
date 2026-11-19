from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.typing import ConfigType

from .const import (
    DEVICESIDE_INSTALL_URL,
    DEVICESIDE_URL,
    DOMAIN,
    ISSUE_REPLACED_BY_DEVICESIDE,
    LEGACY_NAMES,
    NAME,
)
from .services import async_setup_services

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType):
    # Services are registered once per HA run, not per entry; handlers refuse calls until the entry loads.
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    # Leave a title the user has renamed alone.
    if entry.title in LEGACY_NAMES:
        hass.config_entries.async_update_entry(entry, title=NAME)
    # Re-created on every start; HA keeps a user's Ignore across re-creation, so this is one notice, not a nag.
    ir.async_create_issue(
        hass,
        DOMAIN,
        ISSUE_REPLACED_BY_DEVICESIDE,
        is_fixable=False,
        is_persistent=False,
        learn_more_url=DEVICESIDE_URL,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_REPLACED_BY_DEVICESIDE,
        translation_placeholders={"install_url": DEVICESIDE_INSTALL_URL},
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry):
    ir.async_delete_issue(hass, DOMAIN, ISSUE_REPLACED_BY_DEVICESIDE)
