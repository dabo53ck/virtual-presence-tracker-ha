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
from homeassistant.config_entries import ConfigEntryState, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

ENTRY_ID = "01JVPT0000000000000000ENTRY"
STORE_KEY = f"{STORAGE_KEY_PREFIX}.{ENTRY_ID}"
TRACKER_A = "01JVPT000000000000000TRACKA"
TRACKER_B = "01JVPT000000000000000TRACKB"

TRACKER_A_ENTITIES = ("device_tracker.kid", "switch.kid_at_home")


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


async def test_adding_a_tracker_creates_its_entities(hass: HomeAssistant) -> None:
    """A new subentry reloads the entry and brings its own entities."""
    entry = make_entry_with_tracker()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    hass.config_entries.async_add_subentry(
        entry,
        ConfigSubentry(
            data={},
            subentry_id=TRACKER_B,
            subentry_type=SUBENTRY_TYPE_TRACKER,
            title="Granny",
            unique_id=None,
        ),
    )
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    entity_entry = registry.async_get("switch.granny_at_home")
    assert entity_entry is not None
    assert entity_entry.config_subentry_id == TRACKER_B
    assert registry.async_get("device_tracker.granny") is not None


async def test_removing_a_tracker_removes_its_entities(hass: HomeAssistant) -> None:
    """Removing a subentry takes its entities and its device with it."""
    entry = make_entry_with_tracker()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    devices = dr.async_get(hass)
    identifier = (DOMAIN, TRACKER_A)
    assert devices.async_get_device_by_identifier(identifier, ENTRY_ID) is not None

    hass.config_entries.async_remove_subentry(entry, TRACKER_A)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    for entity_id in TRACKER_A_ENTITIES:
        assert registry.async_get(entity_id) is None
        assert hass.states.get(entity_id) is None
    assert devices.async_get_device_by_identifier(identifier, ENTRY_ID) is None
    # The household sensor is not bound to a tracker and stays.
    assert (
        registry.async_get(
            "binary_sensor.virtual_presence_tracker_only_virtual_trackers_home"
        )
        is not None
    )


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
