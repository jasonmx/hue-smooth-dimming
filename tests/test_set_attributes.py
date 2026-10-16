from unittest.mock import patch

import pytest
from homeassistant.util.color import color_hs_to_xy, color_RGB_to_xy

from custom_components.hue_dimmer import _handle_set_attributes
from tests.conftest import make_entity_state, make_lights, make_service_call

RESOURCE_ID = "abc-123"
ENTITY_ID = "light.kitchen"

# Pre-computed expected XY values for color tests
_XY_FROM_HS = color_hs_to_xy(30.0, 80.0)
_XY_FROM_RGB = color_RGB_to_xy(255, 128, 0)


def patch_bridge(bridge, resource_type="light"):
    return patch(
        "custom_components.hue_dimmer.resolve_entity",
        return_value=(bridge, resource_type, RESOURCE_ID),
    )


# ---------------------------------------------------------------------------
# Single-entity tests — parametrized by call data, entity state, expected kwargs
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("call_data, state_kwargs, expected_kwargs", [
    pytest.param(
        {"brightness": 42.5},
        None,
        {"brightness": 42.5, "color_temp": None, "color_xy": None},
        id="brightness_only",
    ),
    pytest.param(
        {"color_temp_kelvin": 3000},
        {"supported_color_modes": ["color_temp"], "min_color_temp_kelvin": 2202, "max_color_temp_kelvin": 6535},
        {"brightness": None, "color_temp": 333, "color_xy": None},
        id="ct_only_on_ct_light",
    ),
    pytest.param(
        {"brightness": 75, "color_temp_kelvin": 4000},
        {"supported_color_modes": ["color_temp"], "min_color_temp_kelvin": 2202, "max_color_temp_kelvin": 6535},
        {"brightness": 75.0, "color_temp": 250, "color_xy": None},
        id="brightness_and_ct",
    ),
    pytest.param(
        {"brightness": 50, "color_temp_kelvin": 3000},
        {"supported_color_modes": ["brightness"]},
        {"brightness": 50.0, "color_temp": None, "color_xy": None},
        id="ct_on_non_ct_light_brightness_still_sent",
    ),
    pytest.param(
        {"color_temp_kelvin": 1000},
        {"supported_color_modes": ["color_temp"], "min_color_temp_kelvin": 2202, "max_color_temp_kelvin": 6535},
        {"brightness": None, "color_temp": 454, "color_xy": None},
        id="ct_clamped_to_min",
    ),
    pytest.param(
        {"color_temp_kelvin": 9000},
        {"supported_color_modes": ["color_temp"], "min_color_temp_kelvin": 2202, "max_color_temp_kelvin": 6535},
        {"brightness": None, "color_temp": 153, "color_xy": None},
        id="ct_clamped_to_max",
    ),
    pytest.param(
        {"xy_color": [0.369, 0.445]},
        {"supported_color_modes": ["xy"]},
        {"brightness": None, "color_temp": None, "color_xy": (0.369, 0.445)},
        id="xy_color_on_color_light",
    ),
    pytest.param(
        {"hs_color": [30, 80]},
        {"supported_color_modes": ["xy"]},
        {"brightness": None, "color_temp": None, "color_xy": _XY_FROM_HS},
        id="hs_color_on_color_light",
    ),
    pytest.param(
        {"rgb_color": [255, 128, 0]},
        {"supported_color_modes": ["xy"]},
        {"brightness": None, "color_temp": None, "color_xy": _XY_FROM_RGB},
        id="rgb_color_on_color_light",
    ),
    pytest.param(
        {"xy_color": [0.3, 0.3], "brightness": 50},
        {"supported_color_modes": ["brightness"]},
        {"brightness": 50.0, "color_temp": None, "color_xy": None},
        id="color_on_non_color_light_brightness_still_sent",
    ),
    pytest.param(
        {"rgb_color": [255, 128, 0], "hs_color": [30, 80], "xy_color": [0.3, 0.3]},
        {"supported_color_modes": ["xy"]},
        {"brightness": None, "color_temp": None, "color_xy": _XY_FROM_RGB},
        id="color_priority_rgb_wins",
    ),
    pytest.param(
        {"brightness": 60, "color_temp_kelvin": 3000, "xy_color": [0.4, 0.4]},
        {"supported_color_modes": ["color_temp", "xy"], "min_color_temp_kelvin": 2202, "max_color_temp_kelvin": 6535},
        {"brightness": 60.0, "color_temp": 333, "color_xy": (0.4, 0.4)},
        id="brightness_ct_and_color_together",
    ),
])
@pytest.mark.asyncio
async def test_set_attributes_single_entity(mock_hass, mock_bridge, call_data, state_kwargs, expected_kwargs):
    call = make_service_call({"entity_id": [ENTITY_ID], **call_data})
    if state_kwargs is not None:
        mock_hass.states.get.return_value = make_entity_state(**state_kwargs)
    with patch_bridge(mock_bridge):
        await _handle_set_attributes(mock_hass, call)
    mock_bridge.api.lights.set_state.assert_called_once_with(RESOURCE_ID, **expected_kwargs)


