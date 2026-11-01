"""Diagnostics of the Virtual Presence Tracker.

What "Download diagnostics" on the integration's page hands out for a bug
report: how the household is set up and what the manager is doing right now -
and nothing that could name somebody. Tracker names, persons, the entity IDs of
the sources (usually named after a device or a room) and Bluetooth addresses
are replaced by neutral labels such as `tracker_1`, `person_2` or `ble_1`, the
same label for the same value everywhere in one download, so that one person
or one source can still be followed through it. Notify services, user IDs,
`answered_by`, the entry and subentry IDs and the raw states of the sources
(a device tracker's state can be the name of a zone) are left out altogether.
Home Assistant's `async_redact_data` is not used: its `**REDACTED**` would
make every tracker look the same.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_HOME, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.loader import async_get_integration

from . import ble
from .const import (
    BINARY_SENSOR_DOMAIN,
    CONF_AWAY_AFTER,
    CONF_BLE_SOURCES,
    CONF_BUTTON_AWAY_TYPES,
    CONF_BUTTON_HOME_TYPES,
    CONF_BUTTON_SOURCES,
    CONF_CREATE_PERSON,
    CONF_NOTIFY_PERSONS,
    CONF_PERSONS,
    CONF_PRESENCE_SOURCES,
    DEVICE_TRACKER_DOMAIN,
    DOMAIN,
    OPTION_DEFAULTS,
    SUBENTRY_TYPE_TRACKER,
)
from .delivery import async_notify_services
from .issues import async_entity_missing
from .manager import async_own_event_entities
from .presence import async_own_presence_entities

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigSubentry

    from . import VirtualPresenceTrackerConfigEntry
    from .manager import HouseholdManager

# The state that means "present", per domain a presence source may have - the
# same rule the follower applies (presence.py).
_PRESENT_STATE = {DEVICE_TRACKER_DOMAIN: STATE_HOME, BINARY_SENSOR_DOMAIN: STATE_ON}


class _Labels:
    """Hand out one neutral label per kind and value, the same one every time."""

    def __init__(self) -> None:
        """Start without any label."""
        self._labels: dict[str, dict[str, str]] = {}

    def __call__(self, kind: str, value: str) -> str:
        """Return the label of a value, `<kind>_<n>` in order of first use."""
        labels = self._labels.setdefault(kind, {})
        if value not in labels:
            labels[value] = f"{kind}_{len(labels) + 1}"
        return labels[value]


def _iso(value: datetime | None) -> str | None:
    """Return a timestamp as ISO text, or None."""
    return value.isoformat() if value is not None else None


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: VirtualPresenceTrackerConfigEntry
) -> dict[str, Any]:
    """Return the diagnostics of the config entry, without anything personal."""
    integration = await async_get_integration(hass, DOMAIN)
    label = _Labels()
    manager: HouseholdManager | None = None
    if entry.state is ConfigEntryState.LOADED and (
        data := getattr(entry, "runtime_data", None)
    ):
        manager = data.manager

    # The real persons first, so that `person_1` is the first one configured.
    persons = [str(person).lower() for person in entry.data.get(CONF_PERSONS, [])]
    real_persons = {
        label("person", person): _async_person(hass, manager, person)
        for person in persons
    }

    diagnostics: dict[str, Any] = {
        "version": str(integration.version) if integration.version else None,
        "loaded": manager is not None,
        "bluetooth_loaded": ble.async_bluetooth_loaded(hass),
        "real_persons": real_persons,
    }
    if manager is not None:
        diagnostics["household"] = {
            "real_persons_home": manager.real_persons_home,
            "real_home": manager.real_home,
            "only_virtual_home": manager.only_virtual_home,
        }
    diagnostics["trackers"] = {
        label("tracker", subentry.subentry_id): _async_tracker(
            hass, manager, subentry, label
        )
        for subentry in entry.get_subentries_of_type(SUBENTRY_TYPE_TRACKER)
    }
    prefix = f"{entry.entry_id}_"
    diagnostics["repair_issues"] = sorted(
        issue.translation_key or ""
        for (domain, issue_id), issue in ir.async_get(hass).issues.items()
        # Only the active ones: the issues of a previous run that Home
        # Assistant restores at startup have no translation key.
        if domain == DOMAIN and issue.active and issue_id.startswith(prefix)
    )
    return diagnostics


@callback
def _async_person(
    hass: HomeAssistant, manager: HouseholdManager | None, person: str
) -> dict[str, Any]:
    """Return what is known about one real person: presence and phone count."""
    home = manager.person_home(person) if manager is not None else None
    return {
        "presence": "unknown" if home is None else "home" if home else "away",
        "exists": hass.states.get(person) is not None,
        "phones": len(async_notify_services(hass, person)),
    }


@callback
def _async_tracker(
    hass: HomeAssistant,
    manager: HouseholdManager | None,
    subentry: ConfigSubentry,
    label: _Labels,
) -> dict[str, Any]:
    """Return the settings, the sources and the state of one tracker."""
    subentry_id = subentry.subentry_id
    stored = subentry.data
    tracker: dict[str, Any] = {
        # Every option as it applies, and which of them are not stored and
        # therefore use the default - which is what tells an old tracker from
        # a new one.
        "options": {
            key: stored.get(key, default) for key, default in OPTION_DEFAULTS.items()
        },
        "options_defaulted": sorted(
            key for key in OPTION_DEFAULTS if key not in stored
        ),
        "recipients": [
            label("person", str(person).lower())
            for person in stored.get(CONF_NOTIFY_PERSONS, [])
        ],
        "create_person_pending": bool(stored.get(CONF_CREATE_PERSON)),
        "buttons": _async_buttons(hass, stored, label),
        "presence_sources": _async_presence_sources(hass, stored, label),
        "ble_sources": _async_ble_sources(hass, stored, label),
    }
    if manager is None:
        return tracker

    presence = manager.presence
    tracker["presence"] = {
        "known": presence.known_presence(subentry_id),
        "following_since": _iso(presence.following_since(subentry_id)),
        "absent_since": _iso(presence.absent_since(subentry_id)),
    }
    if (state := manager.tracker_state(subentry_id)) is not None:
        tracker["state"] = {
            "home": state.home,
            "since": _iso(state.since),
            "anchor": _iso(state.anchor),
            "left_behind_wait_since": _iso(state.wait_since),
            "source_lock": state.source_lock,
        }
    prompt = manager.prompt(subentry_id)
    tracker["prompt_scheduled"] = manager.prompt_scheduled(subentry_id)
    tracker["prompt"] = (
        {
            "id": prompt.prompt_id,
            "started_at": _iso(prompt.started_at),
            "expires_at": _iso(prompt.expires_at),
            "manual": prompt.manual,
        }
        if prompt is not None
        else None
    )
    reminder = manager.reminder(subentry_id)
    tracker["reminder"] = (
        {
            "id": reminder.reminder_id,
            "started_at": _iso(reminder.started_at),
            "expires_at": _iso(reminder.expires_at),
        }
        if reminder is not None
        else None
    )
    question = manager.left_behind_question(subentry_id)
    tracker["left_behind"] = (
        {
            "id": question.left_behind_id,
            "started_at": _iso(question.started_at),
            "expires_at": _iso(question.expires_at),
            "manual": question.manual,
            "sources": [_source_label(source, label) for source in question.sources],
        }
        if question is not None
        else None
    )
    return tracker


def _source_label(source: str, label: _Labels) -> str:
    """Return the label of a presence source: an address or an entity ID."""
    if (address := ble.normalize_address(source)) is not None:
        return label("ble", address)
    return label("source", source.lower())


@callback
def _async_entity_status(hass: HomeAssistant, entity_id: str) -> str | None:
    """Return the status every entity source shares, or None if it has a state.

    `missing` is what the repair issue reports; `no_state` is an entity that is
    registered but has no state, such as a disabled one or one whose
    integration is not loaded.
    """
    if async_entity_missing(hass, entity_id):
        return "missing"
    state = hass.states.get(entity_id)
    if state is None:
        return "no_state"
    if state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
        return state.state
    return None


@callback
def _async_buttons(
    hass: HomeAssistant, stored: Mapping[str, Any], label: _Labels
) -> dict[str, Any]:
    """Return the button sources of a tracker and the event types it uses."""
    own = async_own_event_entities(hass)
    sources: dict[str, dict[str, str]] = {}
    for raw in stored.get(CONF_BUTTON_SOURCES, []):
        entity_id = str(raw).lower()
        status = (
            "ignored_own"
            if entity_id in own
            else _async_entity_status(hass, entity_id) or "available"
        )
        sources[label("button", entity_id)] = {
            "domain": entity_id.partition(".")[0],
            "status": status,
        }
    return {
        "count": len(sources),
        "home_types": list(stored.get(CONF_BUTTON_HOME_TYPES, [])),
        "away_types": list(stored.get(CONF_BUTTON_AWAY_TYPES, [])),
        "sources": sources,
    }


@callback
def _async_presence_sources(
    hass: HomeAssistant, stored: Mapping[str, Any], label: _Labels
) -> dict[str, Any]:
    """Return the entity presence sources of a tracker and what each says."""
    own = async_own_presence_entities(hass)
    sources: dict[str, dict[str, str]] = {}
    for raw in stored.get(CONF_PRESENCE_SOURCES, []):
        entity_id = str(raw).lower()
        domain = entity_id.partition(".")[0]
        if entity_id in own:
            status = "ignored_own"
        elif (status_of := _async_entity_status(hass, entity_id)) is not None:
            status = status_of
        else:
            state = hass.states.get(entity_id)
            present = state is not None and state.state == _PRESENT_STATE.get(domain)
            status = "present" if present else "absent"
        sources[label("source", entity_id)] = {"domain": domain, "status": status}
    return {"count": len(sources), "sources": sources}


@callback
def _async_ble_sources(
    hass: HomeAssistant, stored: Mapping[str, Any], label: _Labels
) -> dict[str, Any]:
    """Return the Bluetooth sources of a tracker and when each was heard.

    Without Bluetooth nothing is known about them, which is what None says.
    """
    loaded = ble.async_bluetooth_loaded(hass)
    window = int(stored.get(CONF_AWAY_AFTER, OPTION_DEFAULTS[CONF_AWAY_AFTER])) * 60
    sources: dict[str, dict[str, Any]] = {}
    for raw in stored.get(CONF_BLE_SOURCES, []):
        address = ble.normalize_address(str(raw))
        if address is None:
            # Never followed: not a valid address. Still labelled, never shown.
            sources[label("ble", str(raw))] = {"valid": False}
            continue
        age = ble.async_seconds_since_heard(hass, address) if loaded else None
        sources[label("ble", address)] = {
            "valid": True,
            "seconds_since_heard": round(age) if age is not None else None,
            "heard_within_away_after": (age is not None and age < window)
            if loaded
            else None,
        }
    return {"count": len(sources), "sources": sources}
