"""Tests for core logic: resolve_brightness, _handle_transition, _handle_stop,
and the min/max clamping path in _handle_set_attributes.

All tests use patched time.time — no real sleeps, no network.
"""
from unittest.mock import MagicMock, patch

import pytest

import custom_components.hue_dimmer.transitions as hue_mod
from custom_components.hue_dimmer.const import (
    DIR_DOWN,
    DIR_NONE,
    DIR_UP,
)
from custom_components.hue_dimmer.services import (
    _handle_set_attributes,
    _handle_stop,
    _handle_transition,
)
from custom_components.hue_dimmer.transitions import resolve_brightness
from tests.conftest import make_service_call

ENTITY_ID = "light.test_light"
RESOURCE_ID = "res-001"


def _hass_with_brightness(pct):
    """Return a mock hass whose entity reports `pct` percent brightness (Hue scale 0-100)."""
    hass = MagicMock()
    state = MagicMock()
    state.attributes = {"brightness": pct * 255 / 100}
    hass.states.get.return_value = state
    return hass


def _patch_resolve(bridge, resource_type="light"):
    return patch(
        "custom_components.hue_dimmer.bridge.resolve_entity",
        return_value=(bridge, resource_type, RESOURCE_ID),
    )


# ---------------------------------------------------------------------------
# resolve_brightness
# ---------------------------------------------------------------------------

def test_resolve_brightness_no_cache():
    hass = _hass_with_brightness(60.0)
    result = resolve_brightness(hass, ENTITY_ID)
    assert result == pytest.approx(60.0, abs=0.1)


@pytest.mark.parametrize("cache_entry, elapsed, ha_brightness, expected, pruned", [
    pytest.param(
        {"bright": 30.0, "target": 100.0, "dir": DIR_UP, "sweep": 10.0},
        5.0, 80.0, 80.0, False,
        id="moving_up_extrapolates",
    ),
    pytest.param(
        {"bright": 70.0, "target": 20.0, "dir": DIR_DOWN, "sweep": 10.0},
        5.0, 20.0, 20.0, False,
        id="moving_down_extrapolates",
    ),
    pytest.param(
        {"bright": 90.0, "target": 100.0, "dir": DIR_UP, "sweep": 5.0},
        10.0, 80.0, 100.0, False,
        id="moving_up_capped_at_target",
    ),
    pytest.param(
        {"bright": 42.0, "target": 42.0, "dir": DIR_NONE, "sweep": 1.0},
        5.0, 80.0, 42.0, False,
        id="stopped_within_guard",
    ),
    pytest.param(
        {"bright": 30.0, "target": 100.0, "dir": DIR_UP, "sweep": 5.0},
        21.0, 70.0, 70.0, True,
        id="guard_expired_moving_prunes_and_returns_reported",
    ),
    pytest.param(
        {"bright": 42.0, "target": 42.0, "dir": DIR_NONE, "sweep": 1.0},
        16.0, 70.0, 70.0, True,
        id="guard_expired_stopped_prunes_and_returns_reported",
    ),
])
def test_resolve_brightness_with_cache(cache_entry, elapsed, ha_brightness, expected, pruned):
    t_start = 1000.0
    cache_entry["time"] = t_start
    hue_mod._brightness_cache[ENTITY_ID] = cache_entry
    hass = _hass_with_brightness(ha_brightness)
    with patch("custom_components.hue_dimmer.transitions.time.time", return_value=t_start + elapsed):
        result = resolve_brightness(hass, ENTITY_ID)
    assert result == pytest.approx(expected, abs=0.1)
    if pruned:
        assert ENTITY_ID not in hue_mod._brightness_cache
    else:
        assert ENTITY_ID in hue_mod._brightness_cache


# ---------------------------------------------------------------------------
# _handle_transition
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_transition_dur_ms(mock_bridge):
    # current=50%, limit=100%, sweep=5 → distance=50, dur_ms = int(50*5*10) = 2500
    hass = _hass_with_brightness(50.0)
    call = make_service_call({"entity_id": [ENTITY_ID], "sweep_time": 5, "limit": 100.0})
    with _patch_resolve(mock_bridge):
        await _handle_transition(hass, call, DIR_UP, 100.0)
    mock_bridge.api.lights.set_state.assert_called_once()
    assert mock_bridge.api.lights.set_state.call_args.kwargs["transition_time"] == 2500


