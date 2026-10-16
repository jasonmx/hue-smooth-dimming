import logging

from .bridge import _write_light

_LOGGER = logging.getLogger(__name__)


def _scene_light_writes(scene):
    # Maps a scene's actions to per-light _write_light kwargs. The Hue API has no stage-only
    # recall, so the scene is replayed as ordinary light writes, which work while lights are off.
    # `on: true` is dropped so no light turns on; `on: false` is sent, as a recall would.
    # Gradient, effects and dynamics are ignored, so dynamic scenes get their first frame.
    writes = []
    for scene_action in scene.actions:
        target = scene_action.target
        if getattr(target.rtype, "value", target.rtype) != "light":
            continue

        action = scene_action.action
        kwargs = {}
        if action.on is not None and action.on.on is False:
            kwargs["on"] = False
        if action.dimming is not None:
            kwargs["brightness"] = action.dimming.brightness
        if action.color is not None:
            kwargs["color_xy"] = (action.color.xy.x, action.color.xy.y)
        if action.color_temperature is not None and action.color_temperature.mirek is not None:
            kwargs["color_temp_mirek"] = action.color_temperature.mirek

        if kwargs:
            writes.append((target.rid, kwargs))
    return writes


async def _apply_scene(bridge, entity_id, scene_id):
    # Reads the scene from aiohue's live cache on every call, so edits in the Hue app apply.
    scenes = bridge.api.scenes
    if scenes.smart_scene.get(scene_id) is not None:
        _LOGGER.warning("set_scene doesn't support All-Day (smart) scenes yet: %s", entity_id)
        return

    scene = scenes.scene.get(scene_id)
    if scene is None:
        _LOGGER.warning("Hue scene %s not found on bridge for %s", scene_id, entity_id)
        return

    for light_id, kwargs in _scene_light_writes(scene):
        await _write_light(bridge, light_id, **kwargs)
