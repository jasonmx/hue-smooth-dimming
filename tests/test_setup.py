"""Tests for service registration/unregistration and schemas."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import SupportsResponse
from homeassistant.exceptions import ServiceValidationError

from custom_components.hue_dimmer import async_remove_entry, async_setup, async_setup_entry
from custom_components.hue_dimmer.const import (
    DEVICESIDE_INSTALL_URL,
    DEVICESIDE_URL,
    DOMAIN,
    ISSUE_REPLACED_BY_DEVICESIDE,
    LEGACY_NAMES,
    NAME,
    SERVICE_GET_ATTRIBUTES,
)
from custom_components.hue_dimmer.services import _call_if_loaded

IR = "custom_components.hue_dimmer.ir"


@pytest.mark.asyncio
async def test_setup_registers_get_attributes_with_supports_response_only():
    hass = MagicMock()

    await async_setup(hass, {})

    for call_args in hass.services.async_register.call_args_list:
        _args, kwargs = call_args
        # positional: domain, service_name, handler
        if call_args.args[1] == SERVICE_GET_ATTRIBUTES:
            assert kwargs.get("supports_response") == SupportsResponse.ONLY
            break
    else:
        pytest.fail("get_attributes was not registered")


@pytest.mark.asyncio
async def test_service_call_rejected_when_no_entry_loaded():
    hass = MagicMock()
    hass.config_entries.async_loaded_entries.return_value = []
    handler = AsyncMock()

    with pytest.raises(ServiceValidationError) as exc_info:
        await _call_if_loaded(handler, hass, MagicMock())

    assert exc_info.value.translation_key == "not_loaded"
    handler.assert_not_called()


@pytest.mark.asyncio
async def test_service_call_runs_when_entry_loaded():
    hass = MagicMock()
    hass.config_entries.async_loaded_entries.return_value = [MagicMock()]
    handler = AsyncMock(return_value={"ok": True})
    call = MagicMock()

    assert await _call_if_loaded(handler, hass, call) == {"ok": True}
    handler.assert_awaited_once_with(hass, call)


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy_title", LEGACY_NAMES)
async def test_setup_entry_migrates_legacy_title(legacy_title):
    hass = MagicMock()
    entry = MagicMock(title=legacy_title)

    with patch(f"{IR}.async_create_issue"):
        assert await async_setup_entry(hass, entry)
    hass.config_entries.async_update_entry.assert_called_once_with(entry, title=NAME)


@pytest.mark.asyncio
async def test_setup_entry_keeps_custom_title():
    hass = MagicMock()
    entry = MagicMock(title="My Dimmer")

    with patch(f"{IR}.async_create_issue"):
        assert await async_setup_entry(hass, entry)
    hass.config_entries.async_update_entry.assert_not_called()


@pytest.mark.asyncio
async def test_setup_entry_raises_replaced_by_deviceside_issue():
    hass = MagicMock()

    with patch(f"{IR}.async_create_issue") as create:
        assert await async_setup_entry(hass, MagicMock(title=NAME))

    create.assert_called_once()
    args, kwargs = create.call_args
    assert args == (hass, DOMAIN, ISSUE_REPLACED_BY_DEVICESIDE)
    assert kwargs["is_fixable"] is False
    assert kwargs["learn_more_url"] == DEVICESIDE_URL
    assert kwargs["severity"] == "warning"
    assert kwargs["translation_key"] == ISSUE_REPLACED_BY_DEVICESIDE
    assert kwargs["translation_placeholders"] == {"install_url": DEVICESIDE_INSTALL_URL}


@pytest.mark.asyncio
async def test_remove_entry_deletes_replaced_by_deviceside_issue():
    hass = MagicMock()

    with patch(f"{IR}.async_delete_issue") as delete:
        await async_remove_entry(hass, MagicMock())

    delete.assert_called_once_with(hass, DOMAIN, ISSUE_REPLACED_BY_DEVICESIDE)
