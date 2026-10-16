"""Tests for service registration/unregistration and schemas."""

from unittest.mock import MagicMock

import pytest
import voluptuous as vol
from homeassistant.core import SupportsResponse

from custom_components.hue_dimmer import async_setup_entry, async_unload_entry
from custom_components.hue_dimmer.const import SERVICE_GET_ATTRIBUTES
from custom_components.hue_dimmer.services import SCHEMA_RAISE, SCHEMA_SET_ATTRIBUTES, SERVICES


@pytest.mark.asyncio
async def test_setup_registers_all_five_services():
    hass = MagicMock()
    entry = MagicMock()

    result = await async_setup_entry(hass, entry)

    assert result is True
    assert hass.services.async_register.call_count == len(SERVICES) == 5


@pytest.mark.asyncio
async def test_setup_registers_get_attributes_with_supports_response_only():
    hass = MagicMock()
    entry = MagicMock()

    await async_setup_entry(hass, entry)

    for call_args in hass.services.async_register.call_args_list:
        _args, kwargs = call_args
        # positional: domain, service_name, handler
        if call_args.args[1] == SERVICE_GET_ATTRIBUTES:
            assert kwargs.get("supports_response") == SupportsResponse.ONLY
            break
    else:
        pytest.fail("get_attributes was not registered")


@pytest.mark.asyncio
async def test_unload_removes_all_five_services():
    hass = MagicMock()
    entry = MagicMock()

    result = await async_unload_entry(hass, entry)

    assert result is True
    assert hass.services.async_remove.call_count == len(SERVICES) == 5


def test_schema_rejects_bad_sweep_time():
    """A non-numeric sweep_time that cannot be coerced to float should be rejected."""
    with pytest.raises(vol.Invalid):
        SCHEMA_RAISE({"entity_id": "light.test", "sweep_time": "not_a_number"})


def test_schema_accepts_zero_min_brightness():
    """0 is accepted by the schema; the handler converts it to None via _positive_or_none."""
    result = SCHEMA_SET_ATTRIBUTES({"entity_id": "light.test", "min_brightness": 0})
    assert result["min_brightness"] == 0.0
