"""Tests for the prompt event entity of a virtual tracker."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.virtual_presence_tracker.const import (
    ATTR_EXPIRES_AT,
    ATTR_PROMPT_ID,
    ATTR_REASON,
    ATTR_REMINDER_ID,
    ATTR_TRACKER,
    CONF_ASK_ON_DEPARTURE,
    CONF_PERSONS,
    CONF_REMIND_AFTER,
    DOMAIN,
    EVENT_CANCELLED,
    EVENT_EXPIRED,
    EVENT_PROMPT_STARTED,
    EVENT_REMINDER_CANCELLED,
    EVENT_REMINDER_EXPIRED,
    EVENT_REMINDER_STARTED,
    REASON_PERSON_HOME,
    REASON_SWITCHED_OFF,
    STORAGE_KEY_PREFIX,
    STORAGE_VERSION,
    SUBENTRY_TYPE_TRACKER,
    TRACKER_EVENT_TYPES,
)
from homeassistant.components.event import ATTR_EVENT_TYPE, ATTR_EVENT_TYPES
from homeassistant.const import (
    ATTR_FRIENDLY_NAME,
    STATE_HOME,
    STATE_NOT_HOME,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util

ENTRY_ID = "01JVPT0000000000000000ENTRY"
STORE_KEY = f"{STORAGE_KEY_PREFIX}.{ENTRY_ID}"

PERSON_A = "person.dabo53ck"

TRACKER_A = "01JVPT000000000000000TRACKA"
TRACKER_B = "01JVPT000000000000000TRACKB"

EVENT_A = "event.kid_prompt"
EVENT_B = "event.granny_prompt"
SWITCH_A = "switch.kid_at_home"


def make_entry(*, asking: bool = True, remind_after: int = 0) -> MockConfigEntry:
    """Return an entry with two trackers, asking or not."""
    data: dict[str, Any] = {CONF_ASK_ON_DEPARTURE: asking}
    if remind_after:
        data[CONF_REMIND_AFTER] = remind_after
    return MockConfigEntry(
        domain=DOMAIN,
        title="Virtual Presence Tracker",
        entry_id=ENTRY_ID,
        data={CONF_PERSONS: [PERSON_A]},
        subentries_data=[
            {
                "data": data,
                "subentry_id": subentry_id,
                "subentry_type": SUBENTRY_TYPE_TRACKER,
                "title": title,
                "unique_id": None,
            }
            for subentry_id, title in ((TRACKER_A, "Kid"), (TRACKER_B, "Granny"))
        ],
    )


def stored_prompt(minutes_left: float) -> dict[str, Any]:
    """Return a storage payload with one open prompt for the first tracker."""
    now = dt_util.utcnow()
    return {
        "version": STORAGE_VERSION,
        "minor_version": 1,
        "key": STORE_KEY,
        "data": {
            "trackers": {TRACKER_A: {"home": False, "since": None}},
            "prompts": {
                TRACKER_A: {
                    "prompt_id": "abc",
                    "started_at": (now - timedelta(minutes=10)).isoformat(),
                    "expires_at": (now + timedelta(minutes=minutes_left)).isoformat(),
                }
            },
        },
    }


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> MockConfigEntry:
    """Add a config entry to hass and set it up."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def unload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Unload an entry so that no prompt timer is left running."""
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def empty_the_house(hass: HomeAssistant) -> None:
    """Send the only real person away."""
    hass.states.async_set(PERSON_A, STATE_NOT_HOME)
    await hass.async_block_till_done()


async def test_one_event_entity_per_tracker(hass: HomeAssistant) -> None:
    """Every tracker gets an event entity on its own device."""
    hass.states.async_set(PERSON_A, STATE_HOME)
    await setup_entry(hass, make_entry())

    registry = er.async_get(hass)
    entity_entry = registry.async_get(EVENT_A)
    assert entity_entry is not None
    assert entity_entry.unique_id == f"{TRACKER_A}_prompt"
    assert entity_entry.config_subentry_id == TRACKER_A

    # The same device as the switch of that tracker.
    device = dr.async_get(hass).async_get(entity_entry.device_id)
    assert device is not None
    assert device.identifiers == {(DOMAIN, TRACKER_A)}
    assert device.id == registry.async_get(SWITCH_A).device_id

    state = hass.states.get(EVENT_A)
    assert state is not None
    assert state.state == STATE_UNKNOWN
    assert state.attributes[ATTR_FRIENDLY_NAME] == "Kid Prompt"
    # One entity for both questions about the tracker: the prompt and the
    # reminder, each with its own event types.
    assert state.attributes[ATTR_EVENT_TYPES] == TRACKER_EVENT_TYPES
    assert hass.states.get(EVENT_B) is not None


