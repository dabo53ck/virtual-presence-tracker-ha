"""Tests for the switch of a virtual tracker and its answer action."""

from __future__ import annotations

from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
import voluptuous as vol

from custom_components.virtual_presence_tracker.const import (
    ANSWER_NO,
    ANSWER_YES,
    ATTR_ANSWER,
    ATTR_ANSWERED_BY,
    ATTR_PROMPT_EXPIRES_AT,
    ATTR_PROMPT_OPEN,
    ATTR_REMINDER_EXPIRES_AT,
    ATTR_REMINDER_OPEN,
    ATTR_SINCE,
    CONF_ASK_ON_DEPARTURE,
    DOMAIN,
    EVENT_ANSWERED_NO,
    EVENT_ANSWERED_YES,
    EVENT_PROMPT_STARTED,
    EVENT_REMINDER_ANSWERED_NO,
    EVENT_REMINDER_ANSWERED_YES,
    EVENT_REMINDER_STARTED,
    SERVICE_ANSWER_PROMPT,
    SERVICE_ANSWER_REMINDER,
    SERVICE_OPEN_PROMPT,
    SERVICE_OPEN_REMINDER,
)
from homeassistant.components.event import ATTR_EVENT_TYPE
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
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .conftest import PERSON_A, TRACKER_A, TRACKER_B, make_entry, make_subentry

SWITCH_A = "switch.kid_at_home"
SWITCH_B = "switch.granny_at_home"
TRACKER_A_ENTITY = "device_tracker.kid"
EVENT_A = "event.kid_prompt"


@pytest.fixture
def asking_entry() -> MockConfigEntry:
    """A config entry whose first tracker asks when the house becomes empty."""
    return make_entry(
        make_subentry(TRACKER_A, "Kid", **{CONF_ASK_ON_DEPARTURE: True}),
        make_subentry(TRACKER_B, "Granny"),
    )


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


async def answer(hass: HomeAssistant, entity_id: str, **data: Any) -> None:
    """Call the answer action on one switch."""
    await hass.services.async_call(
        DOMAIN,
        SERVICE_ANSWER_PROMPT,
        {ATTR_ENTITY_ID: entity_id, **data},
        blocking=True,
    )
    await hass.async_block_till_done()


