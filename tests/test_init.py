"""Tests for the config entry lifecycle."""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.virtual_presence_tracker import VirtualPresenceTrackerData
from custom_components.virtual_presence_tracker.manager import HouseholdManager
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant


async def test_setup_and_unload(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """A config entry can be set up and unloaded again."""
    config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED
    assert isinstance(config_entry.runtime_data, VirtualPresenceTrackerData)
    # The entry has no trackers and no persons yet, the manager tolerates that.
    assert isinstance(config_entry.runtime_data.manager, HouseholdManager)
    assert config_entry.runtime_data.manager.tracker_ids == []

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.NOT_LOADED
