"""Tests for the device tracker of a virtual tracker."""

from __future__ import annotations

from typing import Any

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.virtual_presence_tracker.const import (
    DOMAIN,
    STORAGE_KEY_PREFIX,
    STORAGE_VERSION,
)
from homeassistant.components.device_tracker import ATTR_IN_ZONES, ATTR_SOURCE_TYPE
from homeassistant.const import (
    ATTR_FRIENDLY_NAME,
    EVENT_STATE_CHANGED,
    STATE_HOME,
    STATE_NOT_HOME,
    STATE_UNKNOWN,
)
from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.helpers import entity_registry as er

from .conftest import ENTRY_ID, TRACKER_A, TRACKER_B, make_entry, make_subentry

TRACKER_A_ENTITY = "device_tracker.kid"
TRACKER_B_ENTITY = "device_tracker.granny"
STORE_KEY = f"{STORAGE_KEY_PREFIX}.{ENTRY_ID}"


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Add a config entry to hass and set it up."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


@callback
def record_tracker_states(hass: HomeAssistant) -> list[State]:
    """Collect every device tracker state written from now on."""
    states: list[State] = []

    @callback
    def _record(event: Event) -> None:
        if (new_state := event.data["new_state"]) is not None and (
            new_state.domain == "device_tracker"
        ):
            states.append(new_state)

    hass.bus.async_listen(EVENT_STATE_CHANGED, _record)
    return states


def written_by_the_entity(states: list[State]) -> list[State]:
    """Return the states the entity itself wrote.

    Home Assistant writes ``unavailable`` with ``restored: True`` for a
    registry entry whose entity is not loaded; those are not entity writes.
    """
    return [state for state in states if not state.attributes.get("restored")]


async def test_one_tracker_per_subentry(
    hass: HomeAssistant, tracker_entry: MockConfigEntry
) -> None:
    """Every virtual tracker gets a device tracker bound to its subentry."""
    await setup_entry(hass, tracker_entry)

    registry = er.async_get(hass)
    entry_a = registry.async_get(TRACKER_A_ENTITY)
    entry_b = registry.async_get(TRACKER_B_ENTITY)

    assert entry_a is not None
    assert entry_a.unique_id == f"{TRACKER_A}_tracker"
    assert entry_a.config_subentry_id == TRACKER_A
    assert entry_b is not None
    assert entry_b.unique_id == f"{TRACKER_B}_tracker"
    assert entry_b.config_subentry_id == TRACKER_B

    # A tracker entity never belongs to a device, and it is a normal entity
    # rather than a diagnostic one, so users find it in the person picker and
    # on dashboards.
    assert entry_a.device_id is None
    assert entry_a.entity_category is None

    state = hass.states.get(TRACKER_A_ENTITY)
    assert state is not None
    assert state.attributes[ATTR_FRIENDLY_NAME] == "Kid"


async def test_state_follows_the_manager(
    hass: HomeAssistant, tracker_entry: MockConfigEntry
) -> None:
    """The tracker is home while it is switched on, not_home otherwise."""
    await setup_entry(hass, tracker_entry)
    manager = tracker_entry.runtime_data.manager

    state = hass.states.get(TRACKER_A_ENTITY)
    assert state is not None
    assert state.state == STATE_NOT_HOME
    assert state.attributes[ATTR_SOURCE_TYPE] == "router"
    assert state.attributes[ATTR_IN_ZONES] == []

    manager.async_set_home(TRACKER_A, True)
    await hass.async_block_till_done()

    state = hass.states.get(TRACKER_A_ENTITY)
    assert state is not None
    assert state.state == STATE_HOME
    # The zone membership is what makes a person follow this tracker.
    assert state.attributes[ATTR_IN_ZONES] == ["zone.home"]
    # Another tracker is not affected.
    assert hass.states.get(TRACKER_B_ENTITY).state == STATE_NOT_HOME

    manager.async_set_home(TRACKER_A, False)
    await hass.async_block_till_done()

    state = hass.states.get(TRACKER_A_ENTITY)
    assert state is not None
    assert state.state == STATE_NOT_HOME
    assert state.attributes[ATTR_IN_ZONES] == []


async def test_renaming_keeps_the_entity(
    hass: HomeAssistant, tracker_entry: MockConfigEntry
) -> None:
    """Renaming a tracker keeps its entity ID, unique ID and state."""
    await setup_entry(hass, tracker_entry)
    tracker_entry.runtime_data.manager.async_set_home(TRACKER_A, True)
    await hass.async_block_till_done()

    subentry = tracker_entry.subentries[TRACKER_A]
    hass.config_entries.async_update_subentry(tracker_entry, subentry, title="Teenager")
    # The update listener reloads the entry.
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    entity_entry = registry.async_get(TRACKER_A_ENTITY)
    assert entity_entry is not None
    assert entity_entry.unique_id == f"{TRACKER_A}_tracker"
    assert entity_entry.original_name == "Teenager"

    state = hass.states.get(TRACKER_A_ENTITY)
    assert state is not None
    assert state.state == STATE_HOME
    assert state.attributes[ATTR_FRIENDLY_NAME] == "Teenager"


async def test_first_state_is_the_restored_one(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """A tracker that was home stays home from its very first state on.

    The person a tracker is assigned to turns ``unknown`` when the tracker
    writes ``not_home`` before the stored state is read back (hass-virtual
    issue #82), so the first write has to be the restored value already.
    """
    hass_storage[STORE_KEY] = {
        "version": STORAGE_VERSION,
        "minor_version": 1,
        "key": STORE_KEY,
        "data": {
            "trackers": {
                TRACKER_A: {"home": True, "since": "2026-09-19T08:00:00+00:00"}
            }
        },
    }
    entry = make_entry(make_subentry(TRACKER_A, "Kid"))
    states = record_tracker_states(hass)

    await setup_entry(hass, entry)

    written = written_by_the_entity(states)
    assert written
    assert written[0].entity_id == TRACKER_A_ENTITY
    assert written[0].state == STATE_HOME
    assert not any(state.state == STATE_UNKNOWN for state in states)


async def test_reload_keeps_the_tracker_home(
    hass: HomeAssistant, tracker_entry: MockConfigEntry
) -> None:
    """A reload never lets the tracker fall back to away or unknown."""
    await setup_entry(hass, tracker_entry)
    tracker_entry.runtime_data.manager.async_set_home(TRACKER_A, True)
    await hass.async_block_till_done()
    assert hass.states.get(TRACKER_A_ENTITY).state == STATE_HOME

    states = record_tracker_states(hass)
    await hass.config_entries.async_reload(tracker_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(TRACKER_A_ENTITY).state == STATE_HOME
    assert not any(state.state == STATE_UNKNOWN for state in states)
    written = [
        state
        for state in written_by_the_entity(states)
        if state.entity_id == TRACKER_A_ENTITY
    ]
    assert written
    assert written[0].state == STATE_HOME


async def test_unload_removes_the_entities(
    hass: HomeAssistant, tracker_entry: MockConfigEntry
) -> None:
    """Unloading takes the entities down but keeps their registry entries."""
    await setup_entry(hass, tracker_entry)

    assert await hass.config_entries.async_unload(tracker_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(TRACKER_A_ENTITY)
    # Home Assistant leaves a restored placeholder behind, not a real state.
    assert state is None or state.attributes.get("restored") is True
    assert er.async_get(hass).async_get(TRACKER_A_ENTITY) is not None
    assert DOMAIN in hass.config.components
