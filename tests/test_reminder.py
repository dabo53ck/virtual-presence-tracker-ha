"""Tests for the reminder state machine of the household manager (M3a).

A tracker that is left on keeps the house counting as occupied, so after
``remind_after`` hours at home the integration asks whether the person is still
there. "Yes" starts the waiting time again, "no" switches the tracker off, and
no answer changes nothing at all - the rule that holds everywhere in this
integration.
"""

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
    ATTR_REMINDER_ID,
    ATTR_TRACKER,
    CONF_ANSWER_TIMEOUT,
    CONF_ASK_ON_DEPARTURE,
    CONF_PERSONS,
    CONF_REMIND_AFTER,
    CONF_RESET_ON_RETURN,
    DOMAIN,
    EVENT_PROMPT_STARTED,
    EVENT_REMINDER_ANSWERED_NO,
    EVENT_REMINDER_ANSWERED_YES,
    EVENT_REMINDER_CANCELLED,
    EVENT_REMINDER_EXPIRED,
    EVENT_REMINDER_STARTED,
    REASON_OPTION_DISABLED,
    REASON_SWITCHED_OFF,
    STORAGE_KEY_PREFIX,
    STORAGE_VERSION,
    SUBENTRY_TYPE_TRACKER,
)
from custom_components.virtual_presence_tracker.manager import (
    HouseholdManager,
    OpenReminderResult,
)
from homeassistant.const import STATE_HOME, STATE_NOT_HOME
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

ENTRY_ID = "01JVPT0000000000000000ENTRY"
STORE_KEY = f"{STORAGE_KEY_PREFIX}.{ENTRY_ID}"

PERSON_A = "person.dabo53ck"

TRACKER_A = "01JVPT000000000000000TRACKA"
TRACKER_B = "01JVPT000000000000000TRACKB"

HOUR = 3600
# Two hours is short enough to travel to and long enough to be a real interval.
REMINDING = {CONF_REMIND_AFTER: 2}


def make_subentry(subentry_id: str, title: str, **data: Any) -> dict[str, Any]:
    """Return subentry data for one virtual tracker."""
    return {
        "data": data,
        "subentry_id": subentry_id,
        "subentry_type": SUBENTRY_TYPE_TRACKER,
        "title": title,
        "unique_id": None,
    }


def make_entry(*subentries: dict[str, Any]) -> MockConfigEntry:
    """Return a config entry with one real person and the given trackers."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Virtual Presence Tracker",
        entry_id=ENTRY_ID,
        data={CONF_PERSONS: [PERSON_A]},
        subentries_data=subentries or (make_subentry(TRACKER_A, "Kid", **REMINDING),),
    )


def stored(
    trackers: dict[str, dict[str, Any]],
    reminders: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return a storage payload as the manager writes it."""
    data: dict[str, Any] = {"trackers": trackers}
    if reminders is not None:
        data["reminders"] = reminders
    return {
        "version": STORAGE_VERSION,
        "minor_version": 1,
        "key": STORE_KEY,
        "data": data,
    }


def tracker_at_home(hours_ago: float, anchor_hours_ago: float | None = None) -> dict:
    """Return a stored tracker that has been at home for a while."""
    now = dt_util.utcnow()
    anchor = hours_ago if anchor_hours_ago is None else anchor_hours_ago
    return {
        "home": True,
        "since": (now - timedelta(hours=hours_ago)).isoformat(),
        "anchor": (now - timedelta(hours=anchor)).isoformat(),
    }


def open_reminder(minutes_left: float, reminder_id: str = "abc") -> dict[str, Any]:
    """Return a stored reminder with the given time left."""
    now = dt_util.utcnow()
    return {
        "reminder_id": reminder_id,
        "started_at": (now - timedelta(minutes=1)).isoformat(),
        "expires_at": (now + timedelta(minutes=minutes_left)).isoformat(),
    }


class Recorder:
    """Collect the reminder events of one virtual tracker."""

    def __init__(self, manager: HouseholdManager, subentry_id: str) -> None:
        """Subscribe to the reminder events of a tracker."""
        self.events: list[tuple[str, dict[str, Any]]] = []
        manager.async_add_reminder_listener(subentry_id, self._record)

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


