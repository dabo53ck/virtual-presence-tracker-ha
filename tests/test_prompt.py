"""Tests for the prompt state machine of the household manager."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.virtual_presence_tracker.const import (
    ATTR_ANSWERED_BY,
    ATTR_EXPIRES_AT,
    ATTR_PROMPT_ID,
    ATTR_REASON,
    ATTR_TRACKER,
    CONF_ANSWER_TIMEOUT,
    CONF_ASK_ON_DEPARTURE,
    CONF_PERSONS,
    CONF_PROMPT_DELAY,
    CONF_RESET_ON_RETURN,
    DOMAIN,
    EVENT_ANSWERED_NO,
    EVENT_ANSWERED_YES,
    EVENT_CANCELLED,
    EVENT_EXPIRED,
    EVENT_PROMPT_STARTED,
    REASON_OPTION_DISABLED,
    REASON_PERSON_HOME,
    REASON_SWITCHED_ON,
    STORAGE_KEY_PREFIX,
    STORAGE_VERSION,
    SUBENTRY_TYPE_TRACKER,
)
from custom_components.virtual_presence_tracker.manager import (
    HouseholdManager,
    OpenPromptResult,
)
from homeassistant.const import STATE_HOME, STATE_NOT_HOME, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

ENTRY_ID = "01JVPT0000000000000000ENTRY"
STORE_KEY = f"{STORAGE_KEY_PREFIX}.{ENTRY_ID}"

PERSON_A = "person.dabo53ck"
PERSON_B = "person.king53ck"

TRACKER_A = "01JVPT000000000000000TRACKA"
TRACKER_B = "01JVPT000000000000000TRACKB"

ASKING = {CONF_ASK_ON_DEPARTURE: True}


def make_subentry(subentry_id: str, title: str, **data: Any) -> dict[str, Any]:
    """Return subentry data for one virtual tracker."""
    return {
        "data": data,
        "subentry_id": subentry_id,
        "subentry_type": SUBENTRY_TYPE_TRACKER,
        "title": title,
        "unique_id": None,
    }


def make_entry(
    *subentries: dict[str, Any], persons: list[str] | None = None
) -> MockConfigEntry:
    """Return a config entry with the given real persons and trackers."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Virtual Presence Tracker",
        entry_id=ENTRY_ID,
        data={CONF_PERSONS: persons if persons is not None else [PERSON_A]},
        subentries_data=subentries or (make_subentry(TRACKER_A, "Kid", **ASKING),),
    )


