"""Tests for the switch of a virtual tracker."""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.virtual_presence_tracker.const import ATTR_SINCE, DOMAIN
from homeassistant.components.switch import (
    DOMAIN as SWITCH_DOMAIN,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_FRIENDLY_NAME,
    STATE_HOME,
    STATE_NOT_HOME,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .conftest import TRACKER_A, TRACKER_B

SWITCH_A = "switch.kid_at_home"
SWITCH_B = "switch.granny_at_home"
TRACKER_A_ENTITY = "device_tracker.kid"


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Add a config entry to hass and set it up."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def call_switch(hass: HomeAssistant, service: str, entity_id: str) -> None:
    """Call a switch service on one entity."""
    await hass.services.async_call(
        SWITCH_DOMAIN, service, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    await hass.async_block_till_done()


async def test_one_switch_per_subentry(
    hass: HomeAssistant, tracker_entry: MockConfigEntry
) -> None:
    """Every virtual tracker gets a switch on a device of its own."""
    await setup_entry(hass, tracker_entry)

    registry = er.async_get(hass)
    entry_a = registry.async_get(SWITCH_A)
    entry_b = registry.async_get(SWITCH_B)

    assert entry_a is not None
    assert entry_a.unique_id == f"{TRACKER_A}_at_home"
    assert entry_a.config_subentry_id == TRACKER_A
    assert entry_b is not None
    assert entry_b.unique_id == f"{TRACKER_B}_at_home"
    assert entry_b.config_subentry_id == TRACKER_B

    devices = dr.async_get(hass)
    device = devices.async_get(entry_a.device_id)
    assert device is not None
    assert device.identifiers == {(DOMAIN, TRACKER_A)}
    assert device.name == "Kid"
    assert device.config_entries_subentries[tracker_entry.entry_id] == {TRACKER_A}

    state = hass.states.get(SWITCH_A)
    assert state is not None
    assert state.state == STATE_OFF
    assert state.attributes[ATTR_FRIENDLY_NAME] == "Kid At home"
    assert state.attributes[ATTR_SINCE] is None


async def test_switching_drives_the_tracker(
    hass: HomeAssistant, tracker_entry: MockConfigEntry
) -> None:
    """Turning the switch on and off moves the tracker and the manager."""
    await setup_entry(hass, tracker_entry)
    manager = tracker_entry.runtime_data.manager

    await call_switch(hass, SERVICE_TURN_ON, SWITCH_A)

    assert manager.is_home(TRACKER_A) is True
    assert hass.states.get(SWITCH_A).state == STATE_ON
    assert hass.states.get(TRACKER_A_ENTITY).state == STATE_HOME
    # The other tracker stays where it was.
    assert manager.is_home(TRACKER_B) is False
    assert hass.states.get(SWITCH_B).state == STATE_OFF

    since = hass.states.get(SWITCH_A).attributes[ATTR_SINCE]
    assert since == manager.since(TRACKER_A).isoformat()

    await call_switch(hass, SERVICE_TURN_OFF, SWITCH_A)

    assert manager.is_home(TRACKER_A) is False
    assert hass.states.get(SWITCH_A).state == STATE_OFF
    assert hass.states.get(TRACKER_A_ENTITY).state == STATE_NOT_HOME
    assert hass.states.get(SWITCH_A).attributes[ATTR_SINCE] > since


async def test_switch_follows_the_manager(
    hass: HomeAssistant, tracker_entry: MockConfigEntry
) -> None:
    """A change made through the manager reaches the switch."""
    await setup_entry(hass, tracker_entry)

    tracker_entry.runtime_data.manager.async_set_home(TRACKER_A, True)
    await hass.async_block_till_done()

    assert hass.states.get(SWITCH_A).state == STATE_ON


async def test_renaming_keeps_the_switch(
    hass: HomeAssistant, tracker_entry: MockConfigEntry
) -> None:
    """Renaming a tracker keeps the switch and renames its device."""
    await setup_entry(hass, tracker_entry)
    await call_switch(hass, SERVICE_TURN_ON, SWITCH_A)

    subentry = tracker_entry.subentries[TRACKER_A]
    hass.config_entries.async_update_subentry(tracker_entry, subentry, title="Teenager")
    await hass.async_block_till_done()

    entity_entry = er.async_get(hass).async_get(SWITCH_A)
    assert entity_entry is not None
    assert entity_entry.unique_id == f"{TRACKER_A}_at_home"

    device = dr.async_get(hass).async_get(entity_entry.device_id)
    assert device is not None
    assert device.name == "Teenager"

    state = hass.states.get(SWITCH_A)
    assert state is not None
    assert state.state == STATE_ON
    assert state.attributes[ATTR_FRIENDLY_NAME] == "Teenager At home"
