"""End-to-end tests with the real person and zone components.

The whole point of a virtual tracker is that Home Assistant's own components
treat it like any other tracker: a `person` follows it and `zone.home` counts
that person. These tests wire up `person` and `zone` for real instead of
asserting on our own entities only.
"""

from __future__ import annotations

from typing import Any

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.components.device_tracker import ATTR_SOURCE_TYPE, SourceType
from homeassistant.components.switch import (
    DOMAIN as SWITCH_DOMAIN,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
)
from homeassistant.components.zone import ENTITY_ID_HOME as ZONE_HOME
from homeassistant.const import (
    ATTR_ENTITY_ID,
    STATE_HOME,
    STATE_NOT_HOME,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from .conftest import PERSON_A, PERSON_B, TRACKER_A, make_entry, make_subentry

TRACKER_ENTITY = "device_tracker.kid"
SWITCH = "switch.kid_at_home"

PERSON_KID = "person.kid"
KID_GPS = "device_tracker.kid_tablet"
DABO53CK_PHONE = "device_tracker.dabo53ck_phone"
KING53CK_PHONE = "device_tracker.king53ck_phone"

KID = {"id": "kid", "name": "Kid", "device_trackers": [TRACKER_ENTITY]}
DABO53CK = {"id": "dabo53ck", "name": "dabo53ck", "device_trackers": [DABO53CK_PHONE]}
KING53CK = {"id": "king53ck", "name": "king53ck", "device_trackers": [KING53CK_PHONE]}


async def setup_household(
    hass: HomeAssistant,
    persons: list[dict[str, Any]],
    *,
    real_persons: list[str],
) -> MockConfigEntry:
    """Set up zone, person and the integration with one virtual tracker."""
    assert await async_setup_component(hass, "zone", {})
    assert await async_setup_component(hass, "person", {"person": persons})

    entry = make_entry(make_subentry(TRACKER_A, "Kid"), persons=real_persons)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def set_gps_tracker(hass: HomeAssistant, entity_id: str, state: str) -> None:
    """Set the state of a GPS tracker of a real person."""
    hass.states.async_set(entity_id, state, {ATTR_SOURCE_TYPE: SourceType.GPS})
    await hass.async_block_till_done()


async def call_switch(hass: HomeAssistant, service: str) -> None:
    """Turn the virtual tracker's switch on or off."""
    await hass.services.async_call(
        SWITCH_DOMAIN, service, {ATTR_ENTITY_ID: SWITCH}, blocking=True
    )
    await hass.async_block_till_done()


def persons_at_home(hass: HomeAssistant) -> list[str]:
    """Return the persons zone.home currently counts."""
    state = hass.states.get(ZONE_HOME)
    assert state is not None
    return state.attributes["persons"]


async def test_the_switch_brings_a_person_home(hass: HomeAssistant) -> None:
    """The switch decides whether the person counts as being at home."""
    await setup_household(hass, [KID, DABO53CK], real_persons=[PERSON_A])
    await set_gps_tracker(hass, DABO53CK_PHONE, STATE_NOT_HOME)

    assert hass.states.get(PERSON_KID).state == STATE_NOT_HOME
    assert hass.states.get(ZONE_HOME).state == "0"

    await call_switch(hass, SERVICE_TURN_ON)

    assert hass.states.get(TRACKER_ENTITY).state == STATE_HOME
    person = hass.states.get(PERSON_KID)
    assert person.state == STATE_HOME
    assert person.attributes["source"] == TRACKER_ENTITY
    assert person.attributes["in_zones"] == [ZONE_HOME]
    assert hass.states.get(ZONE_HOME).state == "1"
    assert persons_at_home(hass) == [PERSON_KID]

    await call_switch(hass, SERVICE_TURN_OFF)

    assert hass.states.get(PERSON_KID).state == STATE_NOT_HOME
    assert hass.states.get(ZONE_HOME).state == "0"
    assert persons_at_home(hass) == []


async def test_a_connected_tracker_wins_over_gps(hass: HomeAssistant) -> None:
    """A switched on tracker beats a GPS tracker that says not_home."""
    kid = {**KID, "device_trackers": [TRACKER_ENTITY, KID_GPS]}
    await setup_household(hass, [kid, DABO53CK], real_persons=[PERSON_A])
    await set_gps_tracker(hass, KID_GPS, STATE_NOT_HOME)

    assert hass.states.get(PERSON_KID).state == STATE_NOT_HOME

    await call_switch(hass, SERVICE_TURN_ON)

    person = hass.states.get(PERSON_KID)
    assert person.state == STATE_HOME
    assert person.attributes["source"] == TRACKER_ENTITY
    assert persons_at_home(hass) == [PERSON_KID]

    # The GPS tracker moving away does not overrule the switch either.
    await set_gps_tracker(hass, KID_GPS, "zone.office")
    assert hass.states.get(PERSON_KID).state == STATE_HOME

    # A switched off tracker on the other hand does not veto the GPS tracker:
    # it reports no zone at all, so the GPS tracker decides again.
    await call_switch(hass, SERVICE_TURN_OFF)
    await set_gps_tracker(hass, KID_GPS, STATE_HOME)

    person = hass.states.get(PERSON_KID)
    assert person.state == STATE_HOME
    assert person.attributes["source"] == KID_GPS


async def test_the_reset_chain(hass: HomeAssistant) -> None:
    """A real person entering the empty house switches the tracker off."""
    await setup_household(hass, [KID, DABO53CK], real_persons=[PERSON_A])

    await set_gps_tracker(hass, DABO53CK_PHONE, STATE_HOME)
    assert persons_at_home(hass) == [PERSON_A]

    # dabo53ck leaves, the kid stays behind: the house is not empty.
    await set_gps_tracker(hass, DABO53CK_PHONE, STATE_NOT_HOME)
    await call_switch(hass, SERVICE_TURN_ON)

    assert hass.states.get(ZONE_HOME).state == "1"
    assert persons_at_home(hass) == [PERSON_KID]

    # dabo53ck comes back and takes over: the tracker resets.
    await set_gps_tracker(hass, DABO53CK_PHONE, STATE_HOME)

    assert hass.states.get(SWITCH).state == STATE_OFF
    assert hass.states.get(TRACKER_ENTITY).state == STATE_NOT_HOME
    assert hass.states.get(PERSON_KID).state == STATE_NOT_HOME
    assert persons_at_home(hass) == [PERSON_A]


async def test_no_reset_while_somebody_real_stays_home(hass: HomeAssistant) -> None:
    """Coming home to a house that is not empty leaves the tracker alone."""
    await setup_household(hass, [KID, DABO53CK, KING53CK], real_persons=[PERSON_A, PERSON_B])

    await set_gps_tracker(hass, DABO53CK_PHONE, STATE_NOT_HOME)
    await set_gps_tracker(hass, KING53CK_PHONE, STATE_HOME)
    await call_switch(hass, SERVICE_TURN_ON)

    await set_gps_tracker(hass, DABO53CK_PHONE, STATE_HOME)

    assert hass.states.get(SWITCH).state == STATE_ON
    assert hass.states.get(PERSON_KID).state == STATE_HOME
    assert sorted(persons_at_home(hass)) == [PERSON_A, PERSON_KID, PERSON_B]
