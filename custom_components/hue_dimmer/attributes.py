import logging

from homeassistant.util.color import color_hs_to_xy, color_RGB_to_xy

from .bridge import _get_cached_attributes, _mirek_kelvin, _state_attributes
from .const import BRIGHTNESS_EPSILON
from .transitions import resolve_brightness

_LOGGER = logging.getLogger(__name__)


def _current_brightness(hass, entity_id, bridge, resource_type, resource_id):
    # Cache-aware brightness, falling back to aiohue's stored value when HA reports the light as off.
    brightness = resolve_brightness(hass, entity_id)
    if brightness < BRIGHTNESS_EPSILON:
        brightness, _, _ = _get_cached_attributes(bridge, resource_type, resource_id)
    return brightness


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
