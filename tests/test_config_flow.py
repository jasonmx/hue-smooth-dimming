"""Tests for the config flow."""

from unittest.mock import MagicMock

import pytest
from homeassistant.data_entry_flow import FlowResultType

from custom_components.hue_dimmer.config_flow import HueDimmerConfigFlow
from custom_components.hue_dimmer.const import NAME


def _flow():
    flow = HueDimmerConfigFlow()
    flow.hass = MagicMock()
    flow.context = {"source": "user"}
    return flow


@pytest.mark.asyncio
async def test_user_step_shows_empty_form():
    result = await _flow().async_step_user()

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"


@pytest.mark.asyncio
async def test_user_step_submit_creates_entry():
    result = await _flow().async_step_user(user_input={})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == NAME
    assert result["data"] == {}
