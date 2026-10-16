"""Tests for service registration/unregistration and schemas."""

from unittest.mock import AsyncMock, MagicMock

import pytest
import voluptuous as vol
from homeassistant.core import SupportsResponse
from homeassistant.exceptions import ServiceValidationError

from custom_components.hue_dimmer import async_setup, async_setup_entry, async_unload_entry
from custom_components.hue_dimmer.const import SERVICE_GET_ATTRIBUTES
from custom_components.hue_dimmer.services import SCHEMA_RAISE, SCHEMA_SET_ATTRIBUTES, SERVICES, _call_if_loaded


@pytest.mark.asyncio
async def test_setup_registers_all_five_services():
    hass = MagicMock()

    result = await async_setup(hass, {})

    assert result is True
    assert hass.services.async_register.call_count == len(SERVICES) == 5


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
async def test_entry_setup_and_unload_leave_services_alone():
    hass = MagicMock()
    entry = MagicMock()

    assert await async_setup_entry(hass, entry) is True
    assert await async_unload_entry(hass, entry) is True

    hass.services.async_register.assert_not_called()
    hass.services.async_remove.assert_not_called()


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


def test_schema_rejects_bad_sweep_time():
    """A non-numeric sweep_time that cannot be coerced to float should be rejected."""
    with pytest.raises(vol.Invalid):
        SCHEMA_RAISE({"entity_id": "light.test", "sweep_time": "not_a_number"})


def test_schema_accepts_zero_min_brightness():
    """0 is accepted by the schema; the handler converts it to None via _positive_or_none."""
    result = SCHEMA_SET_ATTRIBUTES({"entity_id": "light.test", "min_brightness": 0})
    assert result["min_brightness"] == 0.0
