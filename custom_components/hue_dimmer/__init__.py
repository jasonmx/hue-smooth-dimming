import functools
import logging
import time
from statistics import mean

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.service import async_extract_entity_ids
from homeassistant.util.color import color_hs_to_xy, color_RGB_to_xy, color_xy_to_hs, color_xy_to_RGB

from .const import (
    API_SETTLE_SECONDS,
    BRIGHTNESS_EPSILON,
    DEFAULT_MAX_BRIGHTNESS,
    DEFAULT_MIN_BRIGHTNESS,
    DEFAULT_SWEEP_TIME,
    DIR_DOWN,
    DIR_NONE,
    DIR_UP,
    DOMAIN,
    MIN_BRIGHTNESS_STEP,
    SERVICE_GET_ATTRIBUTES,
    SERVICE_LOWER,
    SERVICE_RAISE,
    SERVICE_SET_ATTRIBUTES,
    SERVICE_STOP,
)

_LOGGER = logging.getLogger(__name__)

# Moving:  { entity_id: { "time": float, "bright": float, "target": float, "dir": DIR_UP/DIR_DOWN, "sweep": float } }
# Stopped: { entity_id: { "time": float, "bright": float, "dir": DIR_NONE } }
_brightness_cache = {}


# ---------------------------------------------------------------------------
# Voluptuous validators (shape-only for color tuples)
# ---------------------------------------------------------------------------


def _rgb_color(val):
    if not isinstance(val, (list, tuple)) or len(val) != 3:
        raise vol.Invalid("rgb_color must be a list of 3 values")
    return list(val)


def _two_item_list(val):
    if not isinstance(val, (list, tuple)) or len(val) != 2:
        raise vol.Invalid("must be a list of 2 values")
    return list(val)


# ---------------------------------------------------------------------------
# Service schemas
# ---------------------------------------------------------------------------

SCHEMA_RAISE = cv.make_entity_service_schema(
    {
        vol.Optional("sweep_time"): vol.Coerce(float),
        vol.Optional("limit"): vol.Coerce(float),
    }
)

SCHEMA_LOWER = cv.make_entity_service_schema(
    {
        vol.Optional("sweep_time"): vol.Coerce(float),
        vol.Optional("limit"): vol.Coerce(float),
    }
)

SCHEMA_STOP = cv.make_entity_service_schema({})

SCHEMA_SET_ATTRIBUTES = cv.make_entity_service_schema(
    {
        vol.Optional("brightness"): vol.Coerce(float),
        # 0 is accepted; handlers treat it as "not set" via _positive_or_none
        vol.Optional("min_brightness"): vol.Coerce(float),
        vol.Optional("max_brightness"): vol.Coerce(float),
        vol.Optional("color_temp_kelvin"): vol.Coerce(float),
        vol.Optional("rgb_color"): _rgb_color,
        vol.Optional("hs_color"): _two_item_list,
        vol.Optional("xy_color"): _two_item_list,
    }
)

SCHEMA_GET_ATTRIBUTES = cv.make_entity_service_schema({})


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


def _get_ha_brightness(hass: HomeAssistant, entity_id: str):
    # Read brightness from HA entity state (0-255) and convert to Hue percentage (0-100).
    ha_bright = _state_attributes(hass, entity_id).get("brightness")
    return (ha_bright / 255 * 100) if ha_bright is not None else 0.0


def resolve_brightness(hass: HomeAssistant, entity_id: str):
    # During a dimming transition, the Hue API (and therefore HA's entity state) reports
    # brightness as though the transition happened instantaneously. If a transition stops
    # mid-flight, it takes ~10s to correct its reporting.
    #
    # The resolver decides whether to trust the reported brightness or predict its own, to
    # ensure dim-stop-dim sequences work smoothly. Expired cache entries are pruned inline.

    reported = _get_ha_brightness(hass, entity_id)
    cached = _brightness_cache.get(entity_id)
    if not cached:
        return reported

    elapsed = time.time() - cached["time"]
    moving = cached["dir"] != DIR_NONE

    # Guard window: the API settle buffer, plus the sweep duration for active transitions.
    guard_seconds = API_SETTLE_SECONDS + (cached["sweep"] if moving else 0)

    # Guard expired — trust the reported brightness and prune the cache entry
    if elapsed > guard_seconds:
        _brightness_cache.pop(entity_id, None)
        return reported

    # Guard active — predict brightness instead of trusting the report.

    # Stopped: return the cached brightness from when we stopped
    if not moving:
        _LOGGER.debug(
            "CACHE [%s]: Guard active (Stationary). Ignoring reported %.1f%%. Staying at %.1f%%",
            entity_id,
            reported,
            cached["bright"],
        )
        return cached["bright"]

    # Moving: extrapolate brightness based on elapsed time
    change = (100.0 / cached["sweep"]) * elapsed

    if cached["dir"] == DIR_UP:
        predicted = min(cached["bright"] + change, cached["target"])
    else:
        predicted = max(cached["bright"] - change, cached["target"])

    _LOGGER.debug(
        "CACHE [%s]: Guard active (Moving). Ignoring reported: %.1f%%, Predicted: %.1f%%",
        entity_id,
        reported,
        predicted,
    )

    return predicted


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


