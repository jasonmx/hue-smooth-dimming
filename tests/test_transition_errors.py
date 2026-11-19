import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.hue_dimmer.const import DIR_UP
from custom_components.hue_dimmer.services import _handle_get_attributes, _handle_stop, _handle_transition
from custom_components.hue_dimmer.transitions import _brightness_cache
from tests.conftest import make_service_call

ENTITY_ID = "light.kitchen"
RESOURCE_ID = "abc-123"
NOW = 1_000_000.0


def patch_targets(bridge, resource_type="light"):
    async def _targets(hass, call):
        yield ENTITY_ID, bridge, resource_type, RESOURCE_ID

    return patch("custom_components.hue_dimmer.services._iter_targets", _targets)


@pytest.mark.asyncio
async def test_failed_transition_warns_and_leaves_cache_empty(mock_hass, caplog):
    bridge = MagicMock()
    bridge.api.lights.set_state = AsyncMock(side_effect=Exception("bridge unreachable"))

    with patch_targets(bridge), caplog.at_level(logging.WARNING):
        await _handle_transition(mock_hass, make_service_call({"sweep_time": 5}), DIR_UP, 100.0)

    assert ENTITY_ID not in _brightness_cache
    assert "Transition command failed for light.kitchen" in caplog.text


@pytest.mark.asyncio
async def test_successful_transition_is_cached(mock_hass):
    bridge = MagicMock()
    bridge.api.lights.set_state = AsyncMock()

    with patch_targets(bridge):
        await _handle_transition(mock_hass, make_service_call({"sweep_time": 5}), DIR_UP, 100.0)

    assert _brightness_cache[ENTITY_ID]["dir"] == DIR_UP
    assert _brightness_cache[ENTITY_ID]["target"] == 100.0


@pytest.mark.asyncio
async def test_group_get_attributes_predicts_mid_transition(mock_hass):
    # The bridge reports the end value instantly; get_attributes must report the predicted brightness.
    mock_hass.states.get.return_value.attributes = {"brightness": 255}
    bridge = MagicMock()
    member = MagicMock(color=None, color_temperature=None)
    member.dimming.brightness = 100.0
    bridge.api.groups.grouped_light.get_lights.return_value = [member]
    _brightness_cache[ENTITY_ID] = {"time": NOW, "bright": 20.0, "target": 100.0, "dir": DIR_UP, "sweep": 10.0}

    with (
        patch_targets(bridge, "grouped_light"),
        patch("custom_components.hue_dimmer.transitions.time.time", return_value=NOW + 2),
    ):
        result = await _handle_get_attributes(mock_hass, make_service_call({}))

    assert result[ENTITY_ID]["brightness"] == 40.0  # 20% + 2s at 10%/s


@pytest.mark.asyncio
async def test_failed_stop_keeps_moving_prediction(mock_hass):
    # If the bridge rejects the stop, the light keeps moving, so the cache must keep predicting it.
    bridge = MagicMock()
    bridge.api.lights.set_dimming_delta = AsyncMock(side_effect=Exception("bridge unreachable"))
    moving = {"time": NOW, "bright": 20.0, "target": 100.0, "dir": DIR_UP, "sweep": 10.0}
    _brightness_cache[ENTITY_ID] = dict(moving)

    with patch_targets(bridge):
        await _handle_stop(mock_hass, make_service_call({}))

    assert _brightness_cache[ENTITY_ID] == moving
