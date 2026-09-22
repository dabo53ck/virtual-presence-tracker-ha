"""Household state of the Virtual Presence Tracker integration.

The manager owns the state of every virtual tracker, the presence of the
configured real persons and the two state machines that ask about a tracker:
the prompt, when the house empties, and the reminder, when a tracker has been
at home for too long. It is the single source
of truth: the entities are thin views on it, so the state survives a restart
and is already correct before the platforms are set up (see docs/DESIGN.md).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from functools import partial
import logging
from typing import TYPE_CHECKING, Any, NotRequired, TypedDict
from uuid import uuid4

from homeassistant.const import STATE_HOME, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_ANSWERED_BY,
    ATTR_EXPIRES_AT,
    ATTR_PROMPT_ID,
    ATTR_REASON,
    ATTR_REMINDER_ID,
    ATTR_TRACKER,
    CONF_ANSWER_TIMEOUT,
    CONF_ASK_ON_DEPARTURE,
    CONF_PERSONS,
    CONF_PROMPT_DELAY,
    CONF_REMIND_AFTER,
    CONF_REMINDER_TIMEOUT,
    CONF_RESET_ON_RETURN,
    EVENT_ANSWERED_NO,
    EVENT_ANSWERED_YES,
    EVENT_CANCELLED,
    EVENT_EXPIRED,
    EVENT_PROMPT_STARTED,
    EVENT_REMINDER_ANSWERED_NO,
    EVENT_REMINDER_ANSWERED_YES,
    EVENT_REMINDER_CANCELLED,
    EVENT_REMINDER_EXPIRED,
    EVENT_REMINDER_STARTED,
    OPTION_DEFAULTS,
    REASON_OPTION_DISABLED,
    REASON_PERSON_HOME,
    REASON_SWITCHED_OFF,
    REASON_SWITCHED_ON,
    STORAGE_KEY_PREFIX,
    STORAGE_SAVE_DELAY,
    STORAGE_VERSION,
    SUBENTRY_TYPE_TRACKER,
)

if TYPE_CHECKING:
    from . import VirtualPresenceTrackerConfigEntry

_LOGGER = logging.getLogger(__name__)

# What a prompt event entity is called with: the event type and its data. The
# reminder uses the same shape, through a channel of its own.
type PromptListener = Callable[[str, dict[str, Any]], None]


class OpenPromptResult(StrEnum):
    """What came of the attempt to open a prompt by hand.

    The manager says what it found; turning a refusal into an error message is
    the caller's business, so that nothing of the service layer leaks in here.
    """

    OPENED = "opened"
    TRACKER_AT_HOME = "tracker_at_home"
    PROMPT_OPEN = "prompt_open"


class OpenReminderResult(StrEnum):
    """What came of the attempt to open a reminder by hand.

    The mirror image of OpenPromptResult: a reminder is about a tracker that is
    *on*, so the tracker being away is what refuses it.
    """

    OPENED = "opened"
    TRACKER_AWAY = "tracker_away"
    REMINDER_OPEN = "reminder_open"


class StoredTracker(TypedDict):
    """Persisted state of a single virtual tracker.

    ``anchor`` was added in M3a and is optional: a tracker written before it
    simply has none, and the last change of the tracker is then what the
    reminder counts from. Nothing has to be converted, so the store version
    stays where it is.
    """

    home: bool
    since: str | None
    anchor: NotRequired[str | None]


class StoredPrompt(TypedDict):
    """Persisted state of an open prompt.

    ``manual`` was added in M2d and is optional for the same reason the whole
    ``prompts`` key is: a prompt written before it simply was not opened by
    hand.
    """

    prompt_id: str
    started_at: str
    expires_at: str
    manual: NotRequired[bool]


class StoredReminder(TypedDict):
    """Persisted state of an open reminder.

    A reminder has no counterpart of the prompt's ``manual`` flag: neither of
    the reasons that withdraw it after a restart depends on how it was opened.
    """

    reminder_id: str
    started_at: str
    expires_at: str


class StoredData(TypedDict):
    """Persisted state of a config entry.

    ``prompts`` was added in M2a and ``reminders`` in M3a. A store written
    before either simply does not have the key, which means "nothing was open"
    - exactly what a fresh install looks like - so the store version does not
    have to be raised.
    """

    trackers: dict[str, StoredTracker]
    prompts: NotRequired[dict[str, StoredPrompt]]
    reminders: NotRequired[dict[str, StoredReminder]]


@dataclass(slots=True)
class TrackerState:
    """In-memory state of a single virtual tracker.

    ``anchor`` is what the reminder counts from: the moment the tracker was
    switched on, moved forward every time somebody confirms that the person is
    still at home and every time a reminder goes unanswered. It is ``None``
    while the tracker is off, and for a tracker that was switched on before
    M3a - ``since`` is the fallback then, which for a tracker that is on is the
    moment it was switched on.
    """

    home: bool = False
    since: datetime | None = None
    anchor: datetime | None = None


@dataclass(slots=True)
class Prompt:
    """An open prompt of a single virtual tracker.

    ``manual`` marks a prompt somebody opened themselves. It never depended on
    the tracker's option or on an empty house, so neither of them takes it back
    when a restart picks it up again.
    """

    prompt_id: str
    started_at: datetime
    expires_at: datetime
    manual: bool = False


@dataclass(slots=True)
class Reminder:
    """An open reminder about a tracker that has been on for a long time."""

    reminder_id: str
    started_at: datetime
    expires_at: datetime


@dataclass(slots=True)
class _Scheduled:
    """A prompt that is waiting for its delay to pass.

    It already carries the ID of the prompt it is going to open, so that a
    cancellation during the delay can name it. Unlike an open prompt it is not
    persisted: a restart or a reload simply forgets it.
    """

    prompt_id: str
    unsub: CALLBACK_TYPE


def _person_is_home(state: State | None) -> bool | None:
    """Return whether a person is home, or None if their state is unknown.

    Every state other than ``home`` (``not_home``, a zone name, …) counts as
    away.
    """
    if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
        return None
    return state.state == STATE_HOME


def _prompt_from_store(stored: StoredPrompt) -> Prompt | None:
    """Return a persisted prompt, or None if it cannot be read back."""
    started_at = dt_util.parse_datetime(stored.get("started_at") or "")
    expires_at = dt_util.parse_datetime(stored.get("expires_at") or "")
    prompt_id = stored.get("prompt_id")
    if not prompt_id or started_at is None or expires_at is None:
        return None
    return Prompt(
        prompt_id=prompt_id,
        started_at=started_at,
        expires_at=expires_at,
        manual=bool(stored.get("manual")),
    )


def _reminder_from_store(stored: StoredReminder) -> Reminder | None:
    """Return a persisted reminder, or None if it cannot be read back."""
    started_at = dt_util.parse_datetime(stored.get("started_at") or "")
    expires_at = dt_util.parse_datetime(stored.get("expires_at") or "")
    reminder_id = stored.get("reminder_id")
    if not reminder_id or started_at is None or expires_at is None:
        return None
    return Reminder(
        reminder_id=reminder_id, started_at=started_at, expires_at=expires_at
    )


class HouseholdManager:
    """Hold the virtual trackers and the presence of the real persons."""

    def __init__(
        self, hass: HomeAssistant, entry: VirtualPresenceTrackerConfigEntry
    ) -> None:
        """Initialise the manager. Call async_load() before using it."""
        self.hass = hass
        self.entry = entry
        self._store = Store[StoredData](
            hass, STORAGE_VERSION, f"{STORAGE_KEY_PREFIX}.{entry.entry_id}"
        )
        self._trackers: dict[str, TrackerState] = {}
        # Last *known* presence per configured person. A person whose state is
        # unknown, unavailable or missing keeps their previous value and is
        # absent from this mapping until their state is known once.
        self._person_home: dict[str, bool] = {}
        self._listeners: list[Callable[[], None]] = []
        self._tracker_listeners: dict[str, list[Callable[[], None]]] = {}
        self._unsub_persons: CALLBACK_TYPE | None = None
        # Prompt state machine, per tracker: an open prompt with its expiry
        # timer, or a prompt that is still waiting for its delay.
        self._prompts: dict[str, Prompt] = {}
        self._expiry: dict[str, CALLBACK_TYPE] = {}
        self._scheduled: dict[str, _Scheduled] = {}
        self._prompt_listeners: dict[str, list[PromptListener]] = {}
        # Reminder state machine, per tracker: an open reminder with its expiry
        # timer, and the timer that opens the next one when the tracker has
        # been at home for long enough.
        self._reminders: dict[str, Reminder] = {}
        self._reminder_expiry: dict[str, CALLBACK_TYPE] = {}
        self._due: dict[str, CALLBACK_TYPE] = {}
        self._reminder_listeners: dict[str, list[PromptListener]] = {}
        # What the ask option of each tracker was the last time the manager
        # looked. The options live in the subentry data and can now be written
        # from an entity, so switching one off has to be noticed rather than
        # reported - and only these two have anything to take back.
        self._asking: dict[str, bool] = {}
        self._reminding: dict[str, int] = {}

    async def async_load(self) -> None:
        """Load the persisted tracker states, prompts and reminders.

        Must be awaited before any platform is set up, so that the entities
        report the restored state from their first write on. Trackers whose
        subentry is gone are pruned, and so are their prompts and reminders.
        Those are only loaded here; picking them up again is
        async_resume_prompts() / async_resume_reminders(), which need the
        entities to exist.
        """
        stored = await self._store.async_load()
        stored_trackers = stored["trackers"] if stored else {}
        stored_prompts = stored.get("prompts", {}) if stored else {}
        stored_reminders = stored.get("reminders", {}) if stored else {}
        known_ids = [
            subentry.subentry_id
            for subentry in self.entry.get_subentries_of_type(SUBENTRY_TYPE_TRACKER)
        ]

        trackers: dict[str, TrackerState] = {}
        prompts: dict[str, Prompt] = {}
        reminders: dict[str, Reminder] = {}
        for subentry_id in known_ids:
            if (stored_prompt := stored_prompts.get(subentry_id)) is not None and (
                prompt := _prompt_from_store(stored_prompt)
            ) is not None:
                prompts[subentry_id] = prompt
            if (stored_reminder := stored_reminders.get(subentry_id)) is not None and (
                reminder := _reminder_from_store(stored_reminder)
            ) is not None:
                reminders[subentry_id] = reminder
            if (stored_tracker := stored_trackers.get(subentry_id)) is None:
                trackers[subentry_id] = TrackerState()
                continue
            since = stored_tracker.get("since")
            anchor = stored_tracker.get("anchor")
            trackers[subentry_id] = TrackerState(
                home=bool(stored_tracker.get("home")),
                since=dt_util.parse_datetime(since) if since else None,
                anchor=dt_util.parse_datetime(anchor) if anchor else None,
            )
        self._trackers = trackers
        self._prompts = prompts
        self._reminders = reminders
        self._asking = {
            subentry_id: self._ask_on_departure(subentry_id) for subentry_id in trackers
        }
        self._reminding = {
            subentry_id: self._remind_after(subentry_id) for subentry_id in trackers
        }

        stale = stored_trackers.keys() | stored_prompts.keys() | stored_reminders.keys()
        if stale - set(known_ids):
            self._async_schedule_save()

    @callback
    def async_start(self) -> None:
        """Subscribe to the configured real persons and take the baseline.

        The baseline is read from the current states so that a person who is
        already home when the entry is set up does not trigger a reset.
        """
        # async_track_state_change_event lower cases the entity IDs it is given,
        # so the baseline keys have to match.
        persons = [
            entity_id.lower() for entity_id in self.entry.data.get(CONF_PERSONS, [])
        ]
        self._person_home = {}
        for entity_id in persons:
            if (home := _person_is_home(self.hass.states.get(entity_id))) is not None:
                self._person_home[entity_id] = home

        self._unsub_persons = async_track_state_change_event(
            self.hass, persons, self._async_person_changed
        )

    @callback
    def async_resume_prompts(self) -> None:
        """Pick the prompts up again that a restart or a reload interrupted.

        Must run *after* the platforms are set up: the catch-up can emit an
        ``expired`` or a ``cancelled`` event, and an event entity that does not
        exist yet would silently swallow it.

        A prompt that was opened by hand skips both catch-up cancellations: it
        was never about the option or about an empty house, so neither can have
        gone away. Its deadline is the one thing that still applies to it.
        """
        now = dt_util.utcnow()
        for subentry_id, prompt in list(self._prompts.items()):
            if not prompt.manual and not self._ask_on_departure(subentry_id):
                # The option can only have changed through the subentry flow,
                # which reloads the entry - this is where that is noticed.
                self._async_cancel_prompt(subentry_id, REASON_OPTION_DISABLED)
            elif not prompt.manual and self.real_home:
                self._async_cancel_prompt(subentry_id, REASON_PERSON_HOME)
            elif prompt.expires_at <= now:
                self._async_end_prompt(subentry_id)
                self._async_fire(subentry_id, prompt.prompt_id, EVENT_EXPIRED)
            else:
                # Still open: it keeps the time it has left and says nothing.
                self._async_start_expiry(subentry_id, prompt, now)

    @callback
    def async_resume_reminders(self) -> None:
        """Pick the reminders up again and start the timers of every tracker.

        Must run *after* the platforms are set up, for the same reason the
        prompts must: the catch-up can emit an event, and it can open a
        reminder that became due while Home Assistant was down.

        A reminder is only ever about a tracker that is at home, so a tracker
        that was switched off meanwhile takes its reminder with it. Nothing
        else withdraws one: unlike the prompt it does not depend on who is at
        home, and an open reminder does not depend on the option either - it
        may have been opened by hand while the option was off.
        """
        now = dt_util.utcnow()
        for subentry_id, reminder in list(self._reminders.items()):
            if not self.is_home(subentry_id):
                self._async_cancel_reminder(subentry_id, REASON_SWITCHED_OFF)
            elif reminder.expires_at <= now:
                self._async_end_reminder(subentry_id)
                self._async_set_anchor(subentry_id, now)
                self._async_fire_reminder(
                    subentry_id, reminder.reminder_id, EVENT_REMINDER_EXPIRED
                )
            else:
                # Still open: it keeps the time it has left and says nothing.
                self._async_start_reminder_expiry(subentry_id, reminder, now)
        # Whatever is left without an open reminder gets its timer back - and a
        # tracker whose reminder became due while Home Assistant was down is
        # asked about right here, once.
        for subentry_id in list(self._trackers):
            self._async_schedule_reminder(subentry_id)

    async def async_stop(self) -> None:
        """Unsubscribe, drop every timer and write the current state to disk.

        Open prompts and reminders are kept: they are persisted and resumed by
        the next manager. Prompts that are still waiting for their delay are
        not - they were never announced, so nothing has to be taken back - and
        neither is the timer of the next reminder, which is recomputed from the
        persisted anchor.
        """
        if self._unsub_persons is not None:
            self._unsub_persons()
            self._unsub_persons = None
        for unsub in (*self._expiry.values(), *self._reminder_expiry.values()):
            unsub()
        self._expiry.clear()
        self._reminder_expiry.clear()
        for unsub in self._due.values():
            unsub()
        self._due.clear()
        for scheduled in self._scheduled.values():
            scheduled.unsub()
        self._scheduled.clear()
        await self._store.async_save(self._data_to_store())

    @property
    def tracker_ids(self) -> list[str]:
        """Return the subentry IDs of the known virtual trackers."""
        return list(self._trackers)

    def is_home(self, subentry_id: str) -> bool:
        """Return whether a virtual tracker is at home."""
        tracker = self._trackers.get(subentry_id)
        return tracker.home if tracker is not None else False

    def since(self, subentry_id: str) -> datetime | None:
        """Return when a virtual tracker last changed, if it ever did."""
        tracker = self._trackers.get(subentry_id)
        return tracker.since if tracker is not None else None

    @property
    def real_persons_home(self) -> int:
        """Return how many configured real persons are known to be home."""
        return sum(self._person_home.values())

    @property
    def real_home(self) -> bool | None:
        """Return whether a real person is home, None while nothing is known."""
        if not self._person_home:
            return None
        return any(self._person_home.values())

    @property
    def only_virtual_home(self) -> bool:
        """Return whether a tracker is home while no real person is."""
        return self.real_persons_home == 0 and any(
            tracker.home for tracker in self._trackers.values()
        )

    def prompt_open(self, subentry_id: str) -> bool:
        """Return whether a virtual tracker has a prompt waiting for an answer."""
        return subentry_id in self._prompts

    def prompt_expires_at(self, subentry_id: str) -> datetime | None:
        """Return when the open prompt of a tracker gives up, if there is one."""
        prompt = self._prompts.get(subentry_id)
        return prompt.expires_at if prompt is not None else None

    def reminder_open(self, subentry_id: str) -> bool:
        """Return whether a virtual tracker has a reminder waiting for an answer."""
        return subentry_id in self._reminders

    def reminder_expires_at(self, subentry_id: str) -> datetime | None:
        """Return when the open reminder of a tracker gives up, if there is one."""
        reminder = self._reminders.get(subentry_id)
        return reminder.expires_at if reminder is not None else None

    def home_hours(self, subentry_id: str) -> int:
        """Return how many whole hours a tracker has been at home, at least one.

        What the reminder message says, and deliberately counted from the
        moment the tracker was switched on rather than from the anchor: the
        question is how long somebody has been marked as being at home, which
        answering "still here" does not reset.
        """
        since = self.since(subentry_id)
        if since is None:
            return 1
        hours = int((dt_util.utcnow() - since).total_seconds() // 3600)
        return max(hours, 1)

    def tracker_of_prompt(self, prompt_id: str) -> str | None:
        """Return the tracker a prompt ID belongs to, if it is still open.

        An answer that arrives from a phone names the prompt, not the tracker:
        this is what turns the one into the other. A prompt that has ended is
        unknown here, so a late answer finds nothing to answer.
        """
        for subentry_id, prompt in self._prompts.items():
            if prompt.prompt_id == prompt_id:
                return subentry_id
        return None

    def tracker_of_reminder(self, reminder_id: str) -> str | None:
        """Return the tracker a reminder ID belongs to, if it is still open."""
        for subentry_id, reminder in self._reminders.items():
            if reminder.reminder_id == reminder_id:
                return subentry_id
        return None

    @callback
    def async_set_home(self, subentry_id: str, home: bool) -> None:
        """Set a virtual tracker home or away.

        Switching a tracker on answers the question the prompt asks, so a
        prompt that is open or on its way is cancelled rather than left to
        expire. The answer service ends its prompt before it gets here, so
        answering "yes" does not also report a cancellation.
        """
        if home:
            self._async_cancel_prompt(subentry_id, REASON_SWITCHED_ON)
        if self._async_set_tracker(subentry_id, home):
            self._async_notify(self._listeners)

    @callback
    def async_open_prompt(self, subentry_id: str) -> OpenPromptResult:
        """Open the prompt of a tracker right now, because somebody asked for it.

        The manual counterpart of the automatic opening, for a test run or for
        an automation that knows better than the departure rule. It ignores
        everything that decides *whether* to ask - the option, the real
        persons, the delay - because the caller has decided that already.

        What it does not ignore is the tracker: nobody has to be asked about
        somebody who is at home, and a tracker is never asked about twice at
        once. Both are checked before anything changes, so a refusal leaves no
        trace at all. Everything after the opening is the usual prompt.
        """
        if self.is_home(subentry_id):
            return OpenPromptResult.TRACKER_AT_HOME
        if subentry_id in self._prompts:
            return OpenPromptResult.PROMPT_OPEN

        prompt_id = uuid4().hex
        if (scheduled := self._scheduled.pop(subentry_id, None)) is not None:
            # A prompt that is still waiting for its delay is not a second
            # prompt: it becomes this one, ID and all, so that the events stay
            # one chain and the delayed timer has nothing left to open.
            scheduled.unsub()
            prompt_id = scheduled.prompt_id
        self._async_start_prompt(subentry_id, prompt_id, manual=True)
        return OpenPromptResult.OPENED

    @callback
    def async_answer_prompt(
        self, subentry_id: str, answer: bool, answered_by: str | None = None
    ) -> bool:
        """Answer the open prompt of a tracker, if it has one.

        Returns whether there was a prompt to answer. "Yes" sets the tracker
        home, "no" changes nothing at all: the house then counts as empty.
        """
        prompt = self._prompts.get(subentry_id)
        if prompt is None:
            return False
        self._async_end_prompt(subentry_id)
        if answer:
            self.async_set_home(subentry_id, True)
        self._async_fire(
            subentry_id,
            prompt.prompt_id,
            EVENT_ANSWERED_YES if answer else EVENT_ANSWERED_NO,
            {ATTR_ANSWERED_BY: answered_by},
        )
        return True

    @callback
    def async_open_reminder(self, subentry_id: str) -> OpenReminderResult:
        """Ask about a tracker right now, because somebody asked for it.

        The manual counterpart of the timer: it ignores the tracker's
        ``remind_after`` and its anchor, which is what makes the whole chain
        testable without waiting for hours, and what lets an automation ask
        "still there?" on an occasion of its own.

        What it does not ignore is the tracker: a reminder is about somebody
        who is marked as being at home, and a tracker is only asked about once
        at a time. Both are checked before anything changes, so a refusal
        leaves no trace at all.
        """
        if not self.is_home(subentry_id):
            return OpenReminderResult.TRACKER_AWAY
        if subentry_id in self._reminders:
            return OpenReminderResult.REMINDER_OPEN
        self._async_start_reminder(subentry_id)
        return OpenReminderResult.OPENED

    @callback
    def async_answer_reminder(
        self, subentry_id: str, answer: bool, answered_by: str | None = None
    ) -> bool:
        """Answer the open reminder of a tracker, if it has one.

        Returns whether there was a reminder to answer. "Yes" means the person
        is still at home: the tracker stays on and the count starts again.
        "No" switches the tracker off, down the same path a switch does, so
        everything that follows a switch-off follows this too.
        """
        reminder = self._reminders.get(subentry_id)
        if reminder is None:
            return False
        # Ending it first means the switch-off finds nothing to cancel, so a
        # "no" never also reports a withdrawn reminder.
        self._async_end_reminder(subentry_id)
        if answer:
            self._async_set_anchor(subentry_id, dt_util.utcnow())
            self._async_schedule_reminder(subentry_id)
        else:
            self.async_set_home(subentry_id, False)
        self._async_fire_reminder(
            subentry_id,
            reminder.reminder_id,
            EVENT_REMINDER_ANSWERED_YES if answer else EVENT_REMINDER_ANSWERED_NO,
            {ATTR_ANSWERED_BY: answered_by},
        )
        return True

    def option(self, subentry_id: str, key: str) -> Any:
        """Return one of the options a tracker has an entity for.

        The subentry data is the single source of truth and is read every time:
        the entities of these options are views on it, exactly as the switch is
        a view on the tracker state.
        """
        return self._option(subentry_id, key, OPTION_DEFAULTS[key])

    @callback
    def async_set_option(self, subentry_id: str, key: str, value: bool | int) -> None:
        """Write one option of a tracker and let everything follow at once.

        The write goes into the subentry data, where the option has always
        lived. Home Assistant hands the change to the update listeners as a
        task, so the reaction is triggered here as well: the entity that was
        just used has to show the new value now, not after the next tick. Doing
        it twice costs nothing - the second run finds everything done.
        """
        subentry = self.entry.subentries.get(subentry_id)
        if subentry is None:
            return
        self.hass.config_entries.async_update_subentry(
            self.entry, subentry, data={**subentry.data, key: value}
        )
        self.async_options_changed()

    @callback
    def async_options_changed(self) -> None:
        """Take in a change of the options that did not reload the entry.

        Two options have a consequence of their own. Switching the ask option
        off while its tracker is being asked about takes the question back, the
        same way it used to when the form still reloaded the entry. The
        reminder interval decides when the next reminder is due, so every
        change of it moves the timer - and setting it to zero takes an open
        reminder back. Both are compared against the value the manager saw last
        rather than acted on every time: an open reminder of a tracker whose
        interval is zero was opened by hand, and an unrelated option change
        must not withdraw it.

        Everything else - the reset, the timeout, the delay, the expiry
        notice - is read where it is used, so it is enough to let the entities
        write their new state.
        """
        for subentry_id in list(self._trackers):
            asking = self._ask_on_departure(subentry_id)
            if self._asking.get(subentry_id, asking) and not asking:
                self._async_asking_switched_off(subentry_id)
            self._asking[subentry_id] = asking

            reminding = self._remind_after(subentry_id)
            if self._reminding.get(subentry_id, reminding) > 0 and reminding <= 0:
                self._async_cancel_reminder(subentry_id, REASON_OPTION_DISABLED)
            self._reminding[subentry_id] = reminding
            self._async_schedule_reminder(subentry_id)

            self._async_notify(self._tracker_listeners.get(subentry_id, []))

    @callback
    def _async_asking_switched_off(self, subentry_id: str) -> None:
        """Take back what the ask option had started, if anything.

        A prompt somebody opened by hand stays: it was never opened because the
        option was on, so switching the option off says nothing about it - the
        same reasoning that keeps it alive across a restart.
        """
        prompt = self._prompts.get(subentry_id)
        if prompt is not None and prompt.manual:
            return
        self._async_cancel_prompt(subentry_id, REASON_OPTION_DISABLED)

    @callback
    def async_add_prompt_listener(
        self, subentry_id: str, prompt_listener: PromptListener
    ) -> CALLBACK_TYPE:
        """Listen for the prompt events of one virtual tracker."""
        return self._async_add_event_listener(
            self._prompt_listeners, subentry_id, prompt_listener
        )

    @callback
    def async_add_reminder_listener(
        self, subentry_id: str, reminder_listener: PromptListener
    ) -> CALLBACK_TYPE:
        """Listen for the reminder events of one virtual tracker.

        A channel of its own, although both end up on the same event entity:
        the prompt and the reminder carry different data, and whoever follows
        one of them must not have to sort the other one out.
        """
        return self._async_add_event_listener(
            self._reminder_listeners, subentry_id, reminder_listener
        )

    @callback
    def _async_add_event_listener(
        self,
        listeners_by_tracker: dict[str, list[PromptListener]],
        subentry_id: str,
        event_listener: PromptListener,
    ) -> CALLBACK_TYPE:
        """Add one event listener of one tracker and return how to remove it."""
        listeners = listeners_by_tracker.setdefault(subentry_id, [])
        listeners.append(event_listener)

        @callback
        def remove_listener() -> None:
            """Remove the listener again."""
            listeners.remove(event_listener)
            if not listeners:
                listeners_by_tracker.pop(subentry_id, None)

        return remove_listener

    @callback
    def async_add_listener(
        self, update_callback: Callable[[], None], subentry_id: str | None = None
    ) -> CALLBACK_TYPE:
        """Listen for changes, either of one tracker or of the household."""
        listeners = (
            self._listeners
            if subentry_id is None
            else self._tracker_listeners.setdefault(subentry_id, [])
        )
        listeners.append(update_callback)

        @callback
        def remove_listener() -> None:
            """Remove the listener again."""
            listeners.remove(update_callback)
            if subentry_id is not None and not listeners:
                self._tracker_listeners.pop(subentry_id, None)

        return remove_listener

    @callback
    def _async_set_tracker(self, subentry_id: str, home: bool) -> bool:
        """Set a tracker state and return whether it changed.

        This is where the reminder begins and ends, whoever moved the switch: a
        tracker that goes on starts counting from now, and a tracker that goes
        off has nothing left to be reminded about, so an open reminder is
        withdrawn and the anchor is dropped.
        """
        tracker = self._trackers.setdefault(subentry_id, TrackerState())
        if tracker.home == home:
            return False
        tracker.home = home
        tracker.since = dt_util.utcnow()
        tracker.anchor = tracker.since if home else None
        self._async_schedule_save()
        self._async_notify(self._tracker_listeners.get(subentry_id, []))
        if not home:
            self._async_cancel_reminder(subentry_id, REASON_SWITCHED_OFF)
        self._async_schedule_reminder(subentry_id)
        return True

    @callback
    def _async_person_changed(self, event: Event[EventStateChangedData]) -> None:
        """Handle a state change of a configured real person."""
        home = _person_is_home(event.data["new_state"])
        if home is None:
            # Unknown, unavailable or removed: keep the last known value.
            return

        entity_id = event.data["entity_id"]
        was_known = entity_id in self._person_home
        if was_known and self._person_home[entity_id] == home:
            return

        # Only an arrival that ends an empty house resets, and only if the
        # person was known to be away before: a first known state (HA start,
        # recovery from unknown) never counts.
        resets = home and was_known and self.real_persons_home == 0
        # Cancelling is less picky than resetting: whoever is at home answers
        # the question the prompt asks, even if they were never known to be
        # away - which is what a person becoming known after a restart is.
        cancels = home and self.real_persons_home == 0
        # The prompt is the mirror image: the last known person leaves.
        departs = not home and was_known and self.real_persons_home == 1
        self._person_home[entity_id] = home
        if cancels:
            for subentry_id in list(self._prompts):
                self._async_cancel_prompt(subentry_id, REASON_PERSON_HOME)
        if resets:
            self._async_reset_trackers()
        if departs:
            self._async_ask_the_trackers()
        self._async_notify(self._listeners)

    @callback
    def _async_ask_the_trackers(self) -> None:
        """Open or schedule a prompt for every tracker that wants one."""
        for subentry_id in list(self._trackers):
            if subentry_id in self._scheduled or not self._async_may_ask(subentry_id):
                continue
            # The ID is drawn now, not when the prompt opens, so that a
            # cancellation during the delay can name the prompt it stops.
            prompt_id = uuid4().hex
            if (delay := self._prompt_delay(subentry_id)) <= 0:
                self._async_open_prompt(subentry_id, prompt_id)
                continue
            self._scheduled[subentry_id] = _Scheduled(
                prompt_id,
                async_call_later(
                    self.hass,
                    delay,
                    partial(self._async_open_prompt, subentry_id, prompt_id),
                ),
            )

    @callback
    def _async_may_ask(self, subentry_id: str) -> bool:
        """Return whether a tracker can be asked about right now."""
        return (
            self._ask_on_departure(subentry_id)
            and self.real_persons_home == 0
            and self._worth_asking(subentry_id)
        )

    @callback
    def _worth_asking(self, subentry_id: str) -> bool:
        """Return whether a prompt about a tracker makes sense at all.

        The two conditions that hold whoever asks: somebody who is at home is
        not asked about, and a tracker is only asked about once at a time.
        """
        return not self.is_home(subentry_id) and subentry_id not in self._prompts

    @callback
    def _async_open_prompt(
        self, subentry_id: str, prompt_id: str, _now: datetime | None = None
    ) -> None:
        """Open a prompt, unless the reason for it has gone away meanwhile.

        Everything is checked again: the delay can be minutes, and in that time
        somebody may have come home.
        """
        self._scheduled.pop(subentry_id, None)
        if not self._async_may_ask(subentry_id):
            _LOGGER.debug("Not asking about tracker %s after all", subentry_id)
            return
        self._async_start_prompt(subentry_id, prompt_id)

    @callback
    def _async_start_prompt(
        self, subentry_id: str, prompt_id: str, manual: bool = False
    ) -> None:
        """Open a prompt about a tracker and announce it. Asks nothing first."""
        now = dt_util.utcnow()
        prompt = Prompt(
            prompt_id=prompt_id,
            started_at=now,
            expires_at=now + timedelta(minutes=self._answer_timeout(subentry_id)),
            manual=manual,
        )
        self._prompts[subentry_id] = prompt
        self._async_schedule_save()
        self._async_start_expiry(subentry_id, prompt, now)
        self._async_notify(self._tracker_listeners.get(subentry_id, []))
        self._async_fire(
            subentry_id,
            prompt_id,
            EVENT_PROMPT_STARTED,
            {ATTR_EXPIRES_AT: prompt.expires_at.isoformat()},
        )

    @callback
    def _async_start_expiry(
        self, subentry_id: str, prompt: Prompt, now: datetime
    ) -> None:
        """Let a prompt give up when its time is up."""
        self._expiry[subentry_id] = async_call_later(
            self.hass,
            max((prompt.expires_at - now).total_seconds(), 0),
            partial(self._async_prompt_expired, subentry_id, prompt.prompt_id),
        )

    @callback
    def _async_prompt_expired(
        self, subentry_id: str, prompt_id: str, _now: datetime
    ) -> None:
        """Give up on a prompt nobody answered. Nothing else changes."""
        prompt = self._prompts.get(subentry_id)
        if prompt is None or prompt.prompt_id != prompt_id:
            return
        self._async_end_prompt(subentry_id)
        self._async_fire(subentry_id, prompt_id, EVENT_EXPIRED)

    @callback
    def _async_cancel_prompt(self, subentry_id: str, reason: str) -> None:
        """Take a prompt back, whether it is open or still waiting."""
        prompt_id: str | None = None
        if (scheduled := self._scheduled.pop(subentry_id, None)) is not None:
            scheduled.unsub()
            prompt_id = scheduled.prompt_id
        if (prompt := self._async_end_prompt(subentry_id)) is not None:
            prompt_id = prompt.prompt_id
        if prompt_id is not None:
            self._async_fire(
                subentry_id, prompt_id, EVENT_CANCELLED, {ATTR_REASON: reason}
            )

    @callback
    def _async_end_prompt(self, subentry_id: str) -> Prompt | None:
        """Close an open prompt and return it, without saying why."""
        if (unsub := self._expiry.pop(subentry_id, None)) is not None:
            unsub()
        prompt = self._prompts.pop(subentry_id, None)
        if prompt is not None:
            self._async_schedule_save()
            self._async_notify(self._tracker_listeners.get(subentry_id, []))
        return prompt

    @callback
    def _async_fire(
        self,
        subentry_id: str,
        prompt_id: str,
        event_type: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        """Announce a prompt event through the tracker's event entity."""
        subentry = self.entry.subentries.get(subentry_id)
        event_data = {
            ATTR_PROMPT_ID: prompt_id,
            ATTR_TRACKER: subentry.title if subentry is not None else "",
            **(data or {}),
        }
        for prompt_listener in list(self._prompt_listeners.get(subentry_id, [])):
            prompt_listener(event_type, event_data)

    @callback
    def _async_schedule_reminder(self, subentry_id: str) -> None:
        """Set the timer of the next reminder of a tracker, if there is to be one.

        The single place the timer is decided, called after everything that can
        change the answer: the tracker going on or off, an option that changed,
        a reminder that ended and the resume after a restart. It always starts
        by dropping the timer that was there, so it can be called as often as
        it likes.

        A reminder that is already due - the tracker has been on for longer
        than the interval, because Home Assistant was off or because the
        interval was only just set - opens on the spot rather than one interval
        from now. That is the whole point of the safety net.
        """
        if (unsub := self._due.pop(subentry_id, None)) is not None:
            unsub()
        if subentry_id in self._reminders:
            # One reminder at a time; the next timer starts when this one ends.
            return
        hours = self._remind_after(subentry_id)
        if hours <= 0 or not self.is_home(subentry_id):
            return
        now = dt_util.utcnow()
        due = self._anchor(subentry_id, now) + timedelta(hours=hours)
        if due <= now:
            self._async_start_reminder(subentry_id)
            return
        self._due[subentry_id] = async_call_later(
            self.hass,
            (due - now).total_seconds(),
            partial(self._async_reminder_due, subentry_id),
        )

    @callback
    def _async_reminder_due(self, subentry_id: str, _now: datetime) -> None:
        """Open the reminder of a tracker, unless the reason for it has gone.

        The interval can be days, and in that time the tracker may have been
        switched off or the option taken back.
        """
        self._due.pop(subentry_id, None)
        if self._remind_after(subentry_id) <= 0 or not self.is_home(subentry_id):
            return
        if subentry_id in self._reminders:
            return
        self._async_start_reminder(subentry_id)

    @callback
    def _async_start_reminder(self, subentry_id: str) -> None:
        """Open a reminder about a tracker and announce it. Asks nothing first."""
        if (unsub := self._due.pop(subentry_id, None)) is not None:
            unsub()
        now = dt_util.utcnow()
        reminder = Reminder(
            reminder_id=uuid4().hex,
            started_at=now,
            # The reminder's own answer time, not the prompt's: a question
            # about a whole day may well be answered an hour later.
            expires_at=now + timedelta(minutes=self._reminder_timeout(subentry_id)),
        )
        self._reminders[subentry_id] = reminder
        self._async_schedule_save()
        self._async_start_reminder_expiry(subentry_id, reminder, now)
        self._async_notify(self._tracker_listeners.get(subentry_id, []))
        self._async_fire_reminder(
            subentry_id,
            reminder.reminder_id,
            EVENT_REMINDER_STARTED,
            {ATTR_EXPIRES_AT: reminder.expires_at.isoformat()},
        )

    @callback
    def _async_start_reminder_expiry(
        self, subentry_id: str, reminder: Reminder, now: datetime
    ) -> None:
        """Let a reminder give up when its time is up."""
        self._reminder_expiry[subentry_id] = async_call_later(
            self.hass,
            max((reminder.expires_at - now).total_seconds(), 0),
            partial(self._async_reminder_expired, subentry_id, reminder.reminder_id),
        )

    @callback
    def _async_reminder_expired(
        self, subentry_id: str, reminder_id: str, _now: datetime
    ) -> None:
        """Give up on a reminder nobody answered.

        Nothing changes but the anchor: no answer never switches anything, here
        as everywhere else in this integration. Moving the anchor is what makes
        the next reminder come one interval from now instead of at once.
        """
        reminder = self._reminders.get(subentry_id)
        if reminder is None or reminder.reminder_id != reminder_id:
            return
        self._async_end_reminder(subentry_id)
        self._async_set_anchor(subentry_id, dt_util.utcnow())
        self._async_schedule_reminder(subentry_id)
        self._async_fire_reminder(subentry_id, reminder_id, EVENT_REMINDER_EXPIRED)

    @callback
    def _async_cancel_reminder(self, subentry_id: str, reason: str) -> None:
        """Take an open reminder back, saying why. The anchor is left alone."""
        if (reminder := self._async_end_reminder(subentry_id)) is None:
            return
        self._async_fire_reminder(
            subentry_id,
            reminder.reminder_id,
            EVENT_REMINDER_CANCELLED,
            {ATTR_REASON: reason},
        )

    @callback
    def _async_end_reminder(self, subentry_id: str) -> Reminder | None:
        """Close an open reminder and return it, without saying why."""
        if (unsub := self._reminder_expiry.pop(subentry_id, None)) is not None:
            unsub()
        reminder = self._reminders.pop(subentry_id, None)
        if reminder is not None:
            self._async_schedule_save()
            self._async_notify(self._tracker_listeners.get(subentry_id, []))
        return reminder

    @callback
    def _async_fire_reminder(
        self,
        subentry_id: str,
        reminder_id: str,
        event_type: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        """Announce a reminder event through the tracker's event entity."""
        subentry = self.entry.subentries.get(subentry_id)
        event_data = {
            ATTR_REMINDER_ID: reminder_id,
            ATTR_TRACKER: subentry.title if subentry is not None else "",
            **(data or {}),
        }
        for reminder_listener in list(self._reminder_listeners.get(subentry_id, [])):
            reminder_listener(event_type, event_data)

    @callback
    def _async_set_anchor(self, subentry_id: str, when: datetime) -> None:
        """Start counting towards the next reminder from a new moment."""
        if (tracker := self._trackers.get(subentry_id)) is None:
            return
        tracker.anchor = when
        self._async_schedule_save()

    def _anchor(self, subentry_id: str, default: datetime) -> datetime:
        """Return what the reminder of a tracker counts from.

        A tracker that was switched on before M3a has no anchor of its own, and
        its last change is the moment it was switched on - which is exactly
        what the anchor would have been.
        """
        tracker = self._trackers.get(subentry_id)
        if tracker is None:
            return default
        return tracker.anchor or tracker.since or default

    def _option(self, subentry_id: str, key: str, default: Any) -> Any:
        """Return one option of a tracker, or its default."""
        subentry = self.entry.subentries.get(subentry_id)
        if subentry is None:
            return default
        return subentry.data.get(key, default)

    def _ask_on_departure(self, subentry_id: str) -> bool:
        """Return whether a tracker asks when the house empties."""
        return bool(self.option(subentry_id, CONF_ASK_ON_DEPARTURE))

    def _answer_timeout(self, subentry_id: str) -> int:
        """Return how many minutes a prompt of a tracker stays open."""
        return int(self.option(subentry_id, CONF_ANSWER_TIMEOUT))

    def _prompt_delay(self, subentry_id: str) -> int:
        """Return how many seconds a tracker waits before it asks."""
        return int(self.option(subentry_id, CONF_PROMPT_DELAY))

    def _remind_after(self, subentry_id: str) -> int:
        """Return after how many hours at home a tracker reminds; 0 is never."""
        return int(self.option(subentry_id, CONF_REMIND_AFTER))

    def _reminder_timeout(self, subentry_id: str) -> int:
        """Return how many minutes a reminder of a tracker stays open.

        The reminder's own answer time. The prompt keeps `_answer_timeout()`:
        the two questions are asked in different situations and are given very
        different amounts of time.
        """
        return int(self.option(subentry_id, CONF_REMINDER_TIMEOUT))

    @callback
    def _async_reset_trackers(self) -> None:
        """Switch off the trackers that reset when the house is entered."""
        for subentry_id, tracker in list(self._trackers.items()):
            if not tracker.home:
                continue
            if not self.option(subentry_id, CONF_RESET_ON_RETURN):
                continue
            _LOGGER.debug("Resetting tracker %s: a real person came home", subentry_id)
            self._async_set_tracker(subentry_id, False)

    @callback
    def _async_notify(self, listeners: list[Callable[[], None]]) -> None:
        """Call the given listeners."""
        for listener in list(listeners):
            listener()

    @callback
    def _async_schedule_save(self) -> None:
        """Persist the tracker states, batching rapid changes."""
        self._store.async_delay_save(self._data_to_store, STORAGE_SAVE_DELAY)

    @callback
    def _data_to_store(self) -> StoredData:
        """Return the data to persist."""
        return {
            "trackers": {
                subentry_id: {
                    "home": tracker.home,
                    "since": tracker.since.isoformat() if tracker.since else None,
                    "anchor": tracker.anchor.isoformat() if tracker.anchor else None,
                }
                for subentry_id, tracker in self._trackers.items()
            },
            "prompts": {
                subentry_id: {
                    "prompt_id": prompt.prompt_id,
                    "started_at": prompt.started_at.isoformat(),
                    "expires_at": prompt.expires_at.isoformat(),
                    "manual": prompt.manual,
                }
                for subentry_id, prompt in self._prompts.items()
            },
            "reminders": {
                subentry_id: {
                    "reminder_id": reminder.reminder_id,
                    "started_at": reminder.started_at.isoformat(),
                    "expires_at": reminder.expires_at.isoformat(),
                }
                for subentry_id, reminder in self._reminders.items()
            },
        }