def _current_brightness(hass, entity_id, bridge, resource_type, resource_id):
    # Cache-aware brightness, falling back to aiohue's stored value when HA reports the light as off.
    brightness = resolve_brightness(hass, entity_id)
    if brightness < BRIGHTNESS_EPSILON:
        brightness, _, _ = _get_cached_attributes(bridge, resource_type, resource_id)
    return brightness


async def _start_transition(hass, bridge, resource_type, resource_id, entity_id, direction, sweep, limit):
    current_bright = resolve_brightness(hass, entity_id)
    distance = abs(limit - current_bright)
    dur_ms = int(distance * sweep * 10)  # 1000ms / 100% = 10ms/%

    _LOGGER.debug("CALC [%s]: %.1f%% -> %.1f%% | Dur: %dms", entity_id, current_bright, limit, dur_ms)

    if distance < MIN_BRIGHTNESS_STEP:
        return

    controller = _get_controller(bridge, resource_type)
    on = True if direction == DIR_UP else (False if limit == 0.0 else None)

    try:
        await controller.set_state(resource_id, on=on, brightness=limit, transition_time=dur_ms)
    except Exception as exc:
        _LOGGER.warning("Transition command failed for %s: %s", entity_id, exc)
        return

    # Only cache after the bridge accepts the command, or later predictions follow a phantom transition.
    _brightness_cache[entity_id] = {
        "time": time.time(),
        "bright": current_bright,
        "target": limit,
        "dir": direction,
        "sweep": sweep,
    }


async def _handle_transition(hass: HomeAssistant, call: ServiceCall, direction: str, default_limit: float):
    sweep = float(call.data.get("sweep_time", DEFAULT_SWEEP_TIME))
    sweep = max(sweep, 0.1)  # Restricts user-supplied value to +ve numbers
    limit = float(call.data.get("limit", default_limit))

    async for entity_id, bridge, resource_type, resource_id in _iter_targets(hass, call):
        await _start_transition(hass, bridge, resource_type, resource_id, entity_id, direction, sweep, limit)


async def _handle_stop(hass: HomeAssistant, call: ServiceCall):
    async for entity_id, bridge, resource_type, resource_id in _iter_targets(hass, call):
        controller = _get_controller(bridge, resource_type)
        try:
            await controller.set_dimming_delta(resource_id)
        except Exception as exc:
            _LOGGER.debug("Stop command ignored for %s: %s", resource_id, exc)
            continue

        current_bright = resolve_brightness(hass, entity_id)
        _brightness_cache[entity_id] = {"time": time.time(), "bright": current_bright, "dir": DIR_NONE}

        _LOGGER.debug("STOP [%s]: Halted at %.1f%%", entity_id, current_bright)


def _supported_color_modes(hass, entity_id):
    return _state_attributes(hass, entity_id).get("supported_color_modes", [])


def _resolve_color_xy(hass, entity_id, xy_color, hs_color, rgb_color):
    # Convert whichever color format was provided to an XY tuple.
    # Priority: rgb_color > hs_color > xy_color. Warns if more than one is set.
    provided = [f for f in [rgb_color, hs_color, xy_color] if f is not None]
    if not provided:
        return None
    if len(provided) > 1:
        _LOGGER.warning(
            "set_attributes: multiple color fields set for %s; using rgb_color > hs_color > xy_color priority.",
            entity_id,
        )

    if "xy" not in _supported_color_modes(hass, entity_id):
        _LOGGER.warning("Entity %s does not support XY color. Skipping color.", entity_id)
        return None

    if rgb_color is not None:
        return color_RGB_to_xy(int(rgb_color[0]), int(rgb_color[1]), int(rgb_color[2]))
    if hs_color is not None:
        return color_hs_to_xy(float(hs_color[0]), float(hs_color[1]))
    return (float(xy_color[0]), float(xy_color[1]))


def _resolve_color_temp(hass, entity_id, color_temp_kelvin):
    # Validate CT support, clamp to entity range, and convert to mirek.
    if "color_temp" not in _supported_color_modes(hass, entity_id):
        _LOGGER.warning(
            "Entity %s does not support color temperature. Skipping CT.",
            entity_id,
        )
        return None

    attrs = _state_attributes(hass, entity_id)
    min_k = attrs.get("min_color_temp_kelvin", 2000)
    max_k = attrs.get("max_color_temp_kelvin", 6535)
    clamped_k = max(min_k, min(max_k, color_temp_kelvin))
    return _mirek_kelvin(clamped_k)


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