async def test_the_prompt_reaches_the_event_entity(hass: HomeAssistant) -> None:
    """A prompt is published with its ID, its tracker and its deadline."""
    hass.states.async_set(PERSON_A, STATE_HOME)
    entry = await setup_entry(hass, make_entry())

    await empty_the_house(hass)

    state = hass.states.get(EVENT_A)
    assert state.attributes[ATTR_EVENT_TYPE] == EVENT_PROMPT_STARTED
    assert state.attributes[ATTR_TRACKER] == "Kid"
    assert state.attributes[ATTR_PROMPT_ID]
    assert (
        state.attributes[ATTR_EXPIRES_AT]
        == entry.runtime_data.manager.prompt_expires_at(TRACKER_A).isoformat()
    )
    # Both trackers are asked about, each through its own entity.
    assert hass.states.get(EVENT_B).attributes[ATTR_TRACKER] == "Granny"

    await unload(hass, entry)


async def test_no_event_without_the_option(hass: HomeAssistant) -> None:
    """A tracker that does not ask never publishes anything."""
    hass.states.async_set(PERSON_A, STATE_HOME)
    await setup_entry(hass, make_entry(asking=False))

    await empty_the_house(hass)

    assert hass.states.get(EVENT_A).state == STATE_UNKNOWN


async def test_a_cancelled_prompt_is_published(hass: HomeAssistant) -> None:
    """The reason a prompt was taken back is part of the event."""
    hass.states.async_set(PERSON_A, STATE_HOME)
    await setup_entry(hass, make_entry())

    await empty_the_house(hass)
    hass.states.async_set(PERSON_A, STATE_HOME)
    await hass.async_block_till_done()

    state = hass.states.get(EVENT_A)
    assert state.attributes[ATTR_EVENT_TYPE] == EVENT_CANCELLED
    assert state.attributes[ATTR_REASON] == REASON_PERSON_HOME


async def test_a_reload_keeps_an_open_prompt(hass: HomeAssistant) -> None:
    """Reloading the entry - what a subentry change does - keeps the prompt."""
    hass.states.async_set(PERSON_A, STATE_HOME)
    entry = await setup_entry(hass, make_entry())

    await empty_the_house(hass)
    prompt_id = hass.states.get(EVENT_A).attributes[ATTR_PROMPT_ID]
    expires_at = entry.runtime_data.manager.prompt_expires_at(TRACKER_A)

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    manager = entry.runtime_data.manager
    assert manager.prompt_open(TRACKER_A) is True
    assert manager.prompt_expires_at(TRACKER_A) == expires_at
    # The prompt continues, so nothing new was published about it.
    state = hass.states.get(EVENT_A)
    assert state.attributes[ATTR_EVENT_TYPE] == EVENT_PROMPT_STARTED
    assert state.attributes[ATTR_PROMPT_ID] == prompt_id

    await unload(hass, entry)


async def test_a_resumed_prompt_can_still_be_answered(
    hass: HomeAssistant, hass_storage: dict[str, Any], freezer: FrozenDateTimeFactory
) -> None:
    """A prompt that survived a restart keeps the time it has left."""
    hass_storage[STORE_KEY] = stored_prompt(minutes_left=2)
    hass.states.async_set(PERSON_A, STATE_NOT_HOME)
    entry = await setup_entry(hass, make_entry())

    assert entry.runtime_data.manager.prompt_open(TRACKER_A) is True
    assert hass.states.get(EVENT_A).state == STATE_UNKNOWN
    assert hass.states.get(SWITCH_A).attributes["prompt_open"] is True

    freezer.tick(timedelta(minutes=3))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    state = hass.states.get(EVENT_A)
    assert state.attributes[ATTR_EVENT_TYPE] == EVENT_EXPIRED
    assert state.attributes[ATTR_PROMPT_ID] == "abc"


