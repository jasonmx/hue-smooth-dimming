"""Tests for entity -> Hue bridge resolution: _resolve_bridge, resolve_entity, _iter_targets."""

import logging
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from custom_components.hue_dimmer.bridge import _iter_targets, _resolve_bridge, resolve_entity
from tests.conftest import make_service_call

ENTITY_ID = "light.test_light"
RESOURCE_ID = "res-001"


@pytest.fixture(autouse=True)
def stub_hue_const():
    # _resolve_bridge imports the core Hue integration's DOMAIN; importing the real module needs aiohue.
    with patch.dict(sys.modules, {"homeassistant.components.hue.const": SimpleNamespace(DOMAIN="hue")}):
        yield


def _hue_hass(registry_entry="default", config_entry="default", is_group=False):
    """Return (hass, bridge) wired so ENTITY_ID resolves to a V2 Hue bridge unless overridden."""
    bridge = MagicMock(api_version=2)

    if registry_entry == "default":
        registry_entry = MagicMock(config_entry_id="entry-1", unique_id=RESOURCE_ID)
    if config_entry == "default":
        config_entry = MagicMock(domain="hue", runtime_data=bridge)

    hass = MagicMock()
    hass.config_entries.async_get_entry.return_value = config_entry
    hass.states.get.return_value.attributes = {"is_hue_group": True} if is_group else {}

    registry = MagicMock()
    registry.async_get.return_value = registry_entry
    return hass, bridge, registry


def _patch_registry(registry):
    return patch("custom_components.hue_dimmer.bridge.er.async_get", return_value=registry)


# ---------------------------------------------------------------------------
# _resolve_bridge
# ---------------------------------------------------------------------------

def test_resolve_bridge_returns_bridge_and_resource_id():
    hass, bridge, registry = _hue_hass()
    with _patch_registry(registry):
        assert _resolve_bridge(hass, ENTITY_ID) == (bridge, RESOURCE_ID)


def test_resolve_bridge_strips_unique_id_prefix():
    hass, bridge, registry = _hue_hass(
        registry_entry=MagicMock(config_entry_id="entry-1", unique_id=f"bridge-abc:{RESOURCE_ID}")
    )
    with _patch_registry(registry):
        assert _resolve_bridge(hass, ENTITY_ID) == (bridge, RESOURCE_ID)


@pytest.mark.parametrize("overrides, message", [
    pytest.param({"registry_entry": None}, "not found in entity registry", id="not_in_registry"),
    pytest.param({"config_entry": None}, "is not a Philips Hue entity", id="no_config_entry"),
    pytest.param(
        {"config_entry": MagicMock(domain="zha")}, "is not a Philips Hue entity", id="not_hue_integration"
    ),
    pytest.param(
        {"config_entry": MagicMock(domain="hue", runtime_data=None)},
        "runtime_data not found",
        id="bridge_not_loaded",
    ),
    pytest.param(
        {"config_entry": MagicMock(domain="hue", runtime_data=MagicMock(api_version=1))},
        "requires a Bridge V2 or Bridge Pro",
        id="v1_bridge",
    ),
])
def test_resolve_bridge_rejects_unusable_entities(overrides, message, caplog):
    hass, _, registry = _hue_hass(**overrides)
    with _patch_registry(registry), caplog.at_level(logging.ERROR):
        assert _resolve_bridge(hass, ENTITY_ID) == (None, None)
    assert message in caplog.text


# ---------------------------------------------------------------------------
# resolve_entity
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("is_group, expected_type", [
    pytest.param(False, "light", id="light"),
    pytest.param(True, "grouped_light", id="hue_group"),
])
def test_resolve_entity_resource_type(is_group, expected_type):
    hass, bridge, registry = _hue_hass(is_group=is_group)
    with _patch_registry(registry):
        assert resolve_entity(hass, ENTITY_ID) == (bridge, expected_type, RESOURCE_ID)


def test_resolve_entity_unresolved_returns_nones():
    hass, _, registry = _hue_hass(registry_entry=None)
    with _patch_registry(registry):
        assert resolve_entity(hass, ENTITY_ID) == (None, None, None)


# ---------------------------------------------------------------------------
# _iter_targets
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_iter_targets_skips_non_lights_and_unresolved_entities():
    bridge = MagicMock()

    def _resolve(hass, entity_id):
        if entity_id == "light.hue":
            return bridge, "light", RESOURCE_ID
        return None, None, None

    call = make_service_call({"entity_id": ["light.hue", "light.not_hue", "switch.hue_plug"]})
    with patch("custom_components.hue_dimmer.bridge.resolve_entity", side_effect=_resolve) as resolve:
        targets = [t async for t in _iter_targets(MagicMock(), call)]

    assert targets == [("light.hue", bridge, "light", RESOURCE_ID)]
    assert {c.args[1] for c in resolve.call_args_list} == {"light.hue", "light.not_hue"}