def stored(
    trackers: dict[str, dict[str, Any]],
    prompts: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return a storage payload as the manager writes it."""
    data: dict[str, Any] = {"trackers": trackers}
    if prompts is not None:
        data["prompts"] = prompts
    return {
        "version": STORAGE_VERSION,
        "minor_version": 1,
        "key": STORE_KEY,
        "data": data,
    }


class Recorder:
    """Collect the prompt events of one virtual tracker."""

    def __init__(self, manager: HouseholdManager, subentry_id: str) -> None:
        """Subscribe to the prompt events of a tracker."""
        self.events: list[tuple[str, dict[str, Any]]] = []
        manager.async_add_prompt_listener(subentry_id, self._record)

    def _record(self, event_type: str, data: dict[str, Any]) -> None:
        """Remember one event."""
        self.events.append((event_type, dict(data)))

    @property
    def types(self) -> list[str]:
        """Return the types of the events seen so far."""
        return [event_type for event_type, _ in self.events]

    def only(self, event_type: str) -> dict[str, Any]:
        """Return the data of the single event seen, asserting its type."""
        assert self.types == [event_type]
        return self.events[0][1]


async def start_manager(
    hass: HomeAssistant, entry: MockConfigEntry
) -> HouseholdManager:
    """Return a loaded and started manager for the entry.

    Resuming is left to the caller: it happens after the platforms are set up,
    and a test that wants to see a catch-up event has to subscribe first.
    """
    entry.add_to_hass(hass)
    manager = HouseholdManager(hass, entry)
    await manager.async_load()
    manager.async_start()
    return manager


async def set_person(hass: HomeAssistant, entity_id: str, state: str) -> None:
    """Set a person state and let the manager process it."""
    hass.states.async_set(entity_id, state)
    await hass.async_block_till_done()


async def leave(hass: HomeAssistant, *persons: str) -> None:
    """Send the given persons away, one after the other."""
    for entity_id in persons:
        await set_person(hass, entity_id, STATE_NOT_HOME)


async def tick(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: float
) -> None:
    """Let the given number of seconds pass and run what was due."""
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_the_last_departure_opens_a_prompt(hass: HomeAssistant) -> None:
    """The prompt opens with no delay and announces when it gives up."""
    hass.states.async_set(PERSON_A, STATE_HOME)
    manager = await start_manager(hass, make_entry())
    events = Recorder(manager, TRACKER_A)

    await leave(hass, PERSON_A)

    data = events.only(EVENT_PROMPT_STARTED)
    assert data[ATTR_PROMPT_ID]
    assert data[ATTR_TRACKER] == "Kid"
    assert data[ATTR_EXPIRES_AT] == manager.prompt_expires_at(TRACKER_A).isoformat()
    assert manager.prompt_open(TRACKER_A) is True
    # Asking changes nothing by itself.
    assert manager.is_home(TRACKER_A) is False

    await manager.async_stop()


async def test_no_prompt_without_the_option(hass: HomeAssistant) -> None:
    """A tracker that does not ask is left alone entirely."""
    hass.states.async_set(PERSON_A, STATE_HOME)
    manager = await start_manager(hass, make_entry(make_subentry(TRACKER_A, "Kid")))
    events = Recorder(manager, TRACKER_A)

    await leave(hass, PERSON_A)

    assert events.types == []
    assert manager.prompt_open(TRACKER_A) is False
    assert manager.prompt_expires_at(TRACKER_A) is None


async def test_no_prompt_while_the_tracker_is_home(hass: HomeAssistant) -> None:
    """Nobody has to be asked about somebody who is already home."""
    hass.states.async_set(PERSON_A, STATE_HOME)
    manager = await start_manager(hass, make_entry())
    manager.async_set_home(TRACKER_A, True)
    events = Recorder(manager, TRACKER_A)

    await leave(hass, PERSON_A)

    assert events.types == []
    assert manager.prompt_open(TRACKER_A) is False


async def test_no_prompt_while_somebody_real_is_left(hass: HomeAssistant) -> None:
    """Only the departure that empties the house asks."""
    hass.states.async_set(PERSON_A, STATE_HOME)
    hass.states.async_set(PERSON_B, STATE_HOME)
    manager = await start_manager(hass, make_entry(persons=[PERSON_A, PERSON_B]))
    events = Recorder(manager, TRACKER_A)

    await leave(hass, PERSON_A)
    assert events.types == []

    await leave(hass, PERSON_B)
    assert events.types == [EVENT_PROMPT_STARTED]

    await manager.async_stop()


@pytest.mark.parametrize("first", [STATE_UNKNOWN, None])
async def test_no_prompt_from_an_unknown_state(
    hass: HomeAssistant, first: str | None
) -> None:
    """A person who was never known to be home cannot leave one.

    That is what a Home Assistant start looks like: the person entity appears,
    or recovers from ``unknown``, and its first known state is ``not_home``.
    """
    if first is not None:
        hass.states.async_set(PERSON_A, first)
    manager = await start_manager(hass, make_entry())
    events = Recorder(manager, TRACKER_A)

    await leave(hass, PERSON_A)

    assert events.types == []
    assert manager.real_home is False
    assert manager.prompt_open(TRACKER_A) is False


async def test_the_delay_postpones_the_prompt(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """With a delay the prompt only opens once the delay is over."""
    hass.states.async_set(PERSON_A, STATE_HOME)
    manager = await start_manager(
        hass,
        make_entry(
            make_subentry(TRACKER_A, "Kid", **ASKING, **{CONF_PROMPT_DELAY: 60})
        ),
    )
    events = Recorder(manager, TRACKER_A)

    await leave(hass, PERSON_A)
    await tick(hass, freezer, 30)

    assert events.types == []
    assert manager.prompt_open(TRACKER_A) is False

    await tick(hass, freezer, 31)

    assert events.types == [EVENT_PROMPT_STARTED]
    assert manager.prompt_open(TRACKER_A) is True

    await manager.async_stop()


async def test_the_delay_is_rechecked(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Somebody coming home during the delay stops the prompt silently.

    Nothing was announced yet, so there is nothing to take back either.
    """
    hass.states.async_set(PERSON_A, STATE_HOME)
    manager = await start_manager(
        hass,
        make_entry(
            make_subentry(TRACKER_A, "Kid", **ASKING, **{CONF_PROMPT_DELAY: 60})
        ),
    )
    events = Recorder(manager, TRACKER_A)

    await leave(hass, PERSON_A)
    await set_person(hass, PERSON_A, STATE_HOME)
    await tick(hass, freezer, 61)

    assert events.types == []
    assert manager.prompt_open(TRACKER_A) is False


async def test_opening_a_prompt_by_hand(hass: HomeAssistant) -> None:
    """Asked for it, the prompt opens on the spot and behaves like any other."""
    hass.states.async_set(PERSON_A, STATE_NOT_HOME)
    manager = await start_manager(
        hass,
        make_entry(
            make_subentry(TRACKER_A, "Kid", **ASKING, **{CONF_ANSWER_TIMEOUT: 5})
        ),
    )
    events = Recorder(manager, TRACKER_A)

    assert manager.async_open_prompt(TRACKER_A) is OpenPromptResult.OPENED

    data = events.only(EVENT_PROMPT_STARTED)
    assert data[ATTR_TRACKER] == "Kid"
    expires_at = manager.prompt_expires_at(TRACKER_A)
    assert data[ATTR_EXPIRES_AT] == expires_at.isoformat()
    # It is the tracker's own answer time, not one of its own.
    assert expires_at - dt_util.utcnow() <= timedelta(minutes=5)
    assert manager.prompt_open(TRACKER_A) is True
    assert manager.is_home(TRACKER_A) is False

    await manager.async_stop()


async def test_opening_by_hand_ignores_the_option(hass: HomeAssistant) -> None:
    """The option governs the automatic asking, not the asking by hand."""
    hass.states.async_set(PERSON_A, STATE_NOT_HOME)
    manager = await start_manager(hass, make_entry(make_subentry(TRACKER_A, "Kid")))
    events = Recorder(manager, TRACKER_A)

    assert manager.async_open_prompt(TRACKER_A) is OpenPromptResult.OPENED

    assert events.types == [EVENT_PROMPT_STARTED]
    assert manager.prompt_open(TRACKER_A) is True

    await manager.async_stop()


async def test_opening_by_hand_ignores_a_real_person_at_home(
    hass: HomeAssistant,
) -> None:
    """Somebody can be asked about while the house is anything but empty."""
    hass.states.async_set(PERSON_A, STATE_HOME)
    manager = await start_manager(hass, make_entry())
    events = Recorder(manager, TRACKER_A)

    assert manager.async_open_prompt(TRACKER_A) is OpenPromptResult.OPENED

    assert events.types == [EVENT_PROMPT_STARTED]
    assert manager.real_home is True

    await manager.async_stop()


async def test_opening_by_hand_takes_over_a_scheduled_prompt(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Asking now means now, and the prompt that was waiting becomes this one."""
    hass.states.async_set(PERSON_A, STATE_HOME)
    manager = await start_manager(
        hass,
        make_entry(
            make_subentry(TRACKER_A, "Kid", **ASKING, **{CONF_PROMPT_DELAY: 60})
        ),
    )
    events = Recorder(manager, TRACKER_A)

    await leave(hass, PERSON_A)
    assert events.types == []

    assert manager.async_open_prompt(TRACKER_A) is OpenPromptResult.OPENED
    prompt_id = events.only(EVENT_PROMPT_STARTED)[ATTR_PROMPT_ID]

    # The delayed timer has nothing left to open: same prompt, one event.
    await tick(hass, freezer, 61)

    assert events.types == [EVENT_PROMPT_STARTED]
    assert events.events[0][1][ATTR_PROMPT_ID] == prompt_id
    assert manager.prompt_open(TRACKER_A) is True

    await manager.async_stop()


async def test_opening_by_hand_needs_a_tracker_that_is_away(
    hass: HomeAssistant,
) -> None:
    """Nobody is asked about somebody who is already at home."""
    hass.states.async_set(PERSON_A, STATE_NOT_HOME)
    manager = await start_manager(hass, make_entry())
    manager.async_set_home(TRACKER_A, True)
    events = Recorder(manager, TRACKER_A)

    assert manager.async_open_prompt(TRACKER_A) is OpenPromptResult.TRACKER_AT_HOME

    assert events.types == []
    assert manager.prompt_open(TRACKER_A) is False


async def test_opening_by_hand_never_asks_twice(hass: HomeAssistant) -> None:
    """A second attempt leaves the first prompt exactly as it was."""
    hass.states.async_set(PERSON_A, STATE_HOME)
    manager = await start_manager(hass, make_entry())
    events = Recorder(manager, TRACKER_A)

    manager.async_open_prompt(TRACKER_A)
    prompt_id = events.only(EVENT_PROMPT_STARTED)[ATTR_PROMPT_ID]
    expires_at = manager.prompt_expires_at(TRACKER_A)

    assert manager.async_open_prompt(TRACKER_A) is OpenPromptResult.PROMPT_OPEN

    assert events.types == [EVENT_PROMPT_STARTED]
    assert events.events[0][1][ATTR_PROMPT_ID] == prompt_id
    assert manager.prompt_expires_at(TRACKER_A) == expires_at

    await manager.async_stop()


async def test_a_manual_prompt_is_answered_like_any_other(
    hass: HomeAssistant,
) -> None:
    """Nothing downstream knows how the prompt was opened."""
    hass.states.async_set(PERSON_A, STATE_HOME)
    manager = await start_manager(hass, make_entry())
    events = Recorder(manager, TRACKER_A)

    manager.async_open_prompt(TRACKER_A)

    assert manager.async_answer_prompt(TRACKER_A, True, PERSON_A) is True

    assert manager.is_home(TRACKER_A) is True
    assert events.types == [EVENT_PROMPT_STARTED, EVENT_ANSWERED_YES]
    assert events.events[1][1][ATTR_ANSWERED_BY] == PERSON_A


async def test_a_manual_prompt_is_persisted_as_one(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """A prompt opened by hand is written down as such and read back as such."""
    hass.states.async_set(PERSON_A, STATE_HOME)
    entry = make_entry()
    manager = await start_manager(hass, entry)

    manager.async_open_prompt(TRACKER_A)
    await manager.async_stop()

    assert hass_storage[STORE_KEY]["data"]["prompts"][TRACKER_A]["manual"] is True

    restored = HouseholdManager(hass, entry)
    await restored.async_load()
    restored.async_start()
    events = Recorder(restored, TRACKER_A)

    # Somebody is at home, which would take an automatic prompt back.
    assert restored.real_home is True
    restored.async_resume_prompts()

    assert events.types == []
    assert restored.prompt_open(TRACKER_A) is True

    await restored.async_stop()


async def test_a_prompt_expires(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """An unanswered prompt gives up and leaves the tracker alone."""
    hass.states.async_set(PERSON_A, STATE_HOME)
    manager = await start_manager(
        hass,
        make_entry(
            make_subentry(TRACKER_A, "Kid", **ASKING, **{CONF_ANSWER_TIMEOUT: 5})
        ),
    )
    events = Recorder(manager, TRACKER_A)

    await leave(hass, PERSON_A)
    prompt_id = events.only(EVENT_PROMPT_STARTED)[ATTR_PROMPT_ID]

    await tick(hass, freezer, 4 * 60)
    assert events.types == [EVENT_PROMPT_STARTED]

    await tick(hass, freezer, 61)

    assert events.types == [EVENT_PROMPT_STARTED, EVENT_EXPIRED]
    assert events.events[1][1] == {ATTR_PROMPT_ID: prompt_id, ATTR_TRACKER: "Kid"}
    assert manager.prompt_open(TRACKER_A) is False
    assert manager.is_home(TRACKER_A) is False


async def test_answering_yes_sets_the_tracker_home(hass: HomeAssistant) -> None:
    """A yes ends the prompt and switches the tracker on, once."""
    hass.states.async_set(PERSON_A, STATE_HOME)
    manager = await start_manager(hass, make_entry())
    events = Recorder(manager, TRACKER_A)

    await leave(hass, PERSON_A)
    prompt_id = events.only(EVENT_PROMPT_STARTED)[ATTR_PROMPT_ID]

    assert manager.async_answer_prompt(TRACKER_A, True, PERSON_A) is True

    assert manager.is_home(TRACKER_A) is True
    assert manager.prompt_open(TRACKER_A) is False
    # Switching the tracker on is the answer, not a cancellation of the prompt.
    assert events.types == [EVENT_PROMPT_STARTED, EVENT_ANSWERED_YES]
    assert events.events[1][1] == {
        ATTR_PROMPT_ID: prompt_id,
        ATTR_TRACKER: "Kid",
        ATTR_ANSWERED_BY: PERSON_A,
    }


async def test_answering_no_changes_nothing(hass: HomeAssistant) -> None:
    """A no ends the prompt; the house keeps counting as empty."""
    hass.states.async_set(PERSON_A, STATE_HOME)
    manager = await start_manager(hass, make_entry())
    events = Recorder(manager, TRACKER_A)

    await leave(hass, PERSON_A)
    assert manager.async_answer_prompt(TRACKER_A, False) is True

    assert manager.is_home(TRACKER_A) is False
    assert manager.prompt_open(TRACKER_A) is False
    assert events.types == [EVENT_PROMPT_STARTED, EVENT_ANSWERED_NO]
    # Nobody was named, which is part of the contract.
    assert events.events[1][1][ATTR_ANSWERED_BY] is None


async def test_an_answered_prompt_does_not_expire_later(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Answering takes the timeout with it."""
    hass.states.async_set(PERSON_A, STATE_HOME)
    manager = await start_manager(hass, make_entry())
    events = Recorder(manager, TRACKER_A)

    await leave(hass, PERSON_A)
    manager.async_answer_prompt(TRACKER_A, False)

    await tick(hass, freezer, 11 * 60)

    assert events.types == [EVENT_PROMPT_STARTED, EVENT_ANSWERED_NO]


async def test_answering_without_a_prompt(hass: HomeAssistant) -> None:
    """Answering a tracker that was not asked about does nothing."""
    manager = await start_manager(hass, make_entry())
    events = Recorder(manager, TRACKER_A)

    assert manager.async_answer_prompt(TRACKER_A, True) is False

    assert events.types == []
    assert manager.is_home(TRACKER_A) is False


@pytest.mark.parametrize("reset_on_return", [True, False])
async def test_a_real_arrival_cancels_the_prompt(
    hass: HomeAssistant, reset_on_return: bool
) -> None:
    """Whoever comes home answers the question, reset option or not."""
    hass.states.async_set(PERSON_A, STATE_HOME)
    manager = await start_manager(
        hass,
        make_entry(
            make_subentry(
                TRACKER_A, "Kid", **ASKING, **{CONF_RESET_ON_RETURN: reset_on_return}
            )
        ),
    )
    events = Recorder(manager, TRACKER_A)

    await leave(hass, PERSON_A)
    await set_person(hass, PERSON_A, STATE_HOME)

    assert events.types == [EVENT_PROMPT_STARTED, EVENT_CANCELLED]
    assert events.events[1][1][ATTR_REASON] == REASON_PERSON_HOME
    assert manager.prompt_open(TRACKER_A) is False


async def test_a_first_known_arrival_cancels_the_prompt(hass: HomeAssistant) -> None:
    """A person who becomes known as home cancels too.

    Unlike the reset, the cancellation does not care whether the person was
    known to be away before: they are at home, so the question is answered.
    """
    hass.states.async_set(PERSON_A, STATE_HOME)
    manager = await start_manager(hass, make_entry(persons=[PERSON_A, PERSON_B]))
    events = Recorder(manager, TRACKER_A)

    await leave(hass, PERSON_A)
    assert events.types == [EVENT_PROMPT_STARTED]

    # king53ck's state was never known before.
    await set_person(hass, PERSON_B, STATE_HOME)

    assert events.types == [EVENT_PROMPT_STARTED, EVENT_CANCELLED]
    assert events.events[1][1][ATTR_REASON] == REASON_PERSON_HOME


async def test_switching_the_tracker_on_cancels_the_prompt(
    hass: HomeAssistant,
) -> None:
    """Switching the tracker on by hand answers the prompt its own way."""
    hass.states.async_set(PERSON_A, STATE_HOME)
    manager = await start_manager(hass, make_entry())
    events = Recorder(manager, TRACKER_A)

    await leave(hass, PERSON_A)
    manager.async_set_home(TRACKER_A, True)

    assert events.types == [EVENT_PROMPT_STARTED, EVENT_CANCELLED]
    assert events.events[1][1][ATTR_REASON] == REASON_SWITCHED_ON
    assert manager.is_home(TRACKER_A) is True
    assert manager.prompt_open(TRACKER_A) is False


async def test_switching_on_cancels_a_scheduled_prompt(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A prompt still waiting for its delay is taken back as well."""
    hass.states.async_set(PERSON_A, STATE_HOME)
    manager = await start_manager(
        hass,
        make_entry(
            make_subentry(TRACKER_A, "Kid", **ASKING, **{CONF_PROMPT_DELAY: 60})
        ),
    )
    events = Recorder(manager, TRACKER_A)

    await leave(hass, PERSON_A)
    manager.async_set_home(TRACKER_A, True)

    assert events.types == [EVENT_CANCELLED]
    assert events.events[0][1][ATTR_REASON] == REASON_SWITCHED_ON
    # The cancelled prompt is named even though it never opened.
    assert events.events[0][1][ATTR_PROMPT_ID]

    await tick(hass, freezer, 61)
    assert events.types == [EVENT_CANCELLED]


async def test_switching_off_leaves_the_prompt_alone(hass: HomeAssistant) -> None:
    """Only switching a tracker *on* answers a prompt."""
    hass.states.async_set(PERSON_A, STATE_HOME)
    manager = await start_manager(hass, make_entry())
    events = Recorder(manager, TRACKER_A)

    await leave(hass, PERSON_A)
    manager.async_set_home(TRACKER_A, False)

    assert events.types == [EVENT_PROMPT_STARTED]
    assert manager.prompt_open(TRACKER_A) is True

    await manager.async_stop()


async def test_trackers_are_independent(hass: HomeAssistant) -> None:
    """Two trackers get their own prompt, their own ID and their own answer."""
    hass.states.async_set(PERSON_A, STATE_HOME)
    manager = await start_manager(
        hass,
        make_entry(
            make_subentry(TRACKER_A, "Kid", **ASKING),
            make_subentry(TRACKER_B, "Granny", **ASKING),
        ),
    )
    kid = Recorder(manager, TRACKER_A)
    granny = Recorder(manager, TRACKER_B)

    await leave(hass, PERSON_A)

    assert kid.only(EVENT_PROMPT_STARTED)[ATTR_TRACKER] == "Kid"
    assert granny.only(EVENT_PROMPT_STARTED)[ATTR_TRACKER] == "Granny"
    assert kid.events[0][1][ATTR_PROMPT_ID] != granny.events[0][1][ATTR_PROMPT_ID]

    manager.async_answer_prompt(TRACKER_A, True)

    assert manager.is_home(TRACKER_A) is True
    assert manager.is_home(TRACKER_B) is False
    assert granny.types == [EVENT_PROMPT_STARTED]
    assert manager.prompt_open(TRACKER_B) is True

    await manager.async_stop()


async def test_one_prompt_at_a_time(hass: HomeAssistant) -> None:
    """A second departure while a prompt is open changes nothing."""
    hass.states.async_set(PERSON_A, STATE_HOME)
    hass.states.async_set(PERSON_B, STATE_HOME)
    manager = await start_manager(hass, make_entry(persons=[PERSON_A, PERSON_B]))
    events = Recorder(manager, TRACKER_A)

    await leave(hass, PERSON_A, PERSON_B)
    prompt_id = events.only(EVENT_PROMPT_STARTED)[ATTR_PROMPT_ID]

    # king53ck comes back and leaves again while the prompt is open: the
    # cancellation is followed by a new prompt, not by a second one.
    await set_person(hass, PERSON_B, STATE_HOME)
    await leave(hass, PERSON_B)

    assert events.types == [EVENT_PROMPT_STARTED, EVENT_CANCELLED, EVENT_PROMPT_STARTED]
    assert events.events[2][1][ATTR_PROMPT_ID] != prompt_id

    await manager.async_stop()


async def test_an_open_prompt_is_persisted(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """An open prompt is written to the store and read back."""
    hass.states.async_set(PERSON_A, STATE_HOME)
    entry = make_entry()
    manager = await start_manager(hass, entry)
    events = Recorder(manager, TRACKER_A)

    await leave(hass, PERSON_A)
    prompt_id = events.only(EVENT_PROMPT_STARTED)[ATTR_PROMPT_ID]
    expires_at = manager.prompt_expires_at(TRACKER_A)
    await manager.async_stop()

    written = hass_storage[STORE_KEY]["data"]["prompts"][TRACKER_A]
    assert written["prompt_id"] == prompt_id
    assert written["expires_at"] == expires_at.isoformat()

    restored = HouseholdManager(hass, entry)
    await restored.async_load()

    assert restored.prompt_open(TRACKER_A) is True
    assert restored.prompt_expires_at(TRACKER_A) == expires_at


async def test_a_store_without_prompts_is_read(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """A store written before the prompt existed loads unchanged."""
    hass_storage[STORE_KEY] = stored({TRACKER_A: {"home": True, "since": None}})

    manager = await start_manager(hass, make_entry())

    assert manager.is_home(TRACKER_A) is True
    assert manager.prompt_open(TRACKER_A) is False


async def test_resume_keeps_the_remaining_time(
    hass: HomeAssistant, hass_storage: dict[str, Any], freezer: FrozenDateTimeFactory
) -> None:
    """A prompt that is still valid continues silently and can still expire."""
    now = dt_util.utcnow()
    hass_storage[STORE_KEY] = stored(
        {TRACKER_A: {"home": False, "since": None}},
        {
            TRACKER_A: {
                "prompt_id": "abc",
                "started_at": (now - timedelta(minutes=8)).isoformat(),
                "expires_at": (now + timedelta(minutes=2)).isoformat(),
            }
        },
    )
    hass.states.async_set(PERSON_A, STATE_NOT_HOME)
    manager = await start_manager(hass, make_entry())
    events = Recorder(manager, TRACKER_A)

    manager.async_resume_prompts()

    assert events.types == []
    assert manager.prompt_open(TRACKER_A) is True

    await tick(hass, freezer, 60)
    assert events.types == []

    await tick(hass, freezer, 61)

    assert events.types == [EVENT_EXPIRED]
    assert events.events[0][1][ATTR_PROMPT_ID] == "abc"


async def test_resume_gives_up_on_an_old_prompt(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """A prompt whose time ran out while Home Assistant was off expires."""
    now = dt_util.utcnow()
    hass_storage[STORE_KEY] = stored(
        {TRACKER_A: {"home": False, "since": None}},
        {
            TRACKER_A: {
                "prompt_id": "abc",
                "started_at": (now - timedelta(hours=3)).isoformat(),
                "expires_at": (now - timedelta(hours=2)).isoformat(),
            }
        },
    )
    hass.states.async_set(PERSON_A, STATE_NOT_HOME)
    manager = await start_manager(hass, make_entry())
    events = Recorder(manager, TRACKER_A)

    manager.async_resume_prompts()

    assert events.types == [EVENT_EXPIRED]
    assert manager.prompt_open(TRACKER_A) is False
    assert manager.is_home(TRACKER_A) is False


async def test_resume_cancels_when_somebody_is_home(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """Somebody who is home again while the prompt slept cancels it."""
    now = dt_util.utcnow()
    hass_storage[STORE_KEY] = stored(
        {TRACKER_A: {"home": False, "since": None}},
        {
            TRACKER_A: {
                "prompt_id": "abc",
                "started_at": now.isoformat(),
                "expires_at": (now + timedelta(minutes=10)).isoformat(),
            }
        },
    )
    hass.states.async_set(PERSON_A, STATE_HOME)
    manager = await start_manager(hass, make_entry())
    events = Recorder(manager, TRACKER_A)

    manager.async_resume_prompts()

    assert events.types == [EVENT_CANCELLED]
    assert events.events[0][1][ATTR_REASON] == REASON_PERSON_HOME
    assert manager.prompt_open(TRACKER_A) is False


async def test_resume_cancels_when_the_option_was_switched_off(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """Turning the option off reloads the entry, which takes the prompt back."""
    now = dt_util.utcnow()
    hass_storage[STORE_KEY] = stored(
        {TRACKER_A: {"home": False, "since": None}},
        {
            TRACKER_A: {
                "prompt_id": "abc",
                "started_at": now.isoformat(),
                "expires_at": (now + timedelta(minutes=10)).isoformat(),
            }
        },
    )
    hass.states.async_set(PERSON_A, STATE_NOT_HOME)
    manager = await start_manager(hass, make_entry(make_subentry(TRACKER_A, "Kid")))
    events = Recorder(manager, TRACKER_A)

    manager.async_resume_prompts()

    assert events.types == [EVENT_CANCELLED]
    assert events.events[0][1][ATTR_REASON] == REASON_OPTION_DISABLED
    assert manager.prompt_open(TRACKER_A) is False


@pytest.mark.parametrize("asking", [True, False])
async def test_resume_keeps_a_manual_prompt(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    asking: bool,
) -> None:
    """Neither the option nor somebody at home takes a manual prompt back.

    It was never opened because the house was empty, so the reasons that
    withdraw an automatic prompt after a restart do not apply to it. Its
    deadline still does.
    """
    now = dt_util.utcnow()
    hass_storage[STORE_KEY] = stored(
        {TRACKER_A: {"home": False, "since": None}},
        {
            TRACKER_A: {
                "prompt_id": "abc",
                "started_at": now.isoformat(),
                "expires_at": (now + timedelta(minutes=10)).isoformat(),
                "manual": True,
            }
        },
    )
    hass.states.async_set(PERSON_A, STATE_HOME)
    manager = await start_manager(
        hass, make_entry(make_subentry(TRACKER_A, "Kid", **(ASKING if asking else {})))
    )
    events = Recorder(manager, TRACKER_A)

    manager.async_resume_prompts()

    assert events.types == []
    assert manager.prompt_open(TRACKER_A) is True

    await tick(hass, freezer, 11 * 60)

    assert events.types == [EVENT_EXPIRED]
    assert events.events[0][1][ATTR_PROMPT_ID] == "abc"
    assert manager.prompt_open(TRACKER_A) is False


async def test_a_stored_prompt_without_the_manual_key_is_automatic(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """A prompt from before the flag existed is treated as an automatic one."""
    now = dt_util.utcnow()
    hass_storage[STORE_KEY] = stored(
        {TRACKER_A: {"home": False, "since": None}},
        {
            TRACKER_A: {
                "prompt_id": "abc",
                "started_at": now.isoformat(),
                "expires_at": (now + timedelta(minutes=10)).isoformat(),
            }
        },
    )
    hass.states.async_set(PERSON_A, STATE_HOME)
    manager = await start_manager(hass, make_entry())
    events = Recorder(manager, TRACKER_A)

    manager.async_resume_prompts()

    assert events.types == [EVENT_CANCELLED]
    assert events.events[0][1][ATTR_REASON] == REASON_PERSON_HOME
    assert manager.prompt_open(TRACKER_A) is False


async def test_the_prompt_of_a_removed_tracker_is_dropped(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """A prompt without a tracker disappears without a word."""
    now = dt_util.utcnow()
    hass_storage[STORE_KEY] = stored(
        {TRACKER_B: {"home": True, "since": None}},
        {
            TRACKER_B: {
                "prompt_id": "abc",
                "started_at": now.isoformat(),
                "expires_at": (now + timedelta(minutes=10)).isoformat(),
            }
        },
    )

    manager = await start_manager(hass, make_entry())
    manager.async_resume_prompts()

    assert manager.prompt_open(TRACKER_B) is False

    await manager.async_stop()

    assert hass_storage[STORE_KEY]["data"]["prompts"] == {}


async def test_a_broken_stored_prompt_is_ignored(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """Unreadable prompt data is dropped instead of breaking the setup."""
    hass_storage[STORE_KEY] = stored(
        {TRACKER_A: {"home": False, "since": None}},
        {TRACKER_A: {"prompt_id": "abc", "started_at": "", "expires_at": "nonsense"}},
    )

    manager = await start_manager(hass, make_entry())
    manager.async_resume_prompts()

    assert manager.prompt_open(TRACKER_A) is False


async def test_stopping_drops_the_timers(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A stopped manager never fires again, open prompt or not."""
    hass.states.async_set(PERSON_A, STATE_HOME)
    manager = await start_manager(
        hass,
        make_entry(
            make_subentry(TRACKER_A, "Kid", **ASKING),
            make_subentry(TRACKER_B, "Granny", **ASKING, **{CONF_PROMPT_DELAY: 60}),
        ),
    )
    kid = Recorder(manager, TRACKER_A)
    granny = Recorder(manager, TRACKER_B)

    await leave(hass, PERSON_A)
    await manager.async_stop()

    await tick(hass, freezer, 30 * 60)

    assert kid.types == [EVENT_PROMPT_STARTED]
    assert granny.types == []
