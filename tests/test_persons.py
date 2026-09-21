"""Tests for the person a new virtual tracker asks for (M2g).

The person is created against the real `person` component, because the whole
point is that Home Assistant's own collection accepts it: the integration only
leaves a marker in the subentry data and does the work once Home Assistant has
started.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.virtual_presence_tracker.const import (
    ATTR_DEVICE_TRACKERS,
    CONF_CREATE_PERSON,
    DOMAIN,
    PERSON_DOMAIN,
)
from custom_components.virtual_presence_tracker.issues import ISSUE_TRACKER_NOT_ASSIGNED
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, Event, HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component

from .conftest import ENTRY_ID, PERSON_A, TRACKER_A, make_entry, make_subentry

TRACKER_ENTITY = "device_tracker.kid"
PERSON_KID = "person.kid"
DABO53CK_PHONE = "device_tracker.dabo53ck_phone"

DABO53CK = {"id": "dabo53ck", "name": "dabo53ck", "device_trackers": [DABO53CK_PHONE]}

NOT_ASSIGNED = "_".join((ENTRY_ID, ISSUE_TRACKER_NOT_ASSIGNED, TRACKER_A))


async def setup_person(hass: HomeAssistant, *persons: dict[str, Any]) -> None:
    """Set up the real person component with the given persons."""
    assert await async_setup_component(hass, "person", {"person": [DABO53CK, *persons]})


async def setup_tracker(
    hass: HomeAssistant, *, marker: bool = True, title: str = "Kid"
) -> MockConfigEntry:
    """Set up an entry with one tracker, before Home Assistant has started."""
    hass.set_state(CoreState.not_running)
    entry = make_entry(
        make_subentry(
            TRACKER_A, title, **({CONF_CREATE_PERSON: True} if marker else {})
        )
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def start(hass: HomeAssistant) -> None:
    """Let Home Assistant finish starting."""
    hass.set_state(CoreState.running)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()


def issue_ids(hass: HomeAssistant) -> set[str]:
    """Return the IDs of the repair issues of this integration."""
    return {
        issue_id for (domain, issue_id) in ir.async_get(hass).issues if domain == DOMAIN
    }


def persons(hass: HomeAssistant) -> list[str]:
    """Return the entity IDs of every person that exists."""
    return sorted(state.entity_id for state in hass.states.async_all(PERSON_DOMAIN))


async def test_the_person_of_a_new_tracker_is_created(hass: HomeAssistant) -> None:
    """The tracker gets a person of its own, named after it."""
    await setup_person(hass)
    entry = await setup_tracker(hass)
    manager = entry.runtime_data.manager

    await start(hass)

    person = hass.states.get(PERSON_KID)
    assert person is not None
    assert person.name == "Kid"
    assert person.attributes[ATTR_DEVICE_TRACKERS] == [TRACKER_ENTITY]
    # The person exists, so the tracker is not reported as unassigned.
    assert issue_ids(hass) == set()
    # The marker has done its job and is gone - without reloading the entry,
    # which would take the tracker and its brand new person to `unavailable`.
    assert CONF_CREATE_PERSON not in entry.subentries[TRACKER_A].data
    assert entry.runtime_data.manager is manager


async def test_the_issue_is_not_raised_while_the_person_is_being_created(
    hass: HomeAssistant,
) -> None:
    """The repair issue never flashes up in the moment before the person."""
    raised: list[str] = []

    def record(event: Event[ir.EventIssueRegistryUpdatedData]) -> None:
        if event.data["domain"] == DOMAIN and event.data["action"] == "create":
            raised.append(event.data["issue_id"])

    hass.bus.async_listen(ir.EVENT_REPAIRS_ISSUE_REGISTRY_UPDATED, record)

    await setup_person(hass)
    await setup_tracker(hass)
    await start(hass)

    assert raised == []


async def test_a_person_of_the_same_name_is_neither_doubled_nor_stolen(
    hass: HomeAssistant,
) -> None:
    """A person that is already there is the user's, not ours to change."""
    await setup_person(hass, {"id": "kid", "name": "Kid", "device_trackers": []})
    entry = await setup_tracker(hass)

    await start(hass)

    assert persons(hass) == ["person.dabo53ck", PERSON_KID]
    assert hass.states.get(PERSON_KID).attributes[ATTR_DEVICE_TRACKERS] == []
    # Nothing was created, so the tracker really is unassigned and says so.
    assert issue_ids(hass) == {NOT_ASSIGNED}
    assert CONF_CREATE_PERSON not in entry.subentries[TRACKER_A].data


