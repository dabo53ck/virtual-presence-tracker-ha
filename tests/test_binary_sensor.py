"""Tests for the "only virtual trackers home" sensor."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.virtual_presence_tracker.const import (
    ATTR_REAL_PERSONS_HOME,
    ATTR_VIRTUAL_TRACKERS_HOME,
    DOMAIN,
)
from homeassistant.const import (
    ATTR_FRIENDLY_NAME,
    STATE_HOME,
    STATE_NOT_HOME,
    STATE_OFF,
    STATE_ON,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .conftest import ENTRY_ID, PERSON_A, TRACKER_A, TRACKER_B

SENSOR = "binary_sensor.only_virtual_trackers_home"


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Add a config entry to hass and set it up."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_one_sensor_per_entry(
    hass: HomeAssistant, tracker_entry: MockConfigEntry
) -> None:
    """The household sensor belongs to the entry, not to a tracker."""
    await setup_entry(hass, tracker_entry)

    entity_entry = er.async_get(hass).async_get(SENSOR)
    assert entity_entry is not None
    assert entity_entry.unique_id == f"{ENTRY_ID}_only_virtual_home"
    assert entity_entry.config_subentry_id is None

    # Every device belongs to a tracker subentry; an entry-level entity has
    # none, so the entity ID and the name are the entity name on its own.
    assert entity_entry.device_id is None
    assert (
        dr.async_get(hass).async_get_device_by_identifier((DOMAIN, ENTRY_ID), ENTRY_ID)
        is None
    )

    state = hass.states.get(SENSOR)
    assert state is not None
    assert state.attributes[ATTR_FRIENDLY_NAME] == "Only virtual trackers home"


async def test_unknown_while_no_person_state_is_known(
    hass: HomeAssistant, tracker_entry: MockConfigEntry
) -> None:
    """Without a known real person the sensor does not guess."""
    await setup_entry(hass, tracker_entry)

    state = hass.states.get(SENSOR)
    assert state is not None
    assert state.state == STATE_UNKNOWN
    assert state.attributes[ATTR_REAL_PERSONS_HOME] == 0
    assert state.attributes[ATTR_VIRTUAL_TRACKERS_HOME] == []

    # A tracker alone does not answer the question either.
    tracker_entry.runtime_data.manager.async_set_home(TRACKER_A, True)
    await hass.async_block_till_done()

    state = hass.states.get(SENSOR)
    assert state.state == STATE_UNKNOWN
    assert state.attributes[ATTR_VIRTUAL_TRACKERS_HOME] == ["Kid"]


@pytest.mark.parametrize(
    ("person_state", "trackers_home", "expected"),
    [
        (STATE_NOT_HOME, [], STATE_OFF),
        (STATE_NOT_HOME, [TRACKER_A], STATE_ON),
        (STATE_NOT_HOME, [TRACKER_A, TRACKER_B], STATE_ON),
        (STATE_HOME, [], STATE_OFF),
        (STATE_HOME, [TRACKER_A], STATE_OFF),
        ("zone.office", [TRACKER_A], STATE_ON),
    ],
)
async def test_state_matrix(
    hass: HomeAssistant,
    tracker_entry: MockConfigEntry,
    person_state: str,
    trackers_home: list[str],
    expected: str,
) -> None:
    """Only virtual trackers home means a tracker is home and nobody real."""
    hass.states.async_set(PERSON_A, person_state)
    await setup_entry(hass, tracker_entry)

    for tracker_id in trackers_home:
        tracker_entry.runtime_data.manager.async_set_home(tracker_id, True)
    await hass.async_block_till_done()

    assert hass.states.get(SENSOR).state == expected


async def test_attributes_name_who_is_home(
    hass: HomeAssistant, tracker_entry: MockConfigEntry
) -> None:
    """The attributes say how many real persons and which trackers are home."""
    hass.states.async_set(PERSON_A, STATE_NOT_HOME)
    await setup_entry(hass, tracker_entry)

    manager = tracker_entry.runtime_data.manager
    manager.async_set_home(TRACKER_B, True)
    await hass.async_block_till_done()

    state = hass.states.get(SENSOR)
    assert state.state == STATE_ON
    assert state.attributes[ATTR_REAL_PERSONS_HOME] == 0
    assert state.attributes[ATTR_VIRTUAL_TRACKERS_HOME] == ["Granny"]

    manager.async_set_home(TRACKER_A, True)
    hass.states.async_set(PERSON_A, STATE_HOME)
    await hass.async_block_till_done()

    state = hass.states.get(SENSOR)
    assert state.state == STATE_OFF
    assert state.attributes[ATTR_REAL_PERSONS_HOME] == 1
    # The arriving person resets both trackers, so nobody virtual is left.
    assert state.attributes[ATTR_VIRTUAL_TRACKERS_HOME] == []
