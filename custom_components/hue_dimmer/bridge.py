import logging
from statistics import mean

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.service import async_extract_entity_ids

_LOGGER = logging.getLogger(__name__)


def _state_attributes(hass: HomeAssistant, entity_id: str):
    state = hass.states.get(entity_id)
    return state.attributes if state else {}


def _mirek_kelvin(value):
    # The conversion is its own inverse: mirek -> kelvin and kelvin -> mirek.
    return round(1_000_000 / value)


def resolve_entity(hass: HomeAssistant, entity_id: str):
    # Retrieves the Hue Bridge instance and Resource UUID, ensuring it supports V2 API.
    from homeassistant.components.hue.const import DOMAIN as HUE_DOMAIN

    ent_reg = er.async_get(hass)
    entry = ent_reg.async_get(entity_id)

    if not entry:
        _LOGGER.error("Entity %s not found in entity registry.", entity_id)
        return None, None, None

    config_entry = hass.config_entries.async_get_entry(entry.config_entry_id)
    if not config_entry or config_entry.domain != HUE_DOMAIN:
        _LOGGER.error("Entity %s is not a Philips Hue entity.", entity_id)
        return None, None, None

    bridge = getattr(config_entry, "runtime_data", None)

    if not bridge:
        _LOGGER.error("Hue bridge runtime_data not found for %s", entity_id)
        return None, None, None

    # V2 Bridge Check
    if getattr(bridge, "api_version", 1) < 2:
        _LOGGER.error("Hue Smooth Dimmer requires a Bridge V2 or Bridge Pro for %s", entity_id)
        return None, None, None

    resource_id = entry.unique_id

    if ":" in resource_id:
        resource_id = resource_id.split(":")[-1]

    is_group = bool(_state_attributes(hass, entity_id).get("is_hue_group"))
    resource_type = "grouped_light" if is_group else "light"

    return bridge, resource_type, resource_id


async def _iter_targets(hass: HomeAssistant, call: ServiceCall):
    # Yields (entity_id, bridge, resource_type, resource_id) for each targeted Hue light or group.
    for entity_id in await async_extract_entity_ids(call):
        if not entity_id.startswith("light."):
            continue
        bridge, resource_type, resource_id = resolve_entity(hass, entity_id)
        if bridge and resource_id:
            yield entity_id, bridge, resource_type, resource_id


def _get_controller(bridge, resource_type):
    if resource_type == "grouped_light":
        return bridge.api.groups.grouped_light
    return bridge.api.lights


def _get_cached_attributes(bridge, resource_type, resource_id):
    # Read brightness, CT, and XY color from aiohue's cached models (sync, no API call).
    # Groups don't report CT or color directly, and report brightness as 0 when off,
    # so their values are averaged from the member lights.
    if resource_type == "grouped_light":
        models = bridge.api.groups.grouped_light.get_lights(resource_id)
    else:
        model = bridge.api.lights.get(resource_id)
        models = [model] if model else []

    brightnesses = [m.dimming.brightness for m in models if m.dimming]
    mireks = [m.color_temperature.mirek for m in models if m.color_temperature and m.color_temperature.mirek]
    xys = [(m.color.xy.x, m.color.xy.y) for m in models if m.color]

    brightness = mean(brightnesses) if brightnesses else 0.0
    color_temp_kelvin = _mirek_kelvin(round(mean(mireks))) if mireks else None
    color_xy = (round(mean(x for x, _ in xys), 4), round(mean(y for _, y in xys), 4)) if xys else None
    return brightness, color_temp_kelvin, color_xy


async def _send_set_attributes(bridge, resource_type, resource_id, brightness, color_temp_mirek, color_xy):
    # For groups, send to each individual light so attributes apply even when off.
    if resource_type == "grouped_light":
        light_ids = [light.id for light in bridge.api.groups.grouped_light.get_lights(resource_id)]
        if not light_ids:
            _LOGGER.warning("No lights found in group %s", resource_id)
            return
    else:
        light_ids = [resource_id]

    for light_id in light_ids:
        try:
            await bridge.api.lights.set_state(
                light_id,
                brightness=float(brightness) if brightness is not None else None,
                color_temp=color_temp_mirek,
                color_xy=color_xy,
            )
        except Exception as exc:
            _LOGGER.error("set_attributes failed for light %s: %s", light_id, exc)