async def test_a_tracker_that_is_already_followed_gets_no_person(
    hass: HomeAssistant,
) -> None:
    """Somebody was quicker: the tracker is part of a person already."""
    await setup_person(
        hass, {"id": "kiddo", "name": "Kiddo", "device_trackers": [TRACKER_ENTITY]}
    )
    entry = await setup_tracker(hass)

    await start(hass)

    assert persons(hass) == ["person.dabo53ck", "person.kiddo"]
    assert issue_ids(hass) == set()
    assert CONF_CREATE_PERSON not in entry.subentries[TRACKER_A].data


async def test_a_tracker_without_the_marker_is_left_alone(
    hass: HomeAssistant,
) -> None:
    """A tracker from before M2g, or one the user unticked, gets nothing."""
    await setup_person(hass)
    entry = await setup_tracker(hass, marker=False)

    await start(hass)

    assert persons(hass) == ["person.dabo53ck"]
    assert issue_ids(hass) == {NOT_ASSIGNED}
    assert dict(entry.subentries[TRACKER_A].data) == {}


async def test_a_failure_is_logged_and_the_marker_taken_off(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """A person that cannot be created leaves the repair issue behind."""
    await setup_person(hass)
    entry = await setup_tracker(hass)

    with patch(
        "custom_components.virtual_presence_tracker.persons.async_create_person",
        side_effect=ValueError("no"),
    ):
        await start(hass)

    assert "Could not create a person for the virtual tracker Kid" in caplog.text
    assert persons(hass) == ["person.dabo53ck"]
    assert issue_ids(hass) == {NOT_ASSIGNED}
    # Cleared even so: an attempt that failed once fails again, and the repair
    # issue is the better place to say so.
    assert CONF_CREATE_PERSON not in entry.subentries[TRACKER_A].data


async def test_the_person_is_created_exactly_once(hass: HomeAssistant) -> None:
    """A person the user deletes afterwards is never created again."""
    await setup_person(hass)
    entry = await setup_tracker(hass)
    await start(hass)
    assert persons(hass) == ["person.dabo53ck", PERSON_KID]

    await hass.data[PERSON_DOMAIN][1].async_delete_item("kid")
    await hass.async_block_till_done()
    assert persons(hass) == ["person.dabo53ck"]

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert persons(hass) == ["person.dabo53ck"]
    assert issue_ids(hass) == {NOT_ASSIGNED}


async def test_the_person_is_not_created_without_the_person_component(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """An instance without `person` keeps the marker out of the data anyway."""
    entry = await setup_tracker(hass)

    await start(hass)

    assert "the person integration is not set up" in caplog.text
    assert CONF_CREATE_PERSON not in entry.subentries[TRACKER_A].data


async def test_a_real_person_is_never_given_a_virtual_tracker(
    hass: HomeAssistant,
) -> None:
    """The created person is a new one, not one of the household's own.

    Giving a real person a virtual tracker is the self-reset hazard the repair
    issues are about, so the name check must not match a real person by
    accident - it matches by name, and a tracker named after a real person is
    left to the user.
    """
    await setup_person(hass)
    entry = await setup_tracker(hass, title="dabo53ck")

    await start(hass)

    assert persons(hass) == ["person.dabo53ck"]
    assert hass.states.get(PERSON_A).attributes[ATTR_DEVICE_TRACKERS] == [DABO53CK_PHONE]
    assert CONF_CREATE_PERSON not in entry.subentries[TRACKER_A].data