async def open_prompt(hass: HomeAssistant, entity_id: str) -> None:
    """Call the open action on one switch."""
    await hass.services.async_call(
        DOMAIN, SERVICE_OPEN_PROMPT, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    await hass.async_block_till_done()


async def answer_reminder(hass: HomeAssistant, entity_id: str, **data: Any) -> None:
    """Call the reminder answer action on one switch."""
    await hass.services.async_call(
        DOMAIN,
        SERVICE_ANSWER_REMINDER,
        {ATTR_ENTITY_ID: entity_id, **data},
        blocking=True,
    )
    await hass.async_block_till_done()


async def open_reminder(hass: HomeAssistant, entity_id: str) -> None:
    """Call the reminder open action on one switch."""
    await hass.services.async_call(
        DOMAIN, SERVICE_OPEN_REMINDER, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    await hass.async_block_till_done()


async def remind(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Set the entry up, switch the tracker on and open a reminder about it."""
    await setup_entry(hass, entry)
    await call_switch(hass, SERVICE_TURN_ON, SWITCH_A)
    await open_reminder(hass, SWITCH_A)
    assert entry.runtime_data.manager.reminder_open(TRACKER_A) is True


async def ask(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Set the entry up and open a prompt by emptying the house."""
    hass.states.async_set(PERSON_A, STATE_HOME)
    await setup_entry(hass, entry)
    hass.states.async_set(PERSON_A, STATE_NOT_HOME)
    await hass.async_block_till_done()
    assert entry.runtime_data.manager.prompt_open(TRACKER_A) is True


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
    assert state.attributes[ATTR_PROMPT_OPEN] is False
    assert state.attributes[ATTR_PROMPT_EXPIRES_AT] is None
    assert state.attributes[ATTR_REMINDER_OPEN] is False
    assert state.attributes[ATTR_REMINDER_EXPIRES_AT] is None


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


async def test_the_switch_shows_an_open_prompt(
    hass: HomeAssistant, asking_entry: MockConfigEntry
) -> None:
    """While a tracker is being asked about, its switch says so."""
    await ask(hass, asking_entry)

    state = hass.states.get(SWITCH_A)
    assert state.state == STATE_OFF
    assert state.attributes[ATTR_PROMPT_OPEN] is True
    expires_at = asking_entry.runtime_data.manager.prompt_expires_at(TRACKER_A)
    assert state.attributes[ATTR_PROMPT_EXPIRES_AT] == expires_at.isoformat()

    # The tracker that does not ask is untouched.
    assert hass.states.get(SWITCH_B).attributes[ATTR_PROMPT_OPEN] is False

    await answer(hass, SWITCH_A, **{ATTR_ANSWER: ANSWER_NO})

    state = hass.states.get(SWITCH_A)
    assert state.attributes[ATTR_PROMPT_OPEN] is False
    assert state.attributes[ATTR_PROMPT_EXPIRES_AT] is None


async def test_answering_yes_switches_the_tracker_on(
    hass: HomeAssistant, asking_entry: MockConfigEntry
) -> None:
    """A yes sets the tracker home and names who answered."""
    await ask(hass, asking_entry)

    await answer(
        hass, SWITCH_A, **{ATTR_ANSWER: ANSWER_YES, ATTR_ANSWERED_BY: PERSON_A}
    )

    assert hass.states.get(SWITCH_A).state == STATE_ON
    assert hass.states.get(TRACKER_A_ENTITY).state == STATE_HOME
    state = hass.states.get(EVENT_A)
    assert state.attributes[ATTR_EVENT_TYPE] == EVENT_ANSWERED_YES
    assert state.attributes[ATTR_ANSWERED_BY] == PERSON_A


async def test_answering_no_leaves_the_tracker_alone(
    hass: HomeAssistant, asking_entry: MockConfigEntry
) -> None:
    """A no ends the prompt and changes nothing else."""
    await ask(hass, asking_entry)

    await answer(hass, SWITCH_A, **{ATTR_ANSWER: ANSWER_NO})

    assert hass.states.get(SWITCH_A).state == STATE_OFF
    state = hass.states.get(EVENT_A)
    assert state.attributes[ATTR_EVENT_TYPE] == EVENT_ANSWERED_NO
    assert state.attributes[ATTR_ANSWERED_BY] is None


async def test_answering_a_tracker_that_was_not_asked(
    hass: HomeAssistant, asking_entry: MockConfigEntry
) -> None:
    """Without an open prompt the answer is refused with a clear message."""
    await ask(hass, asking_entry)

    with pytest.raises(ServiceValidationError) as err:
        await answer(hass, SWITCH_B, **{ATTR_ANSWER: ANSWER_YES})

    assert err.value.translation_key == "no_open_prompt"
    assert hass.states.get(SWITCH_B).state == STATE_OFF
    # The other tracker's prompt is untouched by the failed call.
    assert asking_entry.runtime_data.manager.prompt_open(TRACKER_A) is True

    await answer(hass, SWITCH_A, **{ATTR_ANSWER: ANSWER_NO})


async def test_opening_the_prompt_from_the_action(
    hass: HomeAssistant, tracker_entry: MockConfigEntry
) -> None:
    """The action opens the prompt of a tracker that would never ask by itself."""
    hass.states.async_set(PERSON_A, STATE_HOME)
    await setup_entry(hass, tracker_entry)

    await open_prompt(hass, SWITCH_A)

    state = hass.states.get(SWITCH_A)
    assert state.state == STATE_OFF
    assert state.attributes[ATTR_PROMPT_OPEN] is True
    expires_at = tracker_entry.runtime_data.manager.prompt_expires_at(TRACKER_A)
    assert state.attributes[ATTR_PROMPT_EXPIRES_AT] == expires_at.isoformat()
    assert hass.states.get(EVENT_A).attributes[ATTR_EVENT_TYPE] == EVENT_PROMPT_STARTED
    # The other tracker is not asked about.
    assert hass.states.get(SWITCH_B).attributes[ATTR_PROMPT_OPEN] is False

    await answer(hass, SWITCH_A, **{ATTR_ANSWER: ANSWER_NO})


async def test_opening_a_prompt_that_is_already_open(
    hass: HomeAssistant, asking_entry: MockConfigEntry
) -> None:
    """A tracker that is already being asked about is not asked about twice."""
    await ask(hass, asking_entry)
    expires_at = hass.states.get(SWITCH_A).attributes[ATTR_PROMPT_EXPIRES_AT]

    with pytest.raises(ServiceValidationError) as err:
        await open_prompt(hass, SWITCH_A)

    assert err.value.translation_key == "prompt_already_open"
    assert hass.states.get(SWITCH_A).attributes[ATTR_PROMPT_EXPIRES_AT] == expires_at

    await answer(hass, SWITCH_A, **{ATTR_ANSWER: ANSWER_NO})


async def test_opening_a_prompt_for_a_tracker_at_home(
    hass: HomeAssistant, tracker_entry: MockConfigEntry
) -> None:
    """Somebody who is at home is not asked about at all."""
    await setup_entry(hass, tracker_entry)
    await call_switch(hass, SERVICE_TURN_ON, SWITCH_A)

    with pytest.raises(ServiceValidationError) as err:
        await open_prompt(hass, SWITCH_A)

    assert err.value.translation_key == "tracker_already_home"
    assert hass.states.get(SWITCH_A).state == STATE_ON
    assert hass.states.get(SWITCH_A).attributes[ATTR_PROMPT_OPEN] is False


async def test_the_answer_only_reaches_our_switches(
    hass: HomeAssistant, asking_entry: MockConfigEntry
) -> None:
    """A target that is not one of our switches answers nothing."""
    await ask(hass, asking_entry)
    hass.states.async_set("switch.somebody_elses", STATE_OFF)

    await answer(hass, "switch.somebody_elses", **{ATTR_ANSWER: ANSWER_YES})

    assert asking_entry.runtime_data.manager.prompt_open(TRACKER_A) is True
    assert hass.states.get(SWITCH_A).state == STATE_OFF

    await answer(hass, SWITCH_A, **{ATTR_ANSWER: ANSWER_NO})


async def test_the_switch_shows_an_open_reminder(
    hass: HomeAssistant, tracker_entry: MockConfigEntry
) -> None:
    """While a tracker is being reminded about, its switch says so."""
    await remind(hass, tracker_entry)

    state = hass.states.get(SWITCH_A)
    assert state.state == STATE_ON
    assert state.attributes[ATTR_REMINDER_OPEN] is True
    expires_at = tracker_entry.runtime_data.manager.reminder_expires_at(TRACKER_A)
    assert state.attributes[ATTR_REMINDER_EXPIRES_AT] == expires_at.isoformat()
    # The prompt attributes are untouched by it.
    assert state.attributes[ATTR_PROMPT_OPEN] is False
    # The tracker that was not asked about is untouched too.
    assert hass.states.get(SWITCH_B).attributes[ATTR_REMINDER_OPEN] is False

    await answer_reminder(hass, SWITCH_A, **{ATTR_ANSWER: ANSWER_YES})

    state = hass.states.get(SWITCH_A)
    assert state.attributes[ATTR_REMINDER_OPEN] is False
    assert state.attributes[ATTR_REMINDER_EXPIRES_AT] is None


async def test_opening_the_reminder_from_the_action(
    hass: HomeAssistant, tracker_entry: MockConfigEntry
) -> None:
    """The action asks about a tracker that has no interval set at all."""
    await remind(hass, tracker_entry)

    assert hass.states.get(EVENT_A).attributes[ATTR_EVENT_TYPE] == (
        EVENT_REMINDER_STARTED
    )
    # Nothing was written to the tracker's options by asking.
    assert dict(tracker_entry.subentries[TRACKER_A].data) == {}

    await answer_reminder(hass, SWITCH_A, **{ATTR_ANSWER: ANSWER_YES})


async def test_answering_the_reminder_with_yes_keeps_the_tracker_on(
    hass: HomeAssistant, tracker_entry: MockConfigEntry
) -> None:
    """A yes leaves everything as it is and names who answered."""
    await remind(hass, tracker_entry)

    await answer_reminder(
        hass, SWITCH_A, **{ATTR_ANSWER: ANSWER_YES, ATTR_ANSWERED_BY: PERSON_A}
    )

    assert hass.states.get(SWITCH_A).state == STATE_ON
    assert hass.states.get(TRACKER_A_ENTITY).state == STATE_HOME
    state = hass.states.get(EVENT_A)
    assert state.attributes[ATTR_EVENT_TYPE] == EVENT_REMINDER_ANSWERED_YES
    assert state.attributes[ATTR_ANSWERED_BY] == PERSON_A


async def test_answering_the_reminder_with_no_switches_the_tracker_off(
    hass: HomeAssistant, tracker_entry: MockConfigEntry
) -> None:
    """A no does what the user would have done by hand."""
    await remind(hass, tracker_entry)

    await answer_reminder(hass, SWITCH_A, **{ATTR_ANSWER: ANSWER_NO})

    assert hass.states.get(SWITCH_A).state == STATE_OFF
    assert hass.states.get(TRACKER_A_ENTITY).state == STATE_NOT_HOME
    state = hass.states.get(EVENT_A)
    assert state.attributes[ATTR_EVENT_TYPE] == EVENT_REMINDER_ANSWERED_NO
    assert state.attributes[ATTR_ANSWERED_BY] is None


async def test_answering_a_tracker_that_was_not_reminded_about(
    hass: HomeAssistant, tracker_entry: MockConfigEntry
) -> None:
    """Without an open reminder the answer is refused with a clear message."""
    await remind(hass, tracker_entry)

    with pytest.raises(ServiceValidationError) as err:
        await answer_reminder(hass, SWITCH_B, **{ATTR_ANSWER: ANSWER_NO})

    assert err.value.translation_key == "no_open_reminder"
    # The other tracker's reminder is untouched by the failed call.
    assert tracker_entry.runtime_data.manager.reminder_open(TRACKER_A) is True

    await answer_reminder(hass, SWITCH_A, **{ATTR_ANSWER: ANSWER_YES})


async def test_opening_a_reminder_for_a_tracker_that_is_away(
    hass: HomeAssistant, tracker_entry: MockConfigEntry
) -> None:
    """Nobody is reminded about somebody who is not marked as being at home."""
    await setup_entry(hass, tracker_entry)

    with pytest.raises(ServiceValidationError) as err:
        await open_reminder(hass, SWITCH_A)

    assert err.value.translation_key == "tracker_not_home"
    assert hass.states.get(SWITCH_A).attributes[ATTR_REMINDER_OPEN] is False


async def test_opening_a_reminder_that_is_already_open(
    hass: HomeAssistant, tracker_entry: MockConfigEntry
) -> None:
    """A tracker that is already being reminded about is not asked twice."""
    await remind(hass, tracker_entry)
    expires_at = hass.states.get(SWITCH_A).attributes[ATTR_REMINDER_EXPIRES_AT]

    with pytest.raises(ServiceValidationError) as err:
        await open_reminder(hass, SWITCH_A)

    assert err.value.translation_key == "reminder_already_open"
    assert hass.states.get(SWITCH_A).attributes[ATTR_REMINDER_EXPIRES_AT] == expires_at

    await answer_reminder(hass, SWITCH_A, **{ATTR_ANSWER: ANSWER_YES})


@pytest.mark.parametrize(
    "data",
    [
        {},
        {ATTR_ANSWER: "maybe"},
        {ATTR_ANSWER: ANSWER_YES, ATTR_ANSWERED_BY: "light.kitchen"},
    ],
)
async def test_the_reminder_answer_is_validated(
    hass: HomeAssistant, tracker_entry: MockConfigEntry, data: dict[str, Any]
) -> None:
    """The action only takes yes or no, and only a person as the answerer."""
    await remind(hass, tracker_entry)

    with pytest.raises(vol.Invalid):
        await answer_reminder(hass, SWITCH_A, **data)

    assert tracker_entry.runtime_data.manager.reminder_open(TRACKER_A) is True

    await answer_reminder(hass, SWITCH_A, **{ATTR_ANSWER: ANSWER_YES})


@pytest.mark.parametrize(
    "data",
    [
        {},
        {ATTR_ANSWER: "maybe"},
        {ATTR_ANSWER: ANSWER_YES, ATTR_ANSWERED_BY: "light.kitchen"},
    ],
)
async def test_the_answer_is_validated(
    hass: HomeAssistant, asking_entry: MockConfigEntry, data: dict[str, Any]
) -> None:
    """The action only takes yes or no, and only a person as the answerer."""
    await ask(hass, asking_entry)

    with pytest.raises(vol.Invalid):
        await answer(hass, SWITCH_A, **data)

    assert asking_entry.runtime_data.manager.prompt_open(TRACKER_A) is True

    await answer(hass, SWITCH_A, **{ATTR_ANSWER: ANSWER_NO})