async def tick(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: float
) -> None:
    """Let the given number of seconds pass and run what was due."""
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_a_tracker_that_is_on_too_long_reminds(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The reminder opens once the interval since the switch-on has passed."""
    manager = await start_manager(hass, make_entry())
    events = Recorder(manager, TRACKER_A)

    manager.async_set_home(TRACKER_A, True)
    await tick(hass, freezer, 2 * HOUR - 60)

    assert events.types == []
    assert manager.reminder_open(TRACKER_A) is False

    await tick(hass, freezer, 120)

    data = events.only(EVENT_REMINDER_STARTED)
    assert data[ATTR_REMINDER_ID]
    assert data[ATTR_TRACKER] == "Kid"
    assert data[ATTR_EXPIRES_AT] == manager.reminder_expires_at(TRACKER_A).isoformat()
    # A reminder names itself, never a prompt.
    assert ATTR_PROMPT_ID not in data
    assert manager.reminder_open(TRACKER_A) is True
    # Reminding changes nothing by itself.
    assert manager.is_home(TRACKER_A) is True

    await manager.async_stop()


async def test_no_reminder_without_the_option(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A tracker whose subentry has no interval stays silent forever."""
    manager = await start_manager(hass, make_entry(make_subentry(TRACKER_A, "Kid")))
    events = Recorder(manager, TRACKER_A)

    manager.async_set_home(TRACKER_A, True)
    await tick(hass, freezer, 200 * HOUR)

    assert events.types == []
    assert manager.reminder_open(TRACKER_A) is False
    assert manager.reminder_expires_at(TRACKER_A) is None


async def test_no_reminder_while_the_tracker_is_off(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Nobody is reminded about somebody who is not marked as being at home."""
    manager = await start_manager(hass, make_entry())
    events = Recorder(manager, TRACKER_A)

    await tick(hass, freezer, 10 * HOUR)

    assert events.types == []
    assert manager.reminder_open(TRACKER_A) is False


async def test_answering_yes_starts_the_waiting_time_again(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A yes keeps the tracker on and asks again one interval later."""
    manager = await start_manager(hass, make_entry())
    events = Recorder(manager, TRACKER_A)

    manager.async_set_home(TRACKER_A, True)
    await tick(hass, freezer, 2 * HOUR + 1)
    assert events.types == [EVENT_REMINDER_STARTED]

    assert manager.async_answer_reminder(TRACKER_A, True, PERSON_A) is True

    assert manager.is_home(TRACKER_A) is True
    assert manager.reminder_open(TRACKER_A) is False
    assert events.types == [EVENT_REMINDER_STARTED, EVENT_REMINDER_ANSWERED_YES]
    assert events.events[1][1][ATTR_ANSWERED_BY] == PERSON_A

    # The next one is a full interval away, not right around the corner.
    await tick(hass, freezer, 2 * HOUR - 60)
    assert events.types == [EVENT_REMINDER_STARTED, EVENT_REMINDER_ANSWERED_YES]

    await tick(hass, freezer, 120)

    assert events.types[-1] == EVENT_REMINDER_STARTED
    assert (
        events.events[-1][1][ATTR_REMINDER_ID] != events.events[0][1][ATTR_REMINDER_ID]
    )

    await manager.async_stop()


async def test_answering_no_switches_the_tracker_off(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A no does what the user would have done by hand, and says so once."""
    manager = await start_manager(hass, make_entry())
    events = Recorder(manager, TRACKER_A)

    manager.async_set_home(TRACKER_A, True)
    await tick(hass, freezer, 2 * HOUR + 1)

    assert manager.async_answer_reminder(TRACKER_A, False) is True

    assert manager.is_home(TRACKER_A) is False
    assert manager.reminder_open(TRACKER_A) is False
    # The switch-off finds nothing to withdraw, so there is no cancellation.
    assert events.types == [EVENT_REMINDER_STARTED, EVENT_REMINDER_ANSWERED_NO]
    assert events.events[1][1][ATTR_ANSWERED_BY] is None

    # And a tracker that is off is not reminded about again.
    await tick(hass, freezer, 5 * HOUR)
    assert events.types == [EVENT_REMINDER_STARTED, EVENT_REMINDER_ANSWERED_NO]


async def test_a_reminder_expires_and_changes_nothing(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Nobody answers: the tracker stays on and the next reminder is due later."""
    manager = await start_manager(
        hass,
        make_entry(
            make_subentry(TRACKER_A, "Kid", **REMINDING, **{CONF_ANSWER_TIMEOUT: 5})
        ),
    )
    events = Recorder(manager, TRACKER_A)

    manager.async_set_home(TRACKER_A, True)
    await tick(hass, freezer, 2 * HOUR + 1)
    reminder_id = events.only(EVENT_REMINDER_STARTED)[ATTR_REMINDER_ID]

    await tick(hass, freezer, 4 * 60)
    assert events.types == [EVENT_REMINDER_STARTED]

    await tick(hass, freezer, 61)

    assert events.types == [EVENT_REMINDER_STARTED, EVENT_REMINDER_EXPIRED]
    assert events.events[1][1] == {
        ATTR_REMINDER_ID: reminder_id,
        ATTR_TRACKER: "Kid",
    }
    assert manager.is_home(TRACKER_A) is True
    assert manager.reminder_open(TRACKER_A) is False

    # The anchor moved, so the next reminder is a full interval away.
    await tick(hass, freezer, 2 * HOUR - 6 * 60)
    assert events.types == [EVENT_REMINDER_STARTED, EVENT_REMINDER_EXPIRED]

    await tick(hass, freezer, 7 * 60)
    assert events.types[-1] == EVENT_REMINDER_STARTED

    await manager.async_stop()


async def test_the_first_answer_wins(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A second answer finds nothing left to answer."""
    manager = await start_manager(hass, make_entry())
    events = Recorder(manager, TRACKER_A)

    manager.async_set_home(TRACKER_A, True)
    await tick(hass, freezer, 2 * HOUR + 1)

    assert manager.async_answer_reminder(TRACKER_A, True) is True
    assert manager.async_answer_reminder(TRACKER_A, False) is False

    assert manager.is_home(TRACKER_A) is True
    assert events.types == [EVENT_REMINDER_STARTED, EVENT_REMINDER_ANSWERED_YES]

    await manager.async_stop()


async def test_answering_without_a_reminder(hass: HomeAssistant) -> None:
    """Answering a tracker that was not reminded about does nothing."""
    manager = await start_manager(hass, make_entry())
    events = Recorder(manager, TRACKER_A)

    assert manager.async_answer_reminder(TRACKER_A, False) is False

    assert events.types == []
    assert manager.is_home(TRACKER_A) is False


async def test_switching_the_tracker_off_cancels_the_reminder(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """There is nothing to remind about once the tracker is off."""
    manager = await start_manager(hass, make_entry())
    events = Recorder(manager, TRACKER_A)

    manager.async_set_home(TRACKER_A, True)
    await tick(hass, freezer, 2 * HOUR + 1)

    manager.async_set_home(TRACKER_A, False)

    assert events.types == [EVENT_REMINDER_STARTED, EVENT_REMINDER_CANCELLED]
    assert events.events[1][1][ATTR_REASON] == REASON_SWITCHED_OFF
    assert manager.reminder_open(TRACKER_A) is False


async def test_a_reset_on_return_cancels_the_reminder(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The automatic reset switches the tracker off, so the reminder goes too."""
    hass.states.async_set(PERSON_A, STATE_NOT_HOME)
    manager = await start_manager(
        hass,
        make_entry(
            make_subentry(TRACKER_A, "Kid", **REMINDING, **{CONF_RESET_ON_RETURN: True})
        ),
    )
    events = Recorder(manager, TRACKER_A)

    manager.async_set_home(TRACKER_A, True)
    await tick(hass, freezer, 2 * HOUR + 1)
    assert events.types == [EVENT_REMINDER_STARTED]

    hass.states.async_set(PERSON_A, STATE_HOME)
    await hass.async_block_till_done()

    assert manager.is_home(TRACKER_A) is False
    assert events.types == [EVENT_REMINDER_STARTED, EVENT_REMINDER_CANCELLED]
    assert events.events[1][1][ATTR_REASON] == REASON_SWITCHED_OFF


async def test_the_option_going_to_zero_cancels_the_reminder(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Switching the reminder off takes an open one back at once."""
    entry = make_entry()
    manager = await start_manager(hass, entry)
    events = Recorder(manager, TRACKER_A)

    manager.async_set_home(TRACKER_A, True)
    await tick(hass, freezer, 2 * HOUR + 1)
    assert events.types == [EVENT_REMINDER_STARTED]

    manager.async_set_option(TRACKER_A, CONF_REMIND_AFTER, 0)

    assert events.types == [EVENT_REMINDER_STARTED, EVENT_REMINDER_CANCELLED]
    assert events.events[1][1][ATTR_REASON] == REASON_OPTION_DISABLED
    assert manager.reminder_open(TRACKER_A) is False
    assert manager.is_home(TRACKER_A) is True

    await tick(hass, freezer, 10 * HOUR)
    assert events.types == [EVENT_REMINDER_STARTED, EVENT_REMINDER_CANCELLED]


async def test_an_unrelated_option_leaves_a_manual_reminder_alone(
    hass: HomeAssistant,
) -> None:
    """A reminder opened by hand is not withdrawn by the next option change.

    Its tracker has no interval at all, so "the interval was switched off"
    never happened - the manager compares against the value it saw last rather
    than against zero.
    """
    manager = await start_manager(hass, make_entry(make_subentry(TRACKER_A, "Kid")))
    manager.async_set_home(TRACKER_A, True)
    events = Recorder(manager, TRACKER_A)

    assert manager.async_open_reminder(TRACKER_A) is OpenReminderResult.OPENED

    manager.async_set_option(TRACKER_A, CONF_ANSWER_TIMEOUT, 30)

    assert events.types == [EVENT_REMINDER_STARTED]
    assert manager.reminder_open(TRACKER_A) is True

    await manager.async_stop()


async def test_raising_the_option_above_the_time_at_home_waits(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A longer interval moves the next reminder further away."""
    manager = await start_manager(hass, make_entry())
    events = Recorder(manager, TRACKER_A)

    manager.async_set_home(TRACKER_A, True)
    await tick(hass, freezer, HOUR)
    manager.async_set_option(TRACKER_A, CONF_REMIND_AFTER, 5)

    await tick(hass, freezer, 3 * HOUR)
    assert events.types == []

    await tick(hass, freezer, HOUR + 60)
    assert events.types == [EVENT_REMINDER_STARTED]

    await manager.async_stop()


async def test_lowering_the_option_below_the_time_at_home_asks_at_once(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The safety net is meant to catch a tracker that is already forgotten."""
    manager = await start_manager(hass, make_entry(make_subentry(TRACKER_A, "Kid")))
    events = Recorder(manager, TRACKER_A)

    manager.async_set_home(TRACKER_A, True)
    await tick(hass, freezer, 10 * HOUR)
    assert events.types == []

    manager.async_set_option(TRACKER_A, CONF_REMIND_AFTER, 3)

    assert events.types == [EVENT_REMINDER_STARTED]
    assert manager.reminder_open(TRACKER_A) is True

    await manager.async_stop()


async def test_opening_a_reminder_by_hand(hass: HomeAssistant) -> None:
    """Asked for it, the reminder opens on the spot - interval or not."""
    manager = await start_manager(
        hass,
        make_entry(make_subentry(TRACKER_A, "Kid", **{CONF_ANSWER_TIMEOUT: 5})),
    )
    manager.async_set_home(TRACKER_A, True)
    events = Recorder(manager, TRACKER_A)

    assert manager.async_open_reminder(TRACKER_A) is OpenReminderResult.OPENED

    data = events.only(EVENT_REMINDER_STARTED)
    assert data[ATTR_TRACKER] == "Kid"
    expires_at = manager.reminder_expires_at(TRACKER_A)
    assert data[ATTR_EXPIRES_AT] == expires_at.isoformat()
    # It is the tracker's own answer time, the one the prompt uses as well.
    assert expires_at - dt_util.utcnow() <= timedelta(minutes=5)
    assert manager.is_home(TRACKER_A) is True

    await manager.async_stop()


async def test_opening_by_hand_needs_a_tracker_at_home(hass: HomeAssistant) -> None:
    """Nobody is reminded about somebody who is not at home."""
    manager = await start_manager(hass, make_entry())
    events = Recorder(manager, TRACKER_A)

    assert manager.async_open_reminder(TRACKER_A) is OpenReminderResult.TRACKER_AWAY

    assert events.types == []
    assert manager.reminder_open(TRACKER_A) is False


async def test_opening_by_hand_never_asks_twice(hass: HomeAssistant) -> None:
    """A second attempt leaves the first reminder exactly as it was."""
    manager = await start_manager(hass, make_entry())
    manager.async_set_home(TRACKER_A, True)
    events = Recorder(manager, TRACKER_A)

    manager.async_open_reminder(TRACKER_A)
    reminder_id = events.only(EVENT_REMINDER_STARTED)[ATTR_REMINDER_ID]
    expires_at = manager.reminder_expires_at(TRACKER_A)

    assert manager.async_open_reminder(TRACKER_A) is OpenReminderResult.REMINDER_OPEN

    assert events.types == [EVENT_REMINDER_STARTED]
    assert events.events[0][1][ATTR_REMINDER_ID] == reminder_id
    assert manager.reminder_expires_at(TRACKER_A) == expires_at

    await manager.async_stop()


async def test_opening_by_hand_postpones_the_automatic_one(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The timer of a tracker that was just asked about does not fire as well."""
    manager = await start_manager(hass, make_entry())
    manager.async_set_home(TRACKER_A, True)
    events = Recorder(manager, TRACKER_A)

    await tick(hass, freezer, HOUR)
    manager.async_open_reminder(TRACKER_A)
    manager.async_answer_reminder(TRACKER_A, True)

    # The timer that was set when the tracker went on would have been due here.
    await tick(hass, freezer, HOUR + 60)

    assert events.types == [EVENT_REMINDER_STARTED, EVENT_REMINDER_ANSWERED_YES]

    await manager.async_stop()


async def test_a_prompt_and_a_reminder_are_never_open_together(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The two questions exclude each other: one needs the tracker off, one on."""
    hass.states.async_set(PERSON_A, STATE_HOME)
    manager = await start_manager(
        hass,
        make_entry(
            make_subentry(
                TRACKER_A, "Kid", **REMINDING, **{CONF_ASK_ON_DEPARTURE: True}
            )
        ),
    )
    reminders = Recorder(manager, TRACKER_A)
    prompts: list[str] = []
    manager.async_add_prompt_listener(
        TRACKER_A, lambda event_type, _data: prompts.append(event_type)
    )

    # The house empties: the prompt opens, the tracker is off, no reminder.
    hass.states.async_set(PERSON_A, STATE_NOT_HOME)
    await hass.async_block_till_done()
    assert prompts == [EVENT_PROMPT_STARTED]
    assert reminders.types == []

    # Answering yes switches the tracker on, which starts the reminder clock.
    manager.async_answer_prompt(TRACKER_A, True)
    assert manager.prompt_open(TRACKER_A) is False

    await tick(hass, freezer, 2 * HOUR + 1)

    assert reminders.types == [EVENT_REMINDER_STARTED]
    assert manager.prompt_open(TRACKER_A) is False

    await manager.async_stop()


async def test_an_open_reminder_is_persisted(
    hass: HomeAssistant, hass_storage: dict[str, Any], freezer: FrozenDateTimeFactory
) -> None:
    """An open reminder and the anchor are written to the store and read back."""
    entry = make_entry()
    manager = await start_manager(hass, entry)
    events = Recorder(manager, TRACKER_A)

    manager.async_set_home(TRACKER_A, True)
    await tick(hass, freezer, 2 * HOUR + 1)
    reminder_id = events.only(EVENT_REMINDER_STARTED)[ATTR_REMINDER_ID]
    expires_at = manager.reminder_expires_at(TRACKER_A)
    await manager.async_stop()

    data = hass_storage[STORE_KEY]["data"]
    assert data["reminders"][TRACKER_A]["reminder_id"] == reminder_id
    assert data["reminders"][TRACKER_A]["expires_at"] == expires_at.isoformat()
    assert data["trackers"][TRACKER_A]["anchor"] is not None

    restored = HouseholdManager(hass, entry)
    await restored.async_load()

    assert restored.reminder_open(TRACKER_A) is True
    assert restored.reminder_expires_at(TRACKER_A) == expires_at


async def test_a_store_without_reminders_is_read(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """A store written before the reminder existed loads unchanged."""
    hass_storage[STORE_KEY] = stored({TRACKER_A: {"home": True, "since": None}})

    manager = await start_manager(hass, make_entry())
    manager.async_resume_reminders()

    assert manager.is_home(TRACKER_A) is True
    assert manager.reminder_open(TRACKER_A) is False

    await manager.async_stop()


async def test_a_broken_stored_reminder_is_ignored(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """Unreadable reminder data is dropped instead of breaking the setup."""
    hass_storage[STORE_KEY] = stored(
        {TRACKER_A: {"home": False, "since": None}},
        {TRACKER_A: {"reminder_id": "abc", "started_at": "", "expires_at": "no"}},
    )

    manager = await start_manager(hass, make_entry())
    manager.async_resume_reminders()

    assert manager.reminder_open(TRACKER_A) is False


async def test_the_reminder_of_a_removed_tracker_is_dropped(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """A reminder without a tracker disappears without a word."""
    hass_storage[STORE_KEY] = stored(
        {TRACKER_B: tracker_at_home(3)}, {TRACKER_B: open_reminder(5)}
    )

    manager = await start_manager(hass, make_entry())
    manager.async_resume_reminders()

    assert manager.reminder_open(TRACKER_B) is False

    await manager.async_stop()

    assert hass_storage[STORE_KEY]["data"]["reminders"] == {}


async def test_resume_keeps_the_remaining_time(
    hass: HomeAssistant, hass_storage: dict[str, Any], freezer: FrozenDateTimeFactory
) -> None:
    """A reminder that is still valid continues silently and can still expire."""
    hass_storage[STORE_KEY] = stored(
        {TRACKER_A: tracker_at_home(3)}, {TRACKER_A: open_reminder(2)}
    )
    manager = await start_manager(hass, make_entry())
    events = Recorder(manager, TRACKER_A)

    manager.async_resume_reminders()

    assert events.types == []
    assert manager.reminder_open(TRACKER_A) is True

    await tick(hass, freezer, 60)
    assert events.types == []

    await tick(hass, freezer, 61)

    assert events.types == [EVENT_REMINDER_EXPIRED]
    assert events.events[0][1][ATTR_REMINDER_ID] == "abc"

    await manager.async_stop()


async def test_resume_gives_up_on_an_old_reminder(
    hass: HomeAssistant, hass_storage: dict[str, Any], freezer: FrozenDateTimeFactory
) -> None:
    """A reminder whose time ran out while Home Assistant was off expires."""
    hass_storage[STORE_KEY] = stored(
        {TRACKER_A: tracker_at_home(5)}, {TRACKER_A: open_reminder(-60)}
    )
    manager = await start_manager(hass, make_entry())
    events = Recorder(manager, TRACKER_A)

    manager.async_resume_reminders()

    assert events.types == [EVENT_REMINDER_EXPIRED]
    assert manager.reminder_open(TRACKER_A) is False
    assert manager.is_home(TRACKER_A) is True

    # The anchor was moved, so the next one is a full interval away rather
    # than immediately due on a tracker that is five hours old.
    await tick(hass, freezer, 2 * HOUR - 60)
    assert events.types == [EVENT_REMINDER_EXPIRED]

    await tick(hass, freezer, 120)
    assert events.types == [EVENT_REMINDER_EXPIRED, EVENT_REMINDER_STARTED]

    await manager.async_stop()


async def test_resume_cancels_when_the_tracker_is_off(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """A tracker that was switched off meanwhile takes its reminder with it."""
    hass_storage[STORE_KEY] = stored(
        {TRACKER_A: {"home": False, "since": None}}, {TRACKER_A: open_reminder(5)}
    )
    manager = await start_manager(hass, make_entry())
    events = Recorder(manager, TRACKER_A)

    manager.async_resume_reminders()

    assert events.types == [EVENT_REMINDER_CANCELLED]
    assert events.events[0][1][ATTR_REASON] == REASON_SWITCHED_OFF
    assert manager.reminder_open(TRACKER_A) is False


async def test_an_overdue_reminder_fires_after_the_start(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """A tracker that became due while Home Assistant was off is asked about once."""
    hass_storage[STORE_KEY] = stored({TRACKER_A: tracker_at_home(9)})
    manager = await start_manager(hass, make_entry())
    events = Recorder(manager, TRACKER_A)

    manager.async_resume_reminders()

    assert events.types == [EVENT_REMINDER_STARTED]
    assert manager.reminder_open(TRACKER_A) is True

    await manager.async_stop()


async def test_a_tracker_without_an_anchor_counts_from_its_last_change(
    hass: HomeAssistant, hass_storage: dict[str, Any], freezer: FrozenDateTimeFactory
) -> None:
    """A tracker switched on before M3a has no anchor, and needs none."""
    now = dt_util.utcnow()
    hass_storage[STORE_KEY] = stored(
        {
            TRACKER_A: {
                "home": True,
                "since": (now - timedelta(minutes=90)).isoformat(),
            }
        }
    )
    manager = await start_manager(hass, make_entry())
    events = Recorder(manager, TRACKER_A)

    manager.async_resume_reminders()
    assert events.types == []

    # Half an hour left of the two hours since it was switched on.
    await tick(hass, freezer, 29 * 60)
    assert events.types == []

    await tick(hass, freezer, 120)
    assert events.types == [EVENT_REMINDER_STARTED]

    await manager.async_stop()


async def test_the_anchor_survives_a_restart(
    hass: HomeAssistant, hass_storage: dict[str, Any], freezer: FrozenDateTimeFactory
) -> None:
    """Answering "still home" is remembered across a restart."""
    entry = make_entry()
    manager = await start_manager(hass, entry)

    manager.async_set_home(TRACKER_A, True)
    await tick(hass, freezer, 2 * HOUR + 1)
    manager.async_answer_reminder(TRACKER_A, True)
    await manager.async_stop()

    restored = HouseholdManager(hass, entry)
    await restored.async_load()
    restored.async_start()
    events = Recorder(restored, TRACKER_A)
    restored.async_resume_reminders()

    assert events.types == []

    await tick(hass, freezer, 2 * HOUR - 60)
    assert events.types == []

    await tick(hass, freezer, 120)
    assert events.types == [EVENT_REMINDER_STARTED]

    await restored.async_stop()


async def test_stopping_drops_the_timers(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A stopped manager never reminds again, open reminder or not."""
    manager = await start_manager(
        hass,
        make_entry(
            make_subentry(TRACKER_A, "Kid", **REMINDING),
            make_subentry(TRACKER_B, "Granny", **REMINDING),
        ),
    )
    kid = Recorder(manager, TRACKER_A)
    granny = Recorder(manager, TRACKER_B)

    manager.async_set_home(TRACKER_A, True)
    manager.async_set_home(TRACKER_B, True)
    await tick(hass, freezer, 2 * HOUR + 1)
    assert kid.types == [EVENT_REMINDER_STARTED]

    await manager.async_stop()
    await tick(hass, freezer, 30 * HOUR)

    assert kid.types == [EVENT_REMINDER_STARTED]
    assert granny.types == [EVENT_REMINDER_STARTED]


@pytest.mark.parametrize("hours", [0, 1, 2])
async def test_how_long_a_tracker_has_been_at_home(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hours: int
) -> None:
    """The message counts whole hours since the switch-on, and never says zero."""
    manager = await start_manager(hass, make_entry(make_subentry(TRACKER_A, "Kid")))

    assert manager.home_hours(TRACKER_A) == 1

    manager.async_set_home(TRACKER_A, True)
    await tick(hass, freezer, hours * HOUR + 60)

    assert manager.home_hours(TRACKER_A) == max(hours, 1)
