import functools
import logging

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.util.color import color_xy_to_hs, color_xy_to_RGB

from .attributes import (
    _clamp_brightness,
    _current_brightness,
    _positive_or_none,
    _resolve_color_temp,
    _resolve_color_xy,
)
from .bridge import _get_cached_attributes, _iter_scene_targets, _iter_targets, _send_set_attributes
from .const import (
    DEFAULT_MAX_BRIGHTNESS,
    DEFAULT_MIN_BRIGHTNESS,
    DEFAULT_SWEEP_TIME,
    DIR_DOWN,
    DIR_UP,
    DOMAIN,
    SERVICE_GET_ATTRIBUTES,
    SERVICE_LOWER,
    SERVICE_RAISE,
    SERVICE_SET_ATTRIBUTES,
    SERVICE_SET_SCENE,
    SERVICE_STOP,
)
from .scenes import _apply_scene
from .transitions import _start_transition, _stop_transition

_LOGGER = logging.getLogger(__name__)


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

SCHEMA_SET_SCENE = cv.make_entity_service_schema({})


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


async def _handle_transition(hass: HomeAssistant, call: ServiceCall, direction: str, default_limit: float):
    sweep = float(call.data.get("sweep_time", DEFAULT_SWEEP_TIME))
    sweep = max(sweep, 0.1)  # Restricts user-supplied value to +ve numbers
    limit = float(call.data.get("limit", default_limit))

    async for entity_id, bridge, resource_type, resource_id in _iter_targets(hass, call):
        await _start_transition(hass, bridge, resource_type, resource_id, entity_id, direction, sweep, limit)


async def _handle_stop(hass: HomeAssistant, call: ServiceCall):
    async for entity_id, bridge, resource_type, resource_id in _iter_targets(hass, call):
        await _stop_transition(hass, bridge, resource_type, resource_id, entity_id)


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


async def _handle_set_scene(hass: HomeAssistant, call: ServiceCall):
    async for entity_id, bridge, scene_id in _iter_scene_targets(hass, call):
        await _apply_scene(bridge, entity_id, scene_id)


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
    SERVICE_SET_SCENE: (_handle_set_scene, SCHEMA_SET_SCENE, SupportsResponse.NONE),
}


async def _call_if_loaded(handler, hass: HomeAssistant, call: ServiceCall):
    if not hass.config_entries.async_loaded_entries(DOMAIN):
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_loaded")
    return await handler(hass, call)


@callback
def async_setup_services(hass: HomeAssistant):
    for svc_name, (handler, schema, supports_resp) in SERVICES.items():
        hass.services.async_register(
            DOMAIN,
            svc_name,
            functools.partial(_call_if_loaded, handler, hass),
            schema=schema,
            supports_response=supports_resp,
        )
