"""Tests for the household manager."""

from __future__ import annotations

from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.virtual_presence_tracker.const import (
    CONF_PERSONS,
    CONF_RESET_ON_RETURN,
    DOMAIN,
    STORAGE_KEY_PREFIX,
    STORAGE_VERSION,
    SUBENTRY_TYPE_TRACKER,
)
from custom_components.virtual_presence_tracker.manager import HouseholdManager
from homeassistant.const import (
    STATE_HOME,
    STATE_NOT_HOME,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant

ENTRY_ID = "01JVPT0000000000000000ENTRY"
STORE_KEY = f"{STORAGE_KEY_PREFIX}.{ENTRY_ID}"

PERSON_A = "person.dabo53ck"
PERSON_B = "person.king53ck"

TRACKER_A = "01JVPT000000000000000TRACKA"
TRACKER_B = "01JVPT000000000000000TRACKB"
TRACKER_C = "01JVPT000000000000000TRACKC"


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
    *,
    persons: list[str] | None = None,
    subentries: list[dict[str, Any]] | None = None,
) -> MockConfigEntry:
    """Return a config entry with the given persons and trackers."""
    data: dict[str, Any] = {} if persons is None else {CONF_PERSONS: persons}
    return MockConfigEntry(
        domain=DOMAIN,
        title="Virtual Presence Tracker",
        entry_id=ENTRY_ID,
        data=data,
        subentries_data=subentries or [make_subentry(TRACKER_A, "Kid")],
    )


