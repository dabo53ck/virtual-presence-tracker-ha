"""Tests for the config entry lifecycle."""

from __future__ import annotations

from typing import Any

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.virtual_presence_tracker import VirtualPresenceTrackerData
from custom_components.virtual_presence_tracker.const import (
    CONF_PERSONS,
    DOMAIN,
    STORAGE_KEY_PREFIX,
    SUBENTRY_TYPE_TRACKER,
)
from custom_components.virtual_presence_tracker.manager import HouseholdManager
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

ENTRY_ID = "01JVPT0000000000000000ENTRY"
STORE_KEY = f"{STORAGE_KEY_PREFIX}.{ENTRY_ID}"
TRACKER_A = "01JVPT000000000000000TRACKA"


def make_entry_with_tracker() -> MockConfigEntry:
    """Return a config entry with one real person and one virtual tracker."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Virtual Presence Tracker",
        entry_id=ENTRY_ID,
        data={CONF_PERSONS: ["person.dabo53ck"]},
        subentries_data=[
            {
                "data": {},
                "subentry_id": TRACKER_A,
                "subentry_type": SUBENTRY_TYPE_TRACKER,
                "title": "Kid",
                "unique_id": None,
            }
        ],
    )


async def test_setup_and_unload(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """A config entry can be set up and unloaded again."""
    config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED
    assert isinstance(config_entry.runtime_data, VirtualPresenceTrackerData)
    # The entry has no trackers yet, the manager tolerates that.
    assert isinstance(config_entry.runtime_data.manager, HouseholdManager)
    assert config_entry.runtime_data.manager.tracker_ids == []

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_reload_keeps_the_tracker_state(hass: HomeAssistant) -> None:
    """A reload flushes the state to the store and reads it back."""
    entry = make_entry_with_tracker()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    manager = entry.runtime_data.manager
    manager.async_set_home(TRACKER_A, True)

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.manager is not manager
    assert entry.runtime_data.manager.is_home(TRACKER_A) is True


async def test_removing_a_tracker_prunes_its_state(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """Removing a subentry reloads the entry and drops the stored state."""
    entry = make_entry_with_tracker()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    entry.runtime_data.manager.async_set_home(TRACKER_A, True)

    hass.config_entries.async_remove_subentry(entry, TRACKER_A)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.manager.tracker_ids == []

    # Unloading flushes what is left, which is nothing.
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert hass_storage[STORE_KEY]["data"]["trackers"] == {}