async def test_a_prompt_that_expired_while_off_is_published(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """The catch-up event needs the entity, so it is fired after the platforms."""
    hass_storage[STORE_KEY] = stored_prompt(minutes_left=-5)
    hass.states.async_set(PERSON_A, STATE_NOT_HOME)
    await setup_entry(hass, make_entry())

    state = hass.states.get(EVENT_A)
    assert state.attributes[ATTR_EVENT_TYPE] == EVENT_EXPIRED
    assert state.attributes[ATTR_PROMPT_ID] == "abc"
    assert state.attributes[ATTR_TRACKER] == "Kid"


async def test_a_prompt_is_taken_back_when_somebody_is_home_again(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """Coming home while Home Assistant was off answers the prompt."""
    hass_storage[STORE_KEY] = stored_prompt(minutes_left=5)
    hass.states.async_set(PERSON_A, STATE_HOME)
    await setup_entry(hass, make_entry())

    state = hass.states.get(EVENT_A)
    assert state.attributes[ATTR_EVENT_TYPE] == EVENT_CANCELLED
    assert state.attributes[ATTR_REASON] == REASON_PERSON_HOME


def stored_reminder(
    *, minutes_left: float | None, hours_at_home: float, home: bool = True
) -> dict[str, Any]:
    """Return a storage payload for the first tracker, with or without a reminder."""
    now = dt_util.utcnow()
    at_home = (now - timedelta(hours=hours_at_home)).isoformat()
    data: dict[str, Any] = {
        "trackers": {TRACKER_A: {"home": home, "since": at_home, "anchor": at_home}}
    }
    if minutes_left is not None:
        data["reminders"] = {
            TRACKER_A: {
                "reminder_id": "rem",
                "started_at": (now - timedelta(minutes=1)).isoformat(),
                "expires_at": (now + timedelta(minutes=minutes_left)).isoformat(),
            }
        }
    return {
        "version": STORAGE_VERSION,
        "minor_version": 1,
        "key": STORE_KEY,
        "data": data,
    }


async def test_the_reminder_reaches_the_event_entity(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """A reminder is published with its own ID, its tracker and its deadline."""
    hass_storage[STORE_KEY] = stored_reminder(minutes_left=None, hours_at_home=5)
    hass.states.async_set(PERSON_A, STATE_NOT_HOME)
    entry = await setup_entry(hass, make_entry(asking=False, remind_after=2))

    state = hass.states.get(EVENT_A)
    assert state.attributes[ATTR_EVENT_TYPE] == EVENT_REMINDER_STARTED
    assert state.attributes[ATTR_TRACKER] == "Kid"
    assert state.attributes[ATTR_REMINDER_ID]
    assert (
        state.attributes[ATTR_EXPIRES_AT]
        == entry.runtime_data.manager.reminder_expires_at(TRACKER_A).isoformat()
    )
    # The reminder is not a prompt and never claims to be one.
    assert ATTR_PROMPT_ID not in state.attributes
    # The second tracker was never at home, so nothing was said about it.
    assert hass.states.get(EVENT_B).state == STATE_UNKNOWN

    await unload(hass, entry)


async def test_a_reminder_that_expired_while_off_is_published(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """The catch-up event needs the entity, so it is fired after the platforms."""
    hass_storage[STORE_KEY] = stored_reminder(minutes_left=-5, hours_at_home=5)
    hass.states.async_set(PERSON_A, STATE_NOT_HOME)
    entry = await setup_entry(hass, make_entry(asking=False, remind_after=2))

    state = hass.states.get(EVENT_A)
    assert state.attributes[ATTR_EVENT_TYPE] == EVENT_REMINDER_EXPIRED
    assert state.attributes[ATTR_REMINDER_ID] == "rem"
    assert state.attributes[ATTR_TRACKER] == "Kid"

    await unload(hass, entry)


async def test_a_reminder_is_taken_back_when_the_tracker_is_off(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """A tracker switched off while Home Assistant was down loses its reminder."""
    hass_storage[STORE_KEY] = stored_reminder(
        minutes_left=5, hours_at_home=5, home=False
    )
    hass.states.async_set(PERSON_A, STATE_NOT_HOME)
    await setup_entry(hass, make_entry(asking=False, remind_after=2))

    state = hass.states.get(EVENT_A)
    assert state.attributes[ATTR_EVENT_TYPE] == EVENT_REMINDER_CANCELLED
    assert state.attributes[ATTR_REASON] == REASON_SWITCHED_OFF