@pytest.mark.asyncio
async def test_handle_transition_no_command_when_distance_below_04(mock_bridge):
    # distance = |100 - 99.9| = 0.1 < 0.4 → no command
    hass = _hass_with_brightness(99.9)
    call = make_service_call({"entity_id": [ENTITY_ID]})
    with _patch_resolve(mock_bridge):
        await _handle_transition(hass, call, DIR_UP, 100.0)
    mock_bridge.api.lights.set_state.assert_not_called()


@pytest.mark.parametrize("direction, limit, expected_on", [
    pytest.param(DIR_UP, 100.0, True, id="raise_sends_on_true"),
    pytest.param(DIR_DOWN, 0.0, False, id="lower_to_zero_sends_on_false"),
    pytest.param(DIR_DOWN, 20.0, None, id="lower_to_positive_sends_on_none"),
])
@pytest.mark.asyncio
async def test_handle_transition_on_flag(mock_bridge, direction, limit, expected_on):
    hass = _hass_with_brightness(50.0)
    call = make_service_call({"entity_id": [ENTITY_ID], "limit": limit})
    with _patch_resolve(mock_bridge):
        await _handle_transition(hass, call, direction, limit)
    assert mock_bridge.api.lights.set_state.call_args.kwargs["on"] is expected_on


@pytest.mark.asyncio
async def test_handle_transition_sweep_time_clamped_to_01(mock_bridge):
    # sweep_time=0 → clamped to 0.1; distance=50%, dur_ms = int(50 * 0.1 * 10) = 50
    hass = _hass_with_brightness(50.0)
    call = make_service_call({"entity_id": [ENTITY_ID], "sweep_time": 0})
    with _patch_resolve(mock_bridge):
        await _handle_transition(hass, call, DIR_UP, 100.0)
    assert mock_bridge.api.lights.set_state.call_args.kwargs["transition_time"] == 50


# ---------------------------------------------------------------------------
# _handle_stop
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_stop_calls_set_dimming_delta(mock_bridge):
    hass = _hass_with_brightness(0.0)
    call = make_service_call({"entity_id": [ENTITY_ID]})
    with _patch_resolve(mock_bridge):
        await _handle_stop(hass, call)
    mock_bridge.api.lights.set_dimming_delta.assert_called_once_with(RESOURCE_ID)


@pytest.mark.asyncio
async def test_handle_stop_caches_stopped_entry_at_current_brightness(mock_bridge):
    hass = _hass_with_brightness(42.0)
    call = make_service_call({"entity_id": [ENTITY_ID]})
    t_now = 1000.0
    with _patch_resolve(mock_bridge):
        with patch("custom_components.hue_dimmer.transitions.time.time", return_value=t_now):
            await _handle_stop(hass, call)
    cached = hue_mod._brightness_cache.get(ENTITY_ID)
    assert cached is not None
    assert cached["dir"] == DIR_NONE
    assert cached["bright"] == pytest.approx(42.0, abs=0.1)
    assert cached["time"] == t_now


# ---------------------------------------------------------------------------
# _handle_set_attributes — min/max brightness clamping
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_set_attributes_raises_below_min_brightness(mock_bridge):
    # current=20%, min=40% → sends brightness=40%
    hass = _hass_with_brightness(20.0)
    call = make_service_call({"entity_id": [ENTITY_ID], "min_brightness": 40.0})
    with _patch_resolve(mock_bridge):
        await _handle_set_attributes(hass, call)
    mock_bridge.api.lights.set_state.assert_called_once()
    assert mock_bridge.api.lights.set_state.call_args.kwargs["brightness"] == pytest.approx(40.0, abs=0.1)


@pytest.mark.asyncio
async def test_set_attributes_lowers_above_max_brightness(mock_bridge):
    # current=80%, max=60% → sends brightness=60%
    hass = _hass_with_brightness(80.0)
    call = make_service_call({"entity_id": [ENTITY_ID], "max_brightness": 60.0})
    with _patch_resolve(mock_bridge):
        await _handle_set_attributes(hass, call)
    mock_bridge.api.lights.set_state.assert_called_once()
    assert mock_bridge.api.lights.set_state.call_args.kwargs["brightness"] == pytest.approx(60.0, abs=0.1)


@pytest.mark.asyncio
async def test_set_attributes_no_command_when_within_range(mock_bridge):
    # current=50%, min=30%, max=70% → no adjustment needed
    hass = _hass_with_brightness(50.0)
    call = make_service_call({"entity_id": [ENTITY_ID], "min_brightness": 30.0, "max_brightness": 70.0})
    with _patch_resolve(mock_bridge):
        await _handle_set_attributes(hass, call)
    mock_bridge.api.lights.set_state.assert_not_called()