# ---------------------------------------------------------------------------
# No-call cases
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ct_only_on_non_ct_light(mock_hass, mock_bridge):
    call = make_service_call({"entity_id": [ENTITY_ID], "color_temp_kelvin": 3000})
    mock_hass.states.get.return_value = make_entity_state(supported_color_modes=["brightness"])
    with patch_bridge(mock_bridge):
        await _handle_set_attributes(mock_hass, call)
    mock_bridge.api.lights.set_state.assert_not_called()


@pytest.mark.asyncio
async def test_no_fields_provided(mock_hass, mock_bridge):
    call = make_service_call({"entity_id": [ENTITY_ID]})
    with patch_bridge(mock_bridge):
        await _handle_set_attributes(mock_hass, call)
    mock_bridge.api.lights.set_state.assert_not_called()


@pytest.mark.asyncio
async def test_color_on_non_color_light_skipped(mock_hass, mock_bridge):
    call = make_service_call({"entity_id": [ENTITY_ID], "xy_color": [0.3, 0.3]})
    mock_hass.states.get.return_value = make_entity_state(supported_color_modes=["color_temp"])
    with patch_bridge(mock_bridge):
        await _handle_set_attributes(mock_hass, call)
    mock_bridge.api.lights.set_state.assert_not_called()


# ---------------------------------------------------------------------------
# API error
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_api_error_handled(mock_hass, mock_bridge):
    call = make_service_call({"entity_id": [ENTITY_ID], "brightness": 50})
    mock_bridge.api.lights.set_state.side_effect = Exception("Connection refused")
    with patch_bridge(mock_bridge):
        await _handle_set_attributes(mock_hass, call)
    mock_bridge.api.lights.set_state.assert_called_once()


# ---------------------------------------------------------------------------
# Group tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_group_resolves_to_individual_lights(mock_hass, mock_bridge):
    call = make_service_call({"entity_id": [ENTITY_ID], "brightness": 80})
    mock_bridge.api.groups.grouped_light.get_lights.return_value = make_lights("light-1", "light-2")
    with patch_bridge(mock_bridge, resource_type="grouped_light"):
        await _handle_set_attributes(mock_hass, call)
    assert mock_bridge.api.lights.set_state.call_count == 2
    called_ids = {c.args[0] for c in mock_bridge.api.lights.set_state.call_args_list}
    assert called_ids == {"light-1", "light-2"}
    for c in mock_bridge.api.lights.set_state.call_args_list:
        assert c.kwargs["brightness"] == 80.0
        assert c.kwargs["color_temp"] is None
        assert c.kwargs["color_xy"] is None


@pytest.mark.asyncio
async def test_group_no_lights_found(mock_hass, mock_bridge):
    call = make_service_call({"entity_id": [ENTITY_ID], "brightness": 50})
    mock_bridge.api.groups.grouped_light.get_lights.return_value = []
    with patch_bridge(mock_bridge, resource_type="grouped_light"):
        await _handle_set_attributes(mock_hass, call)
    mock_bridge.api.lights.set_state.assert_not_called()


@pytest.mark.asyncio
async def test_color_in_group(mock_hass, mock_bridge):
    call = make_service_call({"entity_id": [ENTITY_ID], "xy_color": [0.369, 0.445]})
    mock_hass.states.get.return_value = make_entity_state(supported_color_modes=["xy"])
    mock_bridge.api.groups.grouped_light.get_lights.return_value = make_lights("light-1", "light-2")
    with patch_bridge(mock_bridge, resource_type="grouped_light"):
        await _handle_set_attributes(mock_hass, call)
    assert mock_bridge.api.lights.set_state.call_count == 2
    for c in mock_bridge.api.lights.set_state.call_args_list:
        assert c.kwargs["color_xy"] == (0.369, 0.445)
        assert c.kwargs["color_temp"] is None
        assert c.kwargs["brightness"] is None
