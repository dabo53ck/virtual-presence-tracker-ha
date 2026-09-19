"""Household state of the Virtual Presence Tracker integration.

The manager owns the state of every virtual tracker and the presence of the
configured real persons. It is the single source of truth: the entities of the
later milestones are thin views on it, so the state survives a restart and is
already correct before the platforms are set up (see docs/DESIGN.md).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import logging
from typing import TYPE_CHECKING, TypedDict

from homeassistant.const import STATE_HOME, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_PERSONS,
    CONF_RESET_ON_RETURN,
    DEFAULT_RESET_ON_RETURN,
    STORAGE_KEY_PREFIX,
    STORAGE_SAVE_DELAY,
    STORAGE_VERSION,
    SUBENTRY_TYPE_TRACKER,
)

if TYPE_CHECKING:
    from . import VirtualPresenceTrackerConfigEntry

_LOGGER = logging.getLogger(__name__)


class StoredTracker(TypedDict):
    """Persisted state of a single virtual tracker."""

    home: bool
    since: str | None


class StoredData(TypedDict):
    """Persisted state of a config entry."""

    trackers: dict[str, StoredTracker]


@dataclass(slots=True)
class TrackerState:
    """In-memory state of a single virtual tracker."""

    home: bool = False
    since: datetime | None = None


def _person_is_home(state: State | None) -> bool | None:
    """Return whether a person is home, or None if their state is unknown.

    Every state other than ``home`` (``not_home``, a zone name, …) counts as
    away.
    """
    if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
        return None
    return state.state == STATE_HOME


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

    async def async_load(self) -> None:
        """Load the persisted tracker states.

        Must be awaited before any platform is set up, so that the entities
        report the restored state from their first write on. Trackers whose
        subentry is gone are pruned.
        """
        stored = await self._store.async_load()
        stored_trackers = stored["trackers"] if stored else {}
        known_ids = [
            subentry.subentry_id
            for subentry in self.entry.get_subentries_of_type(SUBENTRY_TYPE_TRACKER)
        ]

        trackers: dict[str, TrackerState] = {}
        for subentry_id in known_ids:
            if (stored_tracker := stored_trackers.get(subentry_id)) is None:
                trackers[subentry_id] = TrackerState()
                continue
            since = stored_tracker.get("since")
            trackers[subentry_id] = TrackerState(
                home=bool(stored_tracker.get("home")),
                since=dt_util.parse_datetime(since) if since else None,
            )
        self._trackers = trackers

        if stored_trackers.keys() - set(known_ids):
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

    async def async_stop(self) -> None:
        """Unsubscribe and write the current state to disk."""
        if self._unsub_persons is not None:
            self._unsub_persons()
            self._unsub_persons = None
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

    @callback
    def async_set_home(self, subentry_id: str, home: bool) -> None:
        """Set a virtual tracker home or away."""
        if self._async_set_tracker(subentry_id, home):
            self._async_notify(self._listeners)

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
        """Set a tracker state and return whether it changed."""
        tracker = self._trackers.setdefault(subentry_id, TrackerState())
        if tracker.home == home:
            return False
        tracker.home = home
        tracker.since = dt_util.utcnow()
        self._async_schedule_save()
        self._async_notify(self._tracker_listeners.get(subentry_id, []))
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
        self._person_home[entity_id] = home
        if resets:
            self._async_reset_trackers()
        self._async_notify(self._listeners)

    @callback
    def _async_reset_trackers(self) -> None:
        """Switch off the trackers that reset when the house is entered."""
        for subentry_id, tracker in list(self._trackers.items()):
            if not tracker.home:
                continue
            subentry = self.entry.subentries.get(subentry_id)
            if subentry is not None and not subentry.data.get(
                CONF_RESET_ON_RETURN, DEFAULT_RESET_ON_RETURN
            ):
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
                }
                for subentry_id, tracker in self._trackers.items()
            }
        }
