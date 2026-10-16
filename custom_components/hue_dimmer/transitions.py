import logging
import time

from homeassistant.core import HomeAssistant

from .bridge import _get_controller, _state_attributes
from .const import API_SETTLE_SECONDS, DIR_NONE, DIR_UP, MIN_BRIGHTNESS_STEP

_LOGGER = logging.getLogger(__name__)

# Moving:  { entity_id: { "time": float, "bright": float, "target": float, "dir": DIR_UP/DIR_DOWN, "sweep": float } }
# Stopped: { entity_id: { "time": float, "bright": float, "dir": DIR_NONE } }
_brightness_cache = {}


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


async def _stop_transition(hass, bridge, resource_type, resource_id, entity_id):
    controller = _get_controller(bridge, resource_type)
    try:
        await controller.set_dimming_delta(resource_id)
    except Exception as exc:
        _LOGGER.debug("Stop command ignored for %s: %s", resource_id, exc)
        return

    current_bright = resolve_brightness(hass, entity_id)
    _brightness_cache[entity_id] = {"time": time.time(), "bright": current_bright, "dir": DIR_NONE}

    _LOGGER.debug("STOP [%s]: Halted at %.1f%%", entity_id, current_bright)