def stored(trackers: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Return a storage payload as it is written by the manager."""
    return {
        "version": STORAGE_VERSION,
        "minor_version": 1,
        "key": STORE_KEY,
        "data": {"trackers": trackers},
    }


async def start_manager(
    hass: HomeAssistant, entry: MockConfigEntry
) -> HouseholdManager:
    """Return a loaded and started manager for the entry."""
    entry.add_to_hass(hass)
    manager = HouseholdManager(hass, entry)
    await manager.async_load()
    manager.async_start()
    return manager


async def set_person(hass: HomeAssistant, entity_id: str, state: str) -> None:
    """Set a person state and let the manager process it."""
    hass.states.async_set(entity_id, state)
    await hass.async_block_till_done()


async def test_load_without_stored_data(hass: HomeAssistant) -> None:
    """Trackers without stored state start away."""
    manager = await start_manager(hass, make_entry())

    assert manager.tracker_ids == [TRACKER_A]
    assert manager.is_home(TRACKER_A) is False
    assert manager.since(TRACKER_A) is None
    # An unknown subentry never raises.
    assert manager.is_home("nope") is False
    assert manager.since("nope") is None


async def test_load_restores_state(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """Stored trackers are restored, unknown ones default to away."""
    hass_storage[STORE_KEY] = stored(
        {TRACKER_A: {"home": True, "since": "2026-09-19T08:00:00+00:00"}}
    )
    entry = make_entry(
        subentries=[
            make_subentry(TRACKER_A, "Kid"),
            make_subentry(TRACKER_B, "Granny"),
        ]
    )

    manager = await start_manager(hass, entry)

    assert manager.is_home(TRACKER_A) is True
    assert manager.since(TRACKER_A) is not None
    assert manager.since(TRACKER_A).isoformat() == "2026-09-19T08:00:00+00:00"
    assert manager.is_home(TRACKER_B) is False
    assert manager.since(TRACKER_B) is None


async def test_persistence_round_trip(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """A state set on one manager is restored by the next one."""
    entry = make_entry()
    manager = await start_manager(hass, entry)

    manager.async_set_home(TRACKER_A, True)
    since = manager.since(TRACKER_A)
    await manager.async_stop()

    assert hass_storage[STORE_KEY]["data"]["trackers"][TRACKER_A]["home"] is True

    restored = HouseholdManager(hass, entry)
    await restored.async_load()

    assert restored.is_home(TRACKER_A) is True
    assert restored.since(TRACKER_A) == since


async def test_load_prunes_removed_subentries(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """State of a subentry that is gone is dropped and not written back."""
    hass_storage[STORE_KEY] = stored(
        {
            TRACKER_A: {"home": True, "since": None},
            TRACKER_B: {"home": True, "since": None},
        }
    )

    manager = await start_manager(hass, make_entry())

    assert manager.tracker_ids == [TRACKER_A]
    assert manager.is_home(TRACKER_B) is False

    await manager.async_stop()

    assert set(hass_storage[STORE_KEY]["data"]["trackers"]) == {TRACKER_A}


async def test_listeners_fire_only_on_change(hass: HomeAssistant) -> None:
    """Listeners are called on a real change, not on a repeated value."""
    entry = make_entry(
        persons=[PERSON_A],
        subentries=[
            make_subentry(TRACKER_A, "Kid"),
            make_subentry(TRACKER_B, "Granny"),
        ],
    )
    manager = await start_manager(hass, entry)

    household: list[None] = []
    tracker_a: list[None] = []
    unsub_household = manager.async_add_listener(lambda: household.append(None))
    unsub_tracker_a = manager.async_add_listener(
        lambda: tracker_a.append(None), TRACKER_A
    )

    manager.async_set_home(TRACKER_A, True)
    assert len(household) == 1
    assert len(tracker_a) == 1

    manager.async_set_home(TRACKER_A, True)
    assert len(household) == 1
    assert len(tracker_a) == 1

    # Another tracker only notifies the household listeners.
    manager.async_set_home(TRACKER_B, True)
    assert len(household) == 2
    assert len(tracker_a) == 1

    # A real person changing affects "only virtual trackers home".
    await set_person(hass, PERSON_A, STATE_NOT_HOME)
    assert len(household) == 3
    assert len(tracker_a) == 1

    unsub_household()
    unsub_tracker_a()
    manager.async_set_home(TRACKER_A, False)
    assert len(household) == 3
    assert len(tracker_a) == 1


@pytest.mark.parametrize(
    ("tracker_home", "person_states", "expected"),
    [
        (False, {}, False),
        (True, {}, True),
        (True, {PERSON_A: STATE_NOT_HOME}, True),
        (True, {PERSON_A: STATE_UNKNOWN}, True),
        (True, {PERSON_A: STATE_HOME}, False),
        (True, {PERSON_A: STATE_HOME, PERSON_B: STATE_NOT_HOME}, False),
        (False, {PERSON_A: STATE_NOT_HOME}, False),
        (True, {PERSON_A: "zone.office"}, True),
    ],
)
async def test_only_virtual_home(
    hass: HomeAssistant,
    tracker_home: bool,
    person_states: dict[str, str],
    expected: bool,
) -> None:
    """Only virtual home means a tracker is home and no real person is."""
    for entity_id, state in person_states.items():
        hass.states.async_set(entity_id, state)

    manager = await start_manager(hass, make_entry(persons=[PERSON_A, PERSON_B]))
    manager.async_set_home(TRACKER_A, tracker_home)

    assert manager.only_virtual_home is expected


async def test_real_home_is_none_until_a_state_is_known(hass: HomeAssistant) -> None:
    """Without any known person state the real presence is unknown."""
    manager = await start_manager(hass, make_entry(persons=[PERSON_A]))

    assert manager.real_home is None
    assert manager.real_persons_home == 0

    await set_person(hass, PERSON_A, STATE_NOT_HOME)

    assert manager.real_home is False


async def test_reset_when_the_house_stops_being_empty(hass: HomeAssistant) -> None:
    """(a) The first real person coming home resets the tracker."""
    hass.states.async_set(PERSON_A, STATE_NOT_HOME)
    hass.states.async_set(PERSON_B, STATE_NOT_HOME)
    manager = await start_manager(hass, make_entry(persons=[PERSON_A, PERSON_B]))
    manager.async_set_home(TRACKER_A, True)

    await set_person(hass, PERSON_A, STATE_HOME)

    assert manager.is_home(TRACKER_A) is False


async def test_no_reset_on_a_second_arrival(hass: HomeAssistant) -> None:
    """(b) Going from one to two real persons at home does not reset."""
    hass.states.async_set(PERSON_A, STATE_HOME)
    hass.states.async_set(PERSON_B, STATE_NOT_HOME)
    manager = await start_manager(hass, make_entry(persons=[PERSON_A, PERSON_B]))
    manager.async_set_home(TRACKER_A, True)

    await set_person(hass, PERSON_B, STATE_HOME)

    assert manager.is_home(TRACKER_A) is True


async def test_no_reset_on_leaving(hass: HomeAssistant) -> None:
    """(c) Real persons leaving never resets a tracker."""
    hass.states.async_set(PERSON_A, STATE_HOME)
    hass.states.async_set(PERSON_B, STATE_HOME)
    manager = await start_manager(hass, make_entry(persons=[PERSON_A, PERSON_B]))
    manager.async_set_home(TRACKER_A, True)

    await set_person(hass, PERSON_A, STATE_NOT_HOME)
    await set_person(hass, PERSON_B, STATE_NOT_HOME)

    assert manager.is_home(TRACKER_A) is True
    assert manager.only_virtual_home is True


async def test_reset_respects_the_per_tracker_option(hass: HomeAssistant) -> None:
    """(d), (g) Trackers with different options are treated individually."""
    hass.states.async_set(PERSON_A, STATE_NOT_HOME)
    entry = make_entry(
        persons=[PERSON_A],
        subentries=[
            make_subentry(TRACKER_A, "Kid", **{CONF_RESET_ON_RETURN: True}),
            make_subentry(TRACKER_B, "Guest", **{CONF_RESET_ON_RETURN: False}),
            make_subentry(TRACKER_C, "Granny"),
        ],
    )
    manager = await start_manager(hass, entry)
    manager.async_set_home(TRACKER_A, True)
    manager.async_set_home(TRACKER_B, True)

    await set_person(hass, PERSON_A, STATE_HOME)

    assert manager.is_home(TRACKER_A) is False
    assert manager.is_home(TRACKER_B) is True
    # A tracker that is away is not touched (the default would reset it).
    assert manager.is_home(TRACKER_C) is False


async def test_no_reset_on_the_first_known_person_state(hass: HomeAssistant) -> None:
    """(e) A person becoming known at startup never resets."""
    hass.states.async_set(PERSON_A, STATE_UNKNOWN)
    manager = await start_manager(hass, make_entry(persons=[PERSON_A, PERSON_B]))
    manager.async_set_home(TRACKER_A, True)

    # Recovering from unknown ...
    await set_person(hass, PERSON_A, STATE_HOME)
    assert manager.is_home(TRACKER_A) is True

    # ... and a person entity that did not exist at all before.
    await set_person(hass, PERSON_B, STATE_HOME)
    assert manager.is_home(TRACKER_A) is True


async def test_tracker_stays_home_while_persons_are_home(hass: HomeAssistant) -> None:
    """(f) A tracker switched on while somebody is home stays on."""
    hass.states.async_set(PERSON_A, STATE_HOME)
    manager = await start_manager(hass, make_entry(persons=[PERSON_A]))
    manager.async_set_home(TRACKER_A, True)

    hass.states.async_set(PERSON_A, STATE_HOME, {"source": "device_tracker.phone"})
    await hass.async_block_till_done()

    assert manager.is_home(TRACKER_A) is True
    assert manager.only_virtual_home is False


async def test_no_reset_when_a_person_becomes_unavailable(hass: HomeAssistant) -> None:
    """(h) An unavailable person keeps their last known state."""
    hass.states.async_set(PERSON_A, STATE_HOME)
    manager = await start_manager(hass, make_entry(persons=[PERSON_A]))
    manager.async_set_home(TRACKER_A, True)

    await set_person(hass, PERSON_A, STATE_UNAVAILABLE)
    assert manager.real_home is True

    await set_person(hass, PERSON_A, STATE_HOME)

    assert manager.is_home(TRACKER_A) is True


async def test_reset_after_an_arrival_through_unavailable(hass: HomeAssistant) -> None:
    """An away person arriving via unavailable still resets.

    The last known state, not the last state, decides: the person really was
    away and really came home, so an unavailable blip must not swallow the
    reset.
    """
    hass.states.async_set(PERSON_A, STATE_NOT_HOME)
    manager = await start_manager(hass, make_entry(persons=[PERSON_A]))
    manager.async_set_home(TRACKER_A, True)

    await set_person(hass, PERSON_A, STATE_UNAVAILABLE)
    await set_person(hass, PERSON_A, STATE_HOME)

    assert manager.is_home(TRACKER_A) is False


async def test_without_configured_persons(hass: HomeAssistant) -> None:
    """The manager tolerates an entry without persons.

    The config flow requires at least one real person, so such an entry cannot
    be created any more; the manager must not depend on that.
    """
    manager = await start_manager(hass, make_entry())

    assert manager.real_home is None
    manager.async_set_home(TRACKER_A, True)
    assert manager.only_virtual_home is True

    # A person state change is simply not watched.
    await set_person(hass, PERSON_A, STATE_HOME)
    assert manager.is_home(TRACKER_A) is True

    await manager.async_stop()
