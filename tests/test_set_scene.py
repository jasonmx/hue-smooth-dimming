import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

from custom_components.hue_dimmer.services import _handle_set_scene
from tests.conftest import make_service_call

SCENE_ID = "scene-123"
ENTITY_ID = "scene.living_room_relax"


def make_action(rid, on=None, brightness=None, xy=None, mirek=..., rtype="light"):
    # Mirrors aiohue's scene Action: target.rid/rtype (an Enum) + action features, None when absent.
    # mirek defaults to "no color_temperature feature"; pass None for a feature with mirek=None.
    action = SimpleNamespace(
        on=SimpleNamespace(on=on) if on is not None else None,
        dimming=SimpleNamespace(brightness=brightness) if brightness is not None else None,
        color=SimpleNamespace(xy=SimpleNamespace(x=xy[0], y=xy[1])) if xy is not None else None,
        color_temperature=SimpleNamespace(mirek=mirek) if mirek is not ... else None,
    )
    target = SimpleNamespace(rid=rid, rtype=SimpleNamespace(value=rtype))
    return SimpleNamespace(target=target, action=action)


def make_scene(*actions):
    return SimpleNamespace(actions=list(actions))


def setup_scene(bridge, scene, smart=False):
    bridge.api.scenes.smart_scene.get.return_value = MagicMock() if smart else None
    bridge.api.scenes.scene.get.return_value = scene


def patch_bridge(bridge):
    return patch(
        "custom_components.hue_dimmer.bridge._resolve_bridge",
        return_value=(bridge, SCENE_ID),
    )


async def run(mock_hass, mock_bridge, entity_ids=(ENTITY_ID,)):
    with patch_bridge(mock_bridge):
        await _handle_set_scene(mock_hass, make_service_call({"entity_id": list(entity_ids)}))


# ---------------------------------------------------------------------------
# Single-light mapping
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("action_kwargs, expected_kwargs", [
    pytest.param(
        {"brightness": 60.0, "mirek": 366},
        {"brightness": 60.0, "color_temp": 366, "color_xy": None},
        id="ct_only",
    ),
    pytest.param(
        {"brightness": 40.0, "xy": (0.5, 0.4)},
        {"brightness": 40.0, "color_temp": None, "color_xy": (0.5, 0.4)},
        id="xy_only",
    ),
    pytest.param(
        {"brightness": 25.0},
        {"brightness": 25.0, "color_temp": None, "color_xy": None},
        id="brightness_only",
    ),
    pytest.param(
        {"brightness": 50.0, "xy": (0.3, 0.3), "mirek": 250},
        {"brightness": 50.0, "color_temp": 250, "color_xy": (0.3, 0.3)},
        id="xy_and_ct_both_passed",
    ),
    pytest.param(
        {"on": True, "brightness": 80.0},
        {"brightness": 80.0, "color_temp": None, "color_xy": None},
        id="on_true_dropped",
    ),
    pytest.param(
        {"on": False, "brightness": 30.0, "mirek": 400},
        {"on": False, "brightness": 30.0, "color_temp": 400, "color_xy": None},
        id="on_false_sent_with_settings",
    ),
    pytest.param(
        {"brightness": 70.0, "xy": (0.4, 0.4), "mirek": None},
        {"brightness": 70.0, "color_temp": None, "color_xy": (0.4, 0.4)},
        id="mirek_none_not_sent",
    ),
])
@pytest.mark.asyncio
async def test_set_scene_single_light(mock_hass, mock_bridge, action_kwargs, expected_kwargs):
    setup_scene(mock_bridge, make_scene(make_action("light-1", **action_kwargs)))
    await run(mock_hass, mock_bridge)
    mock_bridge.api.lights.set_state.assert_called_once_with("light-1", **expected_kwargs)


# ---------------------------------------------------------------------------
# Multi-light and skipped actions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_multi_light_scene_writes_each_light(mock_hass, mock_bridge):
    setup_scene(mock_bridge, make_scene(
        make_action("light-1", brightness=20.0, mirek=450),
        make_action("light-2", brightness=90.0, xy=(0.6, 0.3)),
    ))
    await run(mock_hass, mock_bridge)
    assert mock_bridge.api.lights.set_state.call_args_list == [
        call("light-1", brightness=20.0, color_temp=450, color_xy=None),
        call("light-2", brightness=90.0, color_temp=None, color_xy=(0.6, 0.3)),
    ]


@pytest.mark.parametrize("action", [
    pytest.param(make_action("light-1", on=True), id="nothing_to_write"),
    pytest.param(make_action("light-1", mirek=None), id="only_null_mirek"),
    pytest.param(make_action("group-1", brightness=50.0, rtype="grouped_light"), id="non_light_rtype"),
])
@pytest.mark.asyncio
async def test_action_skipped(mock_hass, mock_bridge, action):
    setup_scene(mock_bridge, make_scene(action))
    await run(mock_hass, mock_bridge)
    mock_bridge.api.lights.set_state.assert_not_called()


# ---------------------------------------------------------------------------
# Unsupported or unknown scenes, non-scene targets
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_smart_scene_warns_and_writes_nothing(mock_hass, mock_bridge, caplog):
    setup_scene(mock_bridge, make_scene(make_action("light-1", brightness=50.0)), smart=True)
    with caplog.at_level(logging.WARNING):
        await run(mock_hass, mock_bridge)
    mock_bridge.api.lights.set_state.assert_not_called()
    assert "All-Day (smart) scenes" in caplog.text


@pytest.mark.asyncio
async def test_unknown_scene_writes_nothing(mock_hass, mock_bridge):
    setup_scene(mock_bridge, None)
    await run(mock_hass, mock_bridge)
    mock_bridge.api.lights.set_state.assert_not_called()


@pytest.mark.asyncio
async def test_non_scene_entity_ignored(mock_hass, mock_bridge):
    setup_scene(mock_bridge, make_scene(make_action("light-1", brightness=50.0)))
    with patch_bridge(mock_bridge) as resolve:
        await _handle_set_scene(mock_hass, make_service_call({"entity_id": ["light.kitchen"]}))
    resolve.assert_not_called()
    mock_bridge.api.lights.set_state.assert_not_called()


# ---------------------------------------------------------------------------
# Resilience and freshness
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_one_failing_light_does_not_stop_others(mock_hass, mock_bridge, caplog):
    setup_scene(mock_bridge, make_scene(
        make_action("light-1", brightness=20.0),
        make_action("light-2", brightness=40.0),
        make_action("light-3", brightness=60.0),
    ))
    mock_bridge.api.lights.set_state.side_effect = [None, RuntimeError("boom"), None]
    with caplog.at_level(logging.ERROR):
        await run(mock_hass, mock_bridge)
    assert [c.args[0] for c in mock_bridge.api.lights.set_state.call_args_list] == ["light-1", "light-2", "light-3"]
    assert "light-2" in caplog.text


@pytest.mark.asyncio
async def test_scene_reread_on_each_call(mock_hass, mock_bridge):
    scene = make_scene(make_action("light-1", brightness=20.0))
    setup_scene(mock_bridge, scene)
    await run(mock_hass, mock_bridge)

    scene.actions = [make_action("light-1", brightness=75.0)]
    await run(mock_hass, mock_bridge)

    assert mock_bridge.api.lights.set_state.call_args_list[-1] == call(
        "light-1", brightness=75.0, color_temp=None, color_xy=None
    )