def _clamp_brightness(current, min_brightness, max_brightness):
    clamped = current
    if min_brightness is not None:
        clamped = max(float(min_brightness), clamped)
    if max_brightness is not None:
        clamped = min(float(max_brightness), clamped)
    return clamped if abs(clamped - current) > BRIGHTNESS_EPSILON else None


def _positive_or_none(value):
    if value is None:
        return None
    f = float(value)
    return f if f > 0 else None


async def _handle_set_attributes(hass: HomeAssistant, call: ServiceCall):
    brightness = call.data.get("brightness")
    min_brightness = _positive_or_none(call.data.get("min_brightness"))
    max_brightness = _positive_or_none(call.data.get("max_brightness"))
    color_temp_kelvin = _positive_or_none(call.data.get("color_temp_kelvin"))
    xy_color = call.data.get("xy_color")
    hs_color = call.data.get("hs_color")
    rgb_color = call.data.get("rgb_color")

    has_explicit = brightness is not None
    has_clamp = min_brightness is not None or max_brightness is not None
    has_ct = color_temp_kelvin is not None
    has_color = xy_color is not None or hs_color is not None or rgb_color is not None

    if not has_explicit and not has_clamp and not has_ct and not has_color:
        _LOGGER.warning("set_attributes called with no attributes to set.")
        return

    async for entity_id, bridge, resource_type, resource_id in _iter_targets(hass, call):
        # Resolve brightness per-entity (explicit value, or clamped from current)
        entity_brightness = brightness
        if not has_explicit and has_clamp:
            current = _current_brightness(hass, entity_id, bridge, resource_type, resource_id)
            entity_brightness = _clamp_brightness(current, min_brightness, max_brightness)

        color_temp_mirek = _resolve_color_temp(hass, entity_id, color_temp_kelvin) if has_ct else None
        color_xy = _resolve_color_xy(hass, entity_id, xy_color, hs_color, rgb_color) if has_color else None
        if entity_brightness is not None or color_temp_mirek is not None or color_xy is not None:
            await _send_set_attributes(
                bridge, resource_type, resource_id, entity_brightness, color_temp_mirek, color_xy
            )


async def _handle_get_attributes(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    result = {}
    async for entity_id, bridge, resource_type, resource_id in _iter_targets(hass, call):
        # CT and color always come from aiohue's cache: HA doesn't retain them when lights are off.
        _, color_temp_kelvin, color_xy = _get_cached_attributes(bridge, resource_type, resource_id)
        brightness = _current_brightness(hass, entity_id, bridge, resource_type, resource_id)

        attrs: dict = {"brightness": round(brightness, 1)}
        if color_temp_kelvin is not None:
            attrs["color_temp_kelvin"] = color_temp_kelvin
        if color_xy is not None:
            attrs["xy_color"] = list(color_xy)
            attrs["rgb_color"] = list(color_xy_to_RGB(*color_xy))
            attrs["hs_color"] = list(color_xy_to_hs(*color_xy))
        result[entity_id] = attrs

    return result


# ---------------------------------------------------------------------------
# Module-level handler partials (direction/limit bound; hass bound in setup)
# ---------------------------------------------------------------------------

_raise_handler = functools.partial(_handle_transition, direction=DIR_UP, default_limit=DEFAULT_MAX_BRIGHTNESS)
_lower_handler = functools.partial(_handle_transition, direction=DIR_DOWN, default_limit=DEFAULT_MIN_BRIGHTNESS)

# Table: service_name -> (handler, schema, supports_response)
SERVICES: dict = {
    SERVICE_RAISE: (_raise_handler, SCHEMA_RAISE, SupportsResponse.NONE),
    SERVICE_LOWER: (_lower_handler, SCHEMA_LOWER, SupportsResponse.NONE),
    SERVICE_STOP: (_handle_stop, SCHEMA_STOP, SupportsResponse.NONE),
    SERVICE_SET_ATTRIBUTES: (_handle_set_attributes, SCHEMA_SET_ATTRIBUTES, SupportsResponse.NONE),
    SERVICE_GET_ATTRIBUTES: (_handle_get_attributes, SCHEMA_GET_ATTRIBUTES, SupportsResponse.ONLY),
}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    for svc_name, (handler, schema, supports_resp) in SERVICES.items():
        hass.services.async_register(
            DOMAIN,
            svc_name,
            functools.partial(handler, hass),
            schema=schema,
            supports_response=supports_resp,
        )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    for svc_name in SERVICES:
        hass.services.async_remove(DOMAIN, svc_name)
    return True
