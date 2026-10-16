"""Smoke test: load the integration in a real hass and verify service wiring.

Requires pytest-homeassistant-custom-component; the module is skipped automatically
when that package is not installed.
"""

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.core import HomeAssistant  # noqa: E402
from homeassistant.exceptions import ServiceValidationError  # noqa: E402

from custom_components.hue_dimmer import async_setup  # noqa: E402
from custom_components.hue_dimmer.const import DOMAIN  # noqa: E402


async def test_five_services_registered(hass: HomeAssistant) -> None:
    """All five services are registered after async_setup."""
    result = await async_setup(hass, {})
    assert result is True
    services = hass.services.async_services_for_domain(DOMAIN)
    assert len(services) == 5


async def test_service_call_before_entry_raises_not_loaded(hass: HomeAssistant) -> None:
    """A service call before the config entry loads must raise ServiceValidationError."""
    await async_setup(hass, {})
    with pytest.raises(ServiceValidationError) as exc_info:
        await hass.services.async_call(
            DOMAIN,
            "raise",
            service_data={},
            target={"entity_id": "light.test"},
            blocking=True,
        )
    assert exc_info.value.translation_key == "not_loaded"
