from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import custom_components.hue_dimmer.transitions as hue_mod


@pytest.fixture
def mock_bridge():
    bridge = MagicMock()
    bridge.api.lights.set_state = AsyncMock()
    bridge.api.lights.set_dimming_delta = AsyncMock()
    bridge.api.groups.grouped_light.set_dimming_delta = AsyncMock()
    bridge.api.groups.grouped_light.get_lights.return_value = []
    return bridge


@pytest.fixture
def mock_hass():
    return MagicMock()


@pytest.fixture(autouse=True)
def patch_extract_entity_ids():
    async def _extract(call):
        return set(call.data.get("entity_id", []))

    with patch(
        "custom_components.hue_dimmer.bridge.async_extract_entity_ids",
        side_effect=_extract,
    ):
        yield


@pytest.fixture(autouse=True)
def clear_brightness_cache():
    hue_mod._brightness_cache.clear()
    yield
    hue_mod._brightness_cache.clear()


def make_service_call(data):
    call = MagicMock()
    call.data = data
    return call


def make_entity_state(
    supported_color_modes=None,
    min_color_temp_kelvin=None,
    max_color_temp_kelvin=None,
):
    state = MagicMock()
    attrs = {}
    if supported_color_modes is not None:
        attrs["supported_color_modes"] = supported_color_modes
    if min_color_temp_kelvin is not None:
        attrs["min_color_temp_kelvin"] = min_color_temp_kelvin
    if max_color_temp_kelvin is not None:
        attrs["max_color_temp_kelvin"] = max_color_temp_kelvin
    state.attributes = attrs
    return state


def make_lights(*ids):
    lights = []
    for lid in ids:
        m = MagicMock()
        m.id = lid
        lights.append(m)
    return lights
