"""Presence sources of the virtual trackers (M3e).

A tracker may follow entities whose state says whether somebody is at home - a
`device_tracker` (present = `home`) or a `binary_sensor` (present = `on`) - and
Bluetooth devices by address, which count as present while an advertisement
was heard within `away_after`. The tracker counts as present while **any** of
its sources is.

Only edges switch: the sources becoming present switches the tracker on, the
sources having been absent for `away_after` minutes switches it off. Between
two edges the tracker is the user's, so a manual change sticks. A state that is
not known - `unknown`, `unavailable`, a missing entity, a Bluetooth address
during the first `away_after` of listening - is never absence by itself: the
last known value is kept, and the very first known value is a baseline, not an
edge. Nothing here is persisted; every start and every change of the sources
starts from a fresh baseline, and the absence clock never starts before it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import partial
import logging
from typing import TYPE_CHECKING

from homeassistant.const import STATE_HOME, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
)
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from . import ble
from .const import (
    BINARY_SENSOR_DOMAIN,
    BLE_POLL_INTERVAL,
    CONF_AWAY_AFTER,
    CONF_BLE_SOURCES,
    CONF_PRESENCE_SOURCES,
    DEVICE_TRACKER_DOMAIN,
    DOMAIN,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from .manager import HouseholdManager

_LOGGER = logging.getLogger(__name__)

# The state that means "present", per domain a presence source may have.
_PRESENT_STATE = {DEVICE_TRACKER_DOMAIN: STATE_HOME, BINARY_SENSOR_DOMAIN: STATE_ON}
_NOT_KNOWN = frozenset({STATE_UNAVAILABLE, STATE_UNKNOWN})

# What one source, or all sources of a tracker together, say: present, absent
# or not known - and for absent, since when.
type Reading = tuple[bool | None, datetime | None]


@callback
def async_own_presence_entities(hass: HomeAssistant) -> set[str]:
    """Return the device trackers and binary sensors of this integration itself.

    A virtual tracker that followed a virtual tracker - or the household
    sensor, which follows all of them - would be a loop waiting to happen. They
    are found through the entity registry, never by name.
    """
    return {
        entry.entity_id
        for entry in er.async_get(hass).entities.values()
        if entry.platform == DOMAIN and entry.domain in _PRESENT_STATE
    }


@dataclass(slots=True)
class _Follow:
    """What is known about the presence sources of one tracker.

    ``since`` is when following exactly these sources began - the start of the
    entry or the last change of the sources - and nothing is ever counted as
    absent from before it. ``present`` is the last *known* value of all sources
    together, ``None`` until one is known. ``absent_since`` is when the current
    absence began, for as long as it has not switched the tracker off yet.
    """

    entities: tuple[str, ...]
    addresses: tuple[str, ...]
    since: datetime
    present: bool | None = None
    absent_since: datetime | None = None
    unsub_off: CALLBACK_TYPE | None = None


class TrackerPresence:
    """Follow the presence sources of every tracker of a config entry."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, manager: HouseholdManager
    ) -> None:
        """Bind the follower to the entry and to the manager it switches."""
        self.hass = hass
        self._entry = entry
        self._manager = manager
        self._follows: dict[str, _Follow] = {}
        # One state listener over the entity sources of every tracker, and one
        # poll while at least one tracker follows a Bluetooth address.
        self._entities: frozenset[str] = frozenset()
        self._unsub_entities: CALLBACK_TYPE | None = None
        self._unsub_poll: CALLBACK_TYPE | None = None

    @callback
    def async_start(self) -> None:
        """Take the baseline of every tracker's sources and start following."""
        self.async_sources_changed()

    @callback
    def async_stop(self) -> None:
        """Stop following: no listener, no poll and no timer is left behind."""
        if self._unsub_entities is not None:
            self._unsub_entities()
            self._unsub_entities = None
        self._entities = frozenset()
        if self._unsub_poll is not None:
            self._unsub_poll()
            self._unsub_poll = None
        for follow in self._follows.values():
            self._async_cancel_off(follow)
        self._follows.clear()

    def has_sources(self, subentry_id: str) -> bool:
        """Return whether a tracker has at least one presence source."""
        entities, addresses = self._sources(subentry_id)
        return bool(entities or addresses)

    def is_present(self, subentry_id: str) -> bool:
        """Return whether the sources of a tracker were last known as present."""
        follow = self._follows.get(subentry_id)
        return follow is not None and follow.present is True

    @callback
    def async_update(self, subentry_id: str) -> None:
        """Look at the sources of one tracker right now."""
        if (follow := self._follows.get(subentry_id)) is not None:
            self._async_evaluate(subentry_id, follow)

    @callback
    def async_sources_changed(self) -> None:
        """Take in a change of the sources or of `away_after`, without a reload.

        A tracker whose sources changed starts again from a fresh baseline: the
        old value said something about other sources. A tracker whose sources
        are the same keeps what it knows, but its pending switch-off is moved,
        because `away_after` may have changed - and so may the window in which
        a Bluetooth advertisement counts. Calling this twice changes nothing.
        """
        now = dt_util.utcnow()
        tracker_ids = self._manager.tracker_ids
        for subentry_id in list(self._follows):
            if subentry_id not in tracker_ids:
                self._async_cancel_off(self._follows.pop(subentry_id))
        for subentry_id in tracker_ids:
            entities, addresses = self._sources(subentry_id)
            follow = self._follows.get(subentry_id)
            if not entities and not addresses:
                if follow is not None:
                    self._async_cancel_off(self._follows.pop(subentry_id))
                continue
            if follow is None or (follow.entities, follow.addresses) != (
                entities,
                addresses,
            ):
                if follow is not None:
                    self._async_cancel_off(follow)
                follow = _Follow(entities, addresses, now)
                self._follows[subentry_id] = follow
            self._async_evaluate(subentry_id, follow)
            if self._follows.get(subentry_id) is follow:
                self._async_schedule_off(subentry_id, follow)
        self._async_follow_entities()
        self._async_follow_addresses()

    def _sources(self, subentry_id: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Return the entities and the Bluetooth addresses a tracker follows.

        The integration's own device trackers and household sensor are left
        out whatever is stored, and so is anything that is neither a device
        tracker nor a binary sensor or not a valid address.
        """
        subentry = self._entry.subentries.get(subentry_id)
        if subentry is None:
            return (), ()
        entities = tuple(
            dict.fromkeys(
                entity_id
                for raw in subentry.data.get(CONF_PRESENCE_SOURCES, [])
                if (entity_id := str(raw).lower()).partition(".")[0] in _PRESENT_STATE
                and not self._is_own(entity_id)
            )
        )
        addresses = tuple(
            dict.fromkeys(
                address
                for raw in subentry.data.get(CONF_BLE_SOURCES, [])
                if (address := ble.normalize_address(str(raw))) is not None
            )
        )
        return entities, addresses

    def _is_own(self, entity_id: str) -> bool:
        """Return whether an entity belongs to this integration.

        Looked up every time rather than once: on the very first setup the
        integration's own entities are registered only after the manager has
        started, and one of them must never count, then or later.
        """
        registry_entry = er.async_get(self.hass).async_get(entity_id)
        return registry_entry is not None and registry_entry.platform == DOMAIN

    def _away_after(self, subentry_id: str) -> timedelta:
        """Return how long a tracker's sources have to be absent."""
        return timedelta(
            minutes=int(self._manager.option(subentry_id, CONF_AWAY_AFTER))
        )

    @callback
    def _async_evaluate(self, subentry_id: str, follow: _Follow) -> None:
        """Act on what the sources of a tracker say now - on edges only.

        Not known changes nothing. Present after absent switches the tracker
        on; absent after present (or as the first known value) starts the
        absence clock. The first known value never switches anything on.
        """
        present, absent_since = self._reading(subentry_id, follow)
        if present is None:
            return
        previous = follow.present
        follow.present = present
        if present:
            self._async_cancel_off(follow)
            follow.absent_since = None
            if previous is False and not self._manager.is_home(subentry_id):
                _LOGGER.debug(
                    "Switching tracker %s on: a presence source is present",
                    subentry_id,
                )
                self._manager.async_set_home(subentry_id, True)
            return
        if previous is not False:
            follow.absent_since = absent_since
            self._async_schedule_off(subentry_id, follow)

    def _reading(self, subentry_id: str, follow: _Follow) -> Reading:
        """Return what all sources of a tracker say together.

        Present while any source is present; otherwise absent if at least one
        source is known to be absent - since the latest of their absences,
        because before that one of them was still there - and not known when
        none of them is known.
        """
        now = dt_util.utcnow()
        readings = [
            self._entity_reading(entity_id, follow.since)
            for entity_id in follow.entities
        ]
        if follow.addresses:
            readings.extend(
                self._address_readings(follow, now, self._away_after(subentry_id))
            )
        if any(present is True for present, _ in readings):
            return True, None
        absences = [
            since
            for present, since in readings
            if present is False and since is not None
        ]
        if absences:
            return False, max(absences)
        return None, None

    def _entity_reading(self, entity_id: str, since: datetime) -> Reading:
        """Return what one entity source says. Our own entities say nothing."""
        if self._is_own(entity_id):
            return None, None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in _NOT_KNOWN:
            return None, None
        if state.state == _PRESENT_STATE[entity_id.partition(".")[0]]:
            return True, None
        return False, max(state.last_changed, since)

    def _address_readings(
        self, follow: _Follow, now: datetime, away_after: timedelta
    ) -> list[Reading]:
        """Return what each Bluetooth source of a tracker says.

        Present when the address was heard within `away_after`. Not heard for
        that long counts as absent only once the tracker has been listening for
        that long: right after a start the manager's history is empty, and an
        address that simply has not been heard *yet* is not known to be away.
        Without the Bluetooth component nothing is known at all.
        """
        if not ble.async_bluetooth_loaded(self.hass):
            return [(None, None)] * len(follow.addresses)
        listening = now - follow.since >= away_after
        readings: list[Reading] = []
        for address in follow.addresses:
            age = ble.async_seconds_since_heard(self.hass, address)
            if age is not None and age < away_after.total_seconds():
                readings.append((True, None))
            elif not listening:
                readings.append((None, None))
            else:
                heard = (
                    now - timedelta(seconds=age) if age is not None else follow.since
                )
                readings.append((False, max(heard, follow.since)))
        return readings

    @callback
    def _async_schedule_off(self, subentry_id: str, follow: _Follow) -> None:
        """Set the switch-off of a tracker whose sources are absent.

        The one place the timer is decided, from when the absence began and the
        `away_after` of right now. An absence that is already long enough
        switches off on the spot.
        """
        self._async_cancel_off(follow)
        if follow.absent_since is None:
            return
        due = follow.absent_since + self._away_after(subentry_id)
        now = dt_util.utcnow()
        if due <= now:
            self._async_away(subentry_id, follow)
            return
        follow.unsub_off = async_call_later(
            self.hass,
            (due - now).total_seconds(),
            partial(self._async_away_due, subentry_id),
        )

    @callback
    def _async_away_due(self, subentry_id: str, _now: datetime) -> None:
        """Switch a tracker off when its sources have been absent for long enough."""
        follow = self._follows.get(subentry_id)
        if follow is None:
            return
        follow.unsub_off = None
        if follow.absent_since is not None:
            self._async_away(subentry_id, follow)

    @callback
    def _async_away(self, subentry_id: str, follow: _Follow) -> None:
        """Switch a tracker off for an absence, once per absence."""
        self._async_cancel_off(follow)
        follow.absent_since = None
        if self._manager.is_home(subentry_id):
            _LOGGER.debug(
                "Switching tracker %s off: its presence sources are absent",
                subentry_id,
            )
            self._manager.async_set_home(subentry_id, False)

    @callback
    def _async_cancel_off(self, follow: _Follow) -> None:
        """Drop the pending switch-off of a tracker, if there is one."""
        if follow.unsub_off is not None:
            follow.unsub_off()
            follow.unsub_off = None

    @callback
    def _async_follow_entities(self) -> None:
        """Listen to the entity sources that are configured right now."""
        entities = frozenset(
            entity_id
            for follow in self._follows.values()
            for entity_id in follow.entities
        )
        if entities == self._entities:
            return
        if self._unsub_entities is not None:
            self._unsub_entities()
            self._unsub_entities = None
        self._entities = entities
        if entities:
            self._unsub_entities = async_track_state_change_event(
                self.hass, list(entities), self._async_entity_changed
            )

    @callback
    def _async_entity_changed(self, event: Event[EventStateChangedData]) -> None:
        """Look at the trackers an entity source belongs to."""
        entity_id = event.data["entity_id"]
        for subentry_id, follow in list(self._follows.items()):
            if entity_id in follow.entities:
                self._async_evaluate(subentry_id, follow)

    @callback
    def _async_follow_addresses(self) -> None:
        """Poll the Bluetooth sources while at least one is configured."""
        wanted = any(follow.addresses for follow in self._follows.values())
        if wanted and self._unsub_poll is None:
            self._unsub_poll = async_track_time_interval(
                self.hass,
                self._async_poll,
                timedelta(seconds=BLE_POLL_INTERVAL),
                name=f"{DOMAIN} Bluetooth presence",
                cancel_on_shutdown=True,
            )
        elif not wanted and self._unsub_poll is not None:
            self._unsub_poll()
            self._unsub_poll = None

    @callback
    def _async_poll(self, _now: datetime) -> None:
        """Look at every tracker that follows a Bluetooth address."""
        for subentry_id, follow in list(self._follows.items()):
            if follow.addresses:
                self._async_evaluate(subentry_id, follow)
