"""Repair issues and person validation of the Virtual Presence Tracker.

A virtual tracker does nothing until its `device_tracker` is attached to a
`person`, and a person that carries one of our trackers must never be a
configured real person: switching that tracker on would look like a real
arrival and reset every tracker at once. Neither is visible from the
integration's page, so both are reported as repair issues - together with a
configured real person whose entity is gone. The config flow refuses the
dangerous assignment up front, the issues cover the case where it happens
afterwards.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from homeassistant.components.device_tracker import DOMAIN as DEVICE_TRACKER_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_DOMAIN,
    EVENT_SERVICE_REGISTERED,
    EVENT_SERVICE_REMOVED,
)
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
)
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.helpers.event import TrackStates, async_track_state_change_filtered
from homeassistant.helpers.start import async_at_started

from .const import (
    ATTR_DEVICE_TRACKERS,
    CONF_ASK_ON_DEPARTURE,
    CONF_CREATE_PERSON,
    CONF_PERSONS,
    DEFAULT_ASK_ON_DEPARTURE,
    DOMAIN,
    NOTIFY_DOMAIN,
    PERSON_DOMAIN,
    SUBENTRY_TYPE_TRACKER,
)
from .delivery import async_notify_services, async_recipients

if TYPE_CHECKING:
    from . import VirtualPresenceTrackerConfigEntry

ISSUE_NO_TRACKER = "no_tracker"
ISSUE_TRACKER_NOT_ASSIGNED = "tracker_not_assigned"
ISSUE_REAL_PERSON_HAS_VIRTUAL_TRACKER = "real_person_has_virtual_tracker"
ISSUE_REAL_PERSON_MISSING = "real_person_missing"
ISSUE_RECIPIENT_WITHOUT_PHONE = "recipient_without_phone"


@callback
def async_tracker_entities(
    hass: HomeAssistant, entry: ConfigEntry | None
) -> dict[str, str]:
    """Return the device tracker entity ID of every tracker, by subentry ID.

    The entity registry is the only place that knows which entity belongs to
    which virtual tracker. ``entry`` is ``None`` while the integration is being
    set up for the first time: there are no trackers yet, so there is nothing
    to find.
    """
    if entry is None:
        return {}
    registry = er.async_get(hass)
    return {
        entity.config_subentry_id: entity.entity_id
        for entity in er.async_entries_for_config_entry(registry, entry.entry_id)
        if entity.domain == DEVICE_TRACKER_DOMAIN
        and entity.platform == DOMAIN
        and entity.config_subentry_id is not None
    }


@callback
def async_persons_with_virtual_tracker(
    hass: HomeAssistant, entry: ConfigEntry | None, persons: Iterable[str]
) -> list[str]:
    """Return which of the given persons carry one of our virtual trackers."""
    tracker_ids = set(async_tracker_entities(hass, entry).values())
    if not tracker_ids:
        return []
    return [
        person
        for person in persons
        if _async_attached_trackers(hass, person, tracker_ids)
    ]


@callback
def _async_attached_trackers(
    hass: HomeAssistant, person: str, tracker_ids: set[str]
) -> list[str]:
    """Return the trackers out of ``tracker_ids`` a person is following."""
    if (state := hass.states.get(person)) is None:
        return []
    return [
        entity_id
        for entity_id in state.attributes.get(ATTR_DEVICE_TRACKERS) or ()
        if entity_id in tracker_ids
    ]


class HouseholdIssues:
    """Keep the repair issues of a config entry up to date."""

    def __init__(
        self, hass: HomeAssistant, entry: VirtualPresenceTrackerConfigEntry
    ) -> None:
        """Initialise the issues of an entry. Call async_start() to begin."""
        self.hass = hass
        self.entry = entry
        # Every issue ID of this entry starts with the entry ID, so all of them
        # can be found again without remembering what was raised.
        self._prefix = f"{entry.entry_id}_"
        self._unsubs: list[CALLBACK_TYPE] = []
        self._checking = False

    @callback
    def async_recheck(self) -> None:
        """Check again, for a change that nothing else here follows.

        Before Home Assistant has started there is nothing to check: the person
        states do not exist yet, and checking would report every tracker as
        unassigned.
        """
        if self._checking:
            self._async_check()

    @callback
    def async_start(self) -> None:
        """Start checking once Home Assistant has started.

        At startup the `person` entities may not exist yet, which would make
        every tracker look unassigned and every real person gone. Waiting for
        the started event is what keeps those false issues away.
        """
        self._unsubs.append(async_at_started(self.hass, self._async_started))

    @callback
    def async_stop(self) -> None:
        """Stop checking and clear the issues of this entry."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        self._checking = False
        self._async_apply({})

    @callback
    def _async_started(self, hass: HomeAssistant) -> None:
        """Check once and follow the persons and the notify services."""
        tracker = async_track_state_change_filtered(
            hass,
            TrackStates(False, set(), {PERSON_DOMAIN}),
            self._async_person_changed,
        )
        self._unsubs.append(tracker.async_remove)
        # A phone that registers with the Companion App brings a notify service
        # with it, and unregistering takes it away again. Both decide whether a
        # chosen recipient can be reached, so both re-check.
        for event_type in (EVENT_SERVICE_REGISTERED, EVENT_SERVICE_REMOVED):
            self._unsubs.append(
                hass.bus.async_listen(event_type, self._async_service_changed)
            )
        self._checking = True
        self._async_check()

    @callback
    def _async_service_changed(self, event: Event[dict[str, str]]) -> None:
        """Re-check after a notify service appeared or disappeared."""
        if event.data.get(ATTR_DOMAIN) == NOTIFY_DOMAIN:
            self._async_check()

    @callback
    def _async_person_changed(self, event: Event[EventStateChangedData]) -> None:
        """Re-check after a person appeared, went away or changed trackers."""
        old_state = event.data["old_state"]
        new_state = event.data["new_state"]
        if (
            old_state is not None
            and new_state is not None
            and old_state.attributes.get(ATTR_DEVICE_TRACKERS)
            == new_state.attributes.get(ATTR_DEVICE_TRACKERS)
        ):
            # A person coming or going changes nothing about who has which
            # tracker, and persons change state a lot.
            return
        self._async_check()

    @callback
    def _async_check(self) -> None:
        """Bring the issues in line with how the household is set up."""
        self._async_apply(self._async_wanted_issues())

    @callback
    def _async_wanted_issues(self) -> dict[str, tuple[str, dict[str, str]]]:
        """Return translation key and placeholders per issue ID."""
        issues: dict[str, tuple[str, dict[str, str]]] = {}
        trackers = async_tracker_entities(self.hass, self.entry)
        tracker_ids = set(trackers.values())
        followed = {
            entity_id
            for state in self.hass.states.async_all(PERSON_DOMAIN)
            for entity_id in state.attributes.get(ATTR_DEVICE_TRACKERS) or ()
        }

        subentries = self.entry.get_subentries_of_type(SUBENTRY_TYPE_TRACKER)
        if not subentries:
            # The setup chains into the form that adds a tracker, but the user
            # can close it. Without a tracker the entry does nothing at all, and
            # the button to add one is easy to miss.
            issues[self._issue_id(ISSUE_NO_TRACKER)] = (ISSUE_NO_TRACKER, {})

        for subentry in subentries:
            entity_id = trackers.get(subentry.subentry_id)
            if entity_id is None or entity_id in followed:
                continue
            if subentry.data.get(CONF_CREATE_PERSON):
                # The person of this tracker is still to be created (M2g).
                # Reporting it as unassigned in that moment would be a warning
                # about something that is about to happen by itself; the marker
                # is taken off either way, and the check runs again then.
                continue
            issues[self._issue_id(ISSUE_TRACKER_NOT_ASSIGNED, subentry.subentry_id)] = (
                ISSUE_TRACKER_NOT_ASSIGNED,
                {"name": subentry.title, "entity_id": entity_id},
            )

        # A recipient without a phone is reported once per person: the same
        # person is usually chosen for several trackers, and one issue that
        # names them all is one notification instead of three.
        without_phone: dict[str, list[str]] = {}
        for subentry in subentries:
            if not subentry.data.get(CONF_ASK_ON_DEPARTURE, DEFAULT_ASK_ON_DEPARTURE):
                continue
            for person in async_recipients(self.entry, subentry.subentry_id):
                if not async_notify_services(self.hass, person):
                    without_phone.setdefault(person, []).append(subentry.title)
        for person, names in without_phone.items():
            issues[self._issue_id(ISSUE_RECIPIENT_WITHOUT_PHONE, person)] = (
                ISSUE_RECIPIENT_WITHOUT_PHONE,
                {"person": person, "tracker": ", ".join(names)},
            )

        for person in self.entry.data.get(CONF_PERSONS, []):
            if self.hass.states.get(person) is None:
                issues[self._issue_id(ISSUE_REAL_PERSON_MISSING, person)] = (
                    ISSUE_REAL_PERSON_MISSING,
                    {"person": person},
                )
                continue
            for entity_id in _async_attached_trackers(self.hass, person, tracker_ids):
                issue_id = self._issue_id(
                    ISSUE_REAL_PERSON_HAS_VIRTUAL_TRACKER, person, entity_id
                )
                issues[issue_id] = (
                    ISSUE_REAL_PERSON_HAS_VIRTUAL_TRACKER,
                    {"person": person, "tracker": entity_id},
                )

        return issues

    @callback
    def _async_apply(self, wanted: dict[str, tuple[str, dict[str, str]]]) -> None:
        """Raise the wanted issues and delete every other issue of this entry."""
        registry = ir.async_get(self.hass)
        for domain, issue_id in list(registry.issues):
            if (
                domain == DOMAIN
                and issue_id.startswith(self._prefix)
                and issue_id not in wanted
            ):
                ir.async_delete_issue(self.hass, DOMAIN, issue_id)

        for issue_id, (translation_key, placeholders) in wanted.items():
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                is_persistent=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=translation_key,
                translation_placeholders=placeholders,
            )

    def _issue_id(self, translation_key: str, *parts: str) -> str:
        """Return the stable ID of one issue of this entry."""
        return "_".join((self.entry.entry_id, translation_key, *parts))
