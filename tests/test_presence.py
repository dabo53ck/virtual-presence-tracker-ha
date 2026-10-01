"""Tests for the presence sources of a tracker (M3e).

A tracker may follow device trackers, binary sensors and Bluetooth devices by
address. It counts as present while any of them is, and only edges switch it:
becoming present switches it on, having been absent for `away_after` switches
it off. Unknown is never absent, the first known value is a baseline, and
changing the sources or `away_after` never reloads the entry.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)
import voluptuous as vol

from custom_components.virtual_presence_tracker.const import (
    ATTR_REASON,
    ATTR_USER_ID,
    BLUETOOTH_DOMAIN,
    CONF_ASK_ON_DEPARTURE,
    CONF_AWAY_AFTER,
    CONF_BLE_SOURCES,
    CONF_CREATE_PERSON,
    CONF_DEVICE_NAME,
    CONF_NOTIFY_PERSONS,
    CONF_PRESENCE_SOURCES,
    CONF_PROMPT_DELAY,
    CONF_RESET_ON_RETURN,
    CONF_USER_ID,
    EVENT_CANCELLED,
    EVENT_REMINDER_CANCELLED,
    MOBILE_APP_DOMAIN,
    NOTIFY_DOMAIN,
    REASON_SWITCHED_OFF,
    REASON_SWITCHED_ON,
    STORAGE_KEY_PREFIX,
    STORAGE_VERSION,
    SUBENTRY_TYPE_TRACKER,
)
from custom_components.virtual_presence_tracker.manager import OpenPromptResult
from homeassistant.components.event import ATTR_EVENT_TYPE
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import (
    CONF_NAME,
    EVENT_STATE_CHANGED,
    STATE_HOME,
    STATE_NOT_HOME,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import Event, HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.helpers import device_registry as dr

from .conftest import (
    ENTRY_ID,
    PERSON_A,
    TRACKER_A,
    TRACKER_B,
    make_entry,
    make_subentry,
)

TAG = "device_tracker.kid_tag"
WIFI = "binary_sensor.kid_tablet_wifi"

SWITCH_A = "switch.kid_at_home"
SWITCH_B = "switch.granny_at_home"
TRACKER_A_ENTITY = "device_tracker.kid"
TRACKER_B_ENTITY = "device_tracker.granny"
EVENT_A = "event.kid_questions"
SENSOR = "binary_sensor.only_virtual_trackers_home"
AWAY_A = "number.kid_away_after"

ADDRESS = "7C:C6:B6:00:5D:C6"
OTHER_ADDRESS = "A4:C1:38:00:00:01"
THIRD_ADDRESS = "D8:0B:CB:00:00:02"

USER_A = "user-dabo53ck"
PHONE_A = "mobile_app_dabo53ck_s_phone"

MINUTE = 60
STORE_KEY = f"{STORAGE_KEY_PREFIX}.{ENTRY_ID}"


def presence_entry(sources: list[str] | None = None, **data: Any) -> MockConfigEntry:
    """Return an entry whose first tracker follows the given entity sources."""
    return make_entry(
        make_subentry(
            TRACKER_A,
            "Kid",
            **{
                CONF_PRESENCE_SOURCES: sources if sources is not None else [TAG],
                **data,
            },
        ),
        make_subentry(TRACKER_B, "Granny"),
    )


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> MockConfigEntry:
    """Add a config entry to hass and set it up."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def unload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Unload an entry, so that no timer is left running."""
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def set_state(hass: HomeAssistant, entity_id: str, state: str) -> None:
    """Write the state of a source and let everything follow."""
    hass.states.async_set(entity_id, state)
    await hass.async_block_till_done()


async def tick(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: float
) -> None:
    """Let time pass and fire whatever timer is due."""
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def switch_on(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Switch the first tracker on by hand."""
    entry.runtime_data.manager.async_set_home(TRACKER_A, True)
    await hass.async_block_till_done()


def stored_home() -> dict[str, Any]:
    """Return a store in which the first tracker was left switched on."""
    return {
        "version": STORAGE_VERSION,
        "minor_version": 1,
        "key": STORE_KEY,
        "data": {
            "trackers": {
                TRACKER_A: {"home": True, "since": "2026-10-01T06:00:00+00:00"}
            }
        },
    }


class Watcher:
    """Record the state changes of the given entities."""

    def __init__(self, hass: HomeAssistant, *entity_ids: str) -> None:
        """Listen for the state changes of the given entities."""
        self.changes: list[str] = []
        self._entity_ids = entity_ids
        hass.bus.async_listen(EVENT_STATE_CHANGED, self._record)

    def _record(self, event: Event[Any]) -> None:
        """Remember one state change."""
        if event.data["entity_id"] in self._entity_ids:
            self.changes.append(event.data["entity_id"])


# --- Entity sources: the edges -----------------------------------------------


async def test_becoming_present_switches_the_tracker_on(hass: HomeAssistant) -> None:
    """Absent -> present is an edge: on, and an open prompt is withdrawn."""
    hass.states.async_set(TAG, STATE_NOT_HOME)
    entry = await setup_entry(hass, presence_entry())
    manager = entry.runtime_data.manager
    assert manager.async_open_prompt(TRACKER_A) is OpenPromptResult.OPENED
    await hass.async_block_till_done()

    await set_state(hass, TAG, STATE_HOME)

    assert hass.states.get(SWITCH_A).state == STATE_ON
    assert hass.states.get(TRACKER_A_ENTITY).state == STATE_HOME
    # The other tracker does not follow this source.
    assert hass.states.get(SWITCH_B).state == STATE_OFF
    state = hass.states.get(EVENT_A)
    assert state.attributes[ATTR_EVENT_TYPE] == EVENT_CANCELLED
    assert state.attributes[ATTR_REASON] == REASON_SWITCHED_ON

    await unload(hass, entry)


async def test_a_binary_sensor_is_present_while_on(hass: HomeAssistant) -> None:
    """`on` is present and `off` is absent for a binary sensor."""
    hass.states.async_set(WIFI, STATE_OFF)
    entry = await setup_entry(hass, presence_entry([WIFI]))

    await set_state(hass, WIFI, STATE_ON)

    assert entry.runtime_data.manager.is_home(TRACKER_A) is True

    await unload(hass, entry)


async def test_absent_switches_off_only_after_away_after(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Off after `away_after`, not before - and an open reminder goes with it."""
    hass.states.async_set(TAG, STATE_HOME)
    entry = await setup_entry(hass, presence_entry(**{CONF_AWAY_AFTER: 10}))
    manager = entry.runtime_data.manager
    await switch_on(hass, entry)
    manager.async_open_reminder(TRACKER_A)
    await hass.async_block_till_done()

    # A zone other than home is away as well.
    await set_state(hass, TAG, "school")
    await tick(hass, freezer, 10 * MINUTE - 1)
    assert manager.is_home(TRACKER_A) is True
    assert manager.reminder_open(TRACKER_A) is True

    await tick(hass, freezer, 1)

    assert manager.is_home(TRACKER_A) is False
    assert hass.states.get(TRACKER_A_ENTITY).state == STATE_NOT_HOME
    state = hass.states.get(EVENT_A)
    assert state.attributes[ATTR_EVENT_TYPE] == EVENT_REMINDER_CANCELLED
    assert state.attributes[ATTR_REASON] == REASON_SWITCHED_OFF

    await unload(hass, entry)


async def test_the_default_away_after_is_ten_minutes(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A tracker without the key waits ten minutes."""
    hass.states.async_set(TAG, STATE_HOME)
    entry = await setup_entry(hass, presence_entry())
    manager = entry.runtime_data.manager
    await switch_on(hass, entry)

    await set_state(hass, TAG, STATE_NOT_HOME)
    await tick(hass, freezer, 10 * MINUTE - 1)
    assert manager.is_home(TRACKER_A) is True
    await tick(hass, freezer, 1)
    assert manager.is_home(TRACKER_A) is False

    await unload(hass, entry)


async def test_coming_back_before_away_after_cancels_the_switch_off(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Present again in time: nothing happens at all."""
    hass.states.async_set(TAG, STATE_HOME)
    entry = await setup_entry(hass, presence_entry())
    manager = entry.runtime_data.manager
    await switch_on(hass, entry)
    since = manager.since(TRACKER_A)

    await set_state(hass, TAG, STATE_NOT_HOME)
    await tick(hass, freezer, 5 * MINUTE)
    await set_state(hass, TAG, STATE_HOME)
    await tick(hass, freezer, 30 * MINUTE)

    assert manager.is_home(TRACKER_A) is True
    assert manager.since(TRACKER_A) == since

    await unload(hass, entry)


async def test_any_present_source_keeps_the_tracker_present(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Away counts from the moment the *last* source went away."""
    hass.states.async_set(TAG, STATE_HOME)
    hass.states.async_set(WIFI, STATE_ON)
    entry = await setup_entry(hass, presence_entry([TAG, WIFI]))
    manager = entry.runtime_data.manager
    await switch_on(hass, entry)

    await set_state(hass, TAG, STATE_NOT_HOME)
    await tick(hass, freezer, 30 * MINUTE)
    assert manager.is_home(TRACKER_A) is True

    await set_state(hass, WIFI, STATE_OFF)
    await tick(hass, freezer, 10 * MINUTE - 1)
    assert manager.is_home(TRACKER_A) is True
    await tick(hass, freezer, 1)
    assert manager.is_home(TRACKER_A) is False

    # One of them coming back is enough to switch on again.
    await set_state(hass, WIFI, STATE_ON)
    assert manager.is_home(TRACKER_A) is True

    await unload(hass, entry)


@pytest.mark.parametrize("state", [STATE_UNAVAILABLE, STATE_UNKNOWN, None])
async def test_a_source_that_is_not_known_is_not_absent(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, state: str | None
) -> None:
    """Unavailable, unknown or gone keeps what was known last."""
    hass.states.async_set(TAG, STATE_HOME)
    entry = await setup_entry(hass, presence_entry())
    manager = entry.runtime_data.manager
    await switch_on(hass, entry)

    if state is None:
        hass.states.async_remove(TAG)
    else:
        hass.states.async_set(TAG, state)
    await hass.async_block_till_done()
    await tick(hass, freezer, 60 * MINUTE)

    assert manager.is_home(TRACKER_A) is True

    # Coming back as present after that is no edge: it was present before.
    since = manager.since(TRACKER_A)
    await set_state(hass, TAG, STATE_HOME)
    assert manager.since(TRACKER_A) == since

    await unload(hass, entry)


async def test_an_absence_keeps_running_while_the_source_is_unknown(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Absent, then unavailable: the last known value is still absent."""
    hass.states.async_set(TAG, STATE_HOME)
    entry = await setup_entry(hass, presence_entry())
    manager = entry.runtime_data.manager
    await switch_on(hass, entry)

    await set_state(hass, TAG, STATE_NOT_HOME)
    await tick(hass, freezer, 5 * MINUTE)
    await set_state(hass, TAG, STATE_UNAVAILABLE)
    await tick(hass, freezer, 5 * MINUTE)

    assert manager.is_home(TRACKER_A) is False

    await unload(hass, entry)


async def test_sources_that_are_all_unknown_do_nothing(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_storage: dict[str, Any]
) -> None:
    """Without a single known source, nothing is switched in either direction."""
    hass_storage[STORE_KEY] = stored_home()
    hass.states.async_set(WIFI, STATE_UNAVAILABLE)
    entry = await setup_entry(hass, presence_entry([TAG, WIFI]))
    manager = entry.runtime_data.manager

    await tick(hass, freezer, 60 * MINUTE)

    assert manager.is_home(TRACKER_A) is True

    await unload(hass, entry)


async def test_a_manual_change_sticks_until_the_next_edge(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Sources never overrule the switch continuously."""
    hass.states.async_set(TAG, STATE_HOME)
    entry = await setup_entry(hass, presence_entry())
    manager = entry.runtime_data.manager
    await switch_on(hass, entry)

    # Switched off by hand while the source is present: it stays off, also
    # through updates of the source that change nothing.
    manager.async_set_home(TRACKER_A, False)
    hass.states.async_set(TAG, STATE_HOME, {"battery": 80})
    await hass.async_block_till_done()
    await tick(hass, freezer, 60 * MINUTE)
    assert manager.is_home(TRACKER_A) is False

    # The next edge switches again.
    await set_state(hass, TAG, STATE_NOT_HOME)
    await set_state(hass, TAG, STATE_HOME)
    assert manager.is_home(TRACKER_A) is True

    # Switched off by the absence, then on by hand: that sticks as well.
    await set_state(hass, TAG, STATE_NOT_HOME)
    await tick(hass, freezer, 10 * MINUTE)
    assert manager.is_home(TRACKER_A) is False
    manager.async_set_home(TRACKER_A, True)
    await tick(hass, freezer, 120 * MINUTE)
    assert manager.is_home(TRACKER_A) is True

    await unload(hass, entry)


# --- Entity sources: the start -------------------------------------------------


async def test_present_at_the_start_switches_nothing_on(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The first value is a baseline, not an edge."""
    hass.states.async_set(TAG, STATE_HOME)
    entry = await setup_entry(hass, presence_entry())

    await tick(hass, freezer, 60 * MINUTE)

    assert entry.runtime_data.manager.is_home(TRACKER_A) is False

    await unload(hass, entry)


async def test_a_source_that_appears_after_the_start_is_a_baseline(
    hass: HomeAssistant,
) -> None:
    """A source whose integration loads later is not an arrival either."""
    entry = await setup_entry(hass, presence_entry())

    await set_state(hass, TAG, STATE_HOME)

    assert entry.runtime_data.manager.is_home(TRACKER_A) is False

    await unload(hass, entry)


async def test_absent_at_the_start_counts_from_the_start(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_storage: dict[str, Any]
) -> None:
    """A tracker that is on goes off `away_after` after the start, never earlier.

    The source has been away for an hour already, but nothing of that is
    counted: the clock starts when the entry does.
    """
    hass_storage[STORE_KEY] = stored_home()
    hass.states.async_set(TAG, STATE_NOT_HOME)
    await tick(hass, freezer, 60 * MINUTE)
    entry = await setup_entry(hass, presence_entry())
    manager = entry.runtime_data.manager
    assert manager.is_home(TRACKER_A) is True

    await tick(hass, freezer, 10 * MINUTE - 1)
    assert manager.is_home(TRACKER_A) is True
    await tick(hass, freezer, 1)
    assert manager.is_home(TRACKER_A) is False

    await unload(hass, entry)


# --- Departure and reset -------------------------------------------------------


def add_phone(hass: HomeAssistant) -> list[Any]:
    """Register a Companion App phone for the real person and mock its service."""
    MockConfigEntry(
        domain=MOBILE_APP_DOMAIN,
        title="dabo53ck's Phone",
        data={CONF_DEVICE_NAME: "dabo53ck's Phone", CONF_USER_ID: USER_A},
    ).add_to_hass(hass)
    return async_mock_service(hass, NOTIFY_DOMAIN, PHONE_A)


async def set_person(hass: HomeAssistant, state: str) -> None:
    """Move the one real person of the household."""
    hass.states.async_set(PERSON_A, state, {ATTR_USER_ID: USER_A})
    await hass.async_block_till_done(wait_background_tasks=True)


@pytest.mark.parametrize("delay", [0, 30])
async def test_departure_with_a_present_source_switches_on_instead_of_asking(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, delay: int
) -> None:
    """No prompt and no message: the source already answered the question."""
    calls = add_phone(hass)
    await set_person(hass, STATE_HOME)
    hass.states.async_set(TAG, STATE_HOME)
    entry = await setup_entry(
        hass,
        presence_entry(
            **{
                CONF_ASK_ON_DEPARTURE: True,
                CONF_NOTIFY_PERSONS: [PERSON_A],
                CONF_PROMPT_DELAY: delay,
            }
        ),
    )
    manager = entry.runtime_data.manager

    await set_person(hass, STATE_NOT_HOME)
    if delay:
        assert manager.is_home(TRACKER_A) is False
        await tick(hass, freezer, delay)
        await hass.async_block_till_done(wait_background_tasks=True)

    assert manager.is_home(TRACKER_A) is True
    assert manager.prompt_open(TRACKER_A) is False
    assert calls == []
    # No prompt was ever announced, so there is nothing to withdraw either.
    assert hass.states.get(EVENT_A).attributes.get(ATTR_EVENT_TYPE) is None
    assert hass.states.get(SENSOR).state == STATE_ON

    await unload(hass, entry)


@pytest.mark.parametrize("delay", [0, 30])
async def test_departure_switches_on_without_asking_when_asking_is_off(
    hass: HomeAssistant, delay: int
) -> None:
    """With "Ask when empty" off, a present source still switches on - at once.

    There is no prompt whose delay it could wait for, so `prompt_delay` does
    not apply; nothing is sent either.
    """
    calls = add_phone(hass)
    await set_person(hass, STATE_HOME)
    hass.states.async_set(TAG, STATE_HOME)
    entry = await setup_entry(
        hass,
        presence_entry(
            **{
                CONF_ASK_ON_DEPARTURE: False,
                CONF_NOTIFY_PERSONS: [PERSON_A],
                CONF_PROMPT_DELAY: delay,
            }
        ),
    )
    manager = entry.runtime_data.manager

    await set_person(hass, STATE_NOT_HOME)

    assert manager.is_home(TRACKER_A) is True
    assert manager.prompt_open(TRACKER_A) is False
    assert calls == []
    # A tracker without sources and without asking is left alone, as ever.
    assert manager.is_home(TRACKER_B) is False

    await unload(hass, entry)


@pytest.mark.parametrize("state", [STATE_NOT_HOME, STATE_UNAVAILABLE, None])
async def test_departure_without_asking_needs_a_present_source(
    hass: HomeAssistant, state: str | None
) -> None:
    """Absent or not known: with asking off, nothing happens at all."""
    calls = add_phone(hass)
    await set_person(hass, STATE_HOME)
    if state is not None:
        hass.states.async_set(TAG, state)
    entry = await setup_entry(
        hass,
        presence_entry(
            **{CONF_ASK_ON_DEPARTURE: False, CONF_NOTIFY_PERSONS: [PERSON_A]}
        ),
    )
    manager = entry.runtime_data.manager

    await set_person(hass, STATE_NOT_HOME)

    assert manager.is_home(TRACKER_A) is False
    assert manager.prompt_open(TRACKER_A) is False
    assert calls == []

    await unload(hass, entry)


async def test_departure_without_asking_switches_on_with_bluetooth(
    hass: HomeAssistant, bluetooth: FakeBluetooth
) -> None:
    """A Bluetooth source heard just now counts at the departure itself."""
    await set_person(hass, STATE_HOME)
    bluetooth.advertise(ADDRESS)
    entry = await setup_entry(hass, ble_entry(**{CONF_ASK_ON_DEPARTURE: False}))

    await set_person(hass, STATE_NOT_HOME)

    assert entry.runtime_data.manager.is_home(TRACKER_A) is True

    await unload(hass, entry)


async def test_departure_with_an_absent_source_asks_as_usual(
    hass: HomeAssistant,
) -> None:
    """A source that says "away" changes nothing about the prompt."""
    calls = add_phone(hass)
    await set_person(hass, STATE_HOME)
    hass.states.async_set(TAG, STATE_NOT_HOME)
    entry = await setup_entry(
        hass,
        presence_entry(
            **{CONF_ASK_ON_DEPARTURE: True, CONF_NOTIFY_PERSONS: [PERSON_A]}
        ),
    )
    manager = entry.runtime_data.manager

    await set_person(hass, STATE_NOT_HOME)

    assert manager.is_home(TRACKER_A) is False
    assert manager.prompt_open(TRACKER_A) is True
    assert len(calls) == 1

    await unload(hass, entry)


async def test_open_prompt_by_hand_ignores_the_sources(hass: HomeAssistant) -> None:
    """The manual action is untouched: it opens even with a present source."""
    hass.states.async_set(TAG, STATE_HOME)
    entry = await setup_entry(hass, presence_entry())
    manager = entry.runtime_data.manager

    assert manager.async_open_prompt(TRACKER_A) is OpenPromptResult.OPENED

    assert manager.prompt_open(TRACKER_A) is True
    assert manager.is_home(TRACKER_A) is False

    await unload(hass, entry)


async def test_reset_on_return_skips_a_tracker_with_sources(
    hass: HomeAssistant,
) -> None:
    """The source knows better than "somebody else came home"."""
    await set_person(hass, STATE_NOT_HOME)
    hass.states.async_set(TAG, STATE_HOME)
    entry = await setup_entry(
        hass,
        make_entry(
            make_subentry(
                TRACKER_A,
                "Kid",
                **{CONF_PRESENCE_SOURCES: [TAG], CONF_RESET_ON_RETURN: True},
            ),
            make_subentry(TRACKER_B, "Granny", **{CONF_RESET_ON_RETURN: True}),
        ),
    )
    manager = entry.runtime_data.manager
    manager.async_set_home(TRACKER_A, True)
    manager.async_set_home(TRACKER_B, True)

    await set_person(hass, STATE_HOME)

    assert manager.is_home(TRACKER_A) is True
    # A tracker without sources resets as it always did.
    assert manager.is_home(TRACKER_B) is False

    await unload(hass, entry)


# --- The integration's own entities --------------------------------------------


async def test_an_own_entity_is_ignored_as_a_source(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A tracker never follows another virtual tracker or the household sensor."""
    entry = await setup_entry(
        hass,
        make_entry(
            make_subentry(
                TRACKER_A,
                "Kid",
                **{CONF_PRESENCE_SOURCES: [TRACKER_B_ENTITY, SENSOR]},
            ),
            make_subentry(TRACKER_B, "Granny"),
        ),
    )
    manager = entry.runtime_data.manager

    manager.async_set_home(TRACKER_B, True)
    await hass.async_block_till_done()
    manager.async_set_home(TRACKER_B, False)
    await hass.async_block_till_done()
    manager.async_set_home(TRACKER_B, True)
    await hass.async_block_till_done()

    assert manager.is_home(TRACKER_A) is False

    # Nor is it switched off: it has no source that counts.
    manager.async_set_home(TRACKER_A, True)
    await tick(hass, freezer, 60 * MINUTE)
    assert manager.is_home(TRACKER_A) is True

    await unload(hass, entry)


# --- Changing the sources and away_after -----------------------------------------


async def test_changing_the_sources_does_not_reload_the_entry(
    hass: HomeAssistant,
) -> None:
    """New sources apply at once, without a flicker, from a fresh baseline."""
    hass.states.async_set(TAG, STATE_NOT_HOME)
    hass.states.async_set(WIFI, STATE_OFF)
    entry = await setup_entry(hass, make_entry(make_subentry(TRACKER_A, "Kid")))
    manager = entry.runtime_data.manager
    subentry = entry.subentries[TRACKER_A]

    watcher = Watcher(hass, TRACKER_A_ENTITY, SWITCH_A)
    hass.config_entries.async_update_subentry(
        entry, subentry, data={**subentry.data, CONF_PRESENCE_SOURCES: [TAG]}
    )
    await hass.async_block_till_done()

    assert entry.runtime_data.manager is manager
    assert watcher.changes == []

    await set_state(hass, TAG, STATE_HOME)
    assert manager.is_home(TRACKER_A) is True

    # Swapped for another source: the old one switches nothing any more.
    subentry = entry.subentries[TRACKER_A]
    hass.config_entries.async_update_subentry(
        entry, subentry, data={**subentry.data, CONF_PRESENCE_SOURCES: [WIFI]}
    )
    await hass.async_block_till_done()
    manager.async_set_home(TRACKER_A, False)
    await set_state(hass, TAG, STATE_NOT_HOME)
    await set_state(hass, TAG, STATE_HOME)
    assert manager.is_home(TRACKER_A) is False

    await set_state(hass, WIFI, STATE_ON)
    assert manager.is_home(TRACKER_A) is True
    assert entry.runtime_data.manager is manager

    await unload(hass, entry)


async def test_removing_the_sources_drops_a_pending_switch_off(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Without sources the tracker is the user's alone again."""
    hass.states.async_set(TAG, STATE_HOME)
    entry = await setup_entry(hass, presence_entry())
    manager = entry.runtime_data.manager
    await switch_on(hass, entry)
    await set_state(hass, TAG, STATE_NOT_HOME)

    subentry = entry.subentries[TRACKER_A]
    hass.config_entries.async_update_subentry(
        entry,
        subentry,
        data={
            key: value
            for key, value in subentry.data.items()
            if key != CONF_PRESENCE_SOURCES
        },
    )
    await hass.async_block_till_done()
    await tick(hass, freezer, 60 * MINUTE)

    assert manager.is_home(TRACKER_A) is True
    assert entry.runtime_data.manager is manager

    await unload(hass, entry)


async def test_a_longer_away_after_moves_a_pending_switch_off(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The number writes without a reload, and the timer follows it."""
    hass.states.async_set(TAG, STATE_HOME)
    entry = await setup_entry(hass, presence_entry())
    manager = entry.runtime_data.manager
    await switch_on(hass, entry)
    await set_state(hass, TAG, STATE_NOT_HOME)

    watcher = Watcher(hass, TRACKER_A_ENTITY, SWITCH_A)
    await hass.services.async_call(
        "number", "set_value", {"entity_id": AWAY_A, "value": 30}, blocking=True
    )
    await hass.async_block_till_done()
    assert watcher.changes == []
    assert entry.runtime_data.manager is manager
    assert entry.subentries[TRACKER_A].data[CONF_AWAY_AFTER] == 30

    await tick(hass, freezer, 29 * MINUTE)
    assert manager.is_home(TRACKER_A) is True
    await tick(hass, freezer, 1 * MINUTE)
    assert manager.is_home(TRACKER_A) is False

    await unload(hass, entry)


async def test_a_shorter_away_after_can_switch_off_at_once(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Lowered below the time already away: off on the spot."""
    hass.states.async_set(TAG, STATE_HOME)
    entry = await setup_entry(hass, presence_entry(**{CONF_AWAY_AFTER: 30}))
    manager = entry.runtime_data.manager
    await switch_on(hass, entry)
    await set_state(hass, TAG, STATE_NOT_HOME)
    await tick(hass, freezer, 5 * MINUTE)

    await hass.services.async_call(
        "number", "set_value", {"entity_id": AWAY_A, "value": 2}, blocking=True
    )
    await hass.async_block_till_done()

    assert manager.is_home(TRACKER_A) is False

    await unload(hass, entry)


async def test_unloading_stops_following_the_sources(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """No listener and no timer survive the entry."""
    hass.states.async_set(TAG, STATE_HOME)
    entry = await setup_entry(hass, presence_entry())
    manager = entry.runtime_data.manager
    await switch_on(hass, entry)
    await set_state(hass, TAG, STATE_NOT_HOME)

    await unload(hass, entry)
    await tick(hass, freezer, 60 * MINUTE)
    await set_state(hass, TAG, STATE_HOME)

    assert manager.is_home(TRACKER_A) is True


# --- Bluetooth sources -------------------------------------------------------------


@dataclass
class _ServiceInfo:
    """What the Bluetooth manager hands out about one device."""

    address: str
    name: str
    rssi: int
    time: float
    service_data: dict[str, bytes]


class FakeBluetooth:
    """The three calls of Home Assistant's Bluetooth API the integration uses."""

    def __init__(self) -> None:
        """Start with an empty history at an arbitrary monotonic time."""
        self.clock = 5000.0
        self.history: dict[str, _ServiceInfo] = {}

    def MONOTONIC_TIME(self) -> float:
        """Return the manager's clock."""
        return self.clock

    def advertise(self, address: str, name: str | None = None, rssi: int = -70) -> None:
        """Receive one advertisement - always the same payload."""
        self.history[address] = _ServiceInfo(
            address=address,
            name=name or address,
            rssi=rssi,
            time=self.clock,
            service_data={"0000fcd2-0000-1000-8000-00805f9b34fb": b"\x44\x00\x01"},
        )

    def async_last_service_info(
        self, hass: HomeAssistant, address: str, connectable: bool = True
    ) -> _ServiceInfo | None:
        """Return the last advertisement of an address, from any scanner."""
        assert connectable is False
        return self.history.get(address)

    def async_discovered_service_info(
        self, hass: HomeAssistant, connectable: bool = True
    ) -> list[_ServiceInfo]:
        """Return every device that has advertised."""
        assert connectable is False
        return list(self.history.values())


@pytest.fixture
def bluetooth(hass: HomeAssistant) -> Iterator[FakeBluetooth]:
    """Pretend that Bluetooth is set up, with a fake manager behind it."""
    fake = FakeBluetooth()
    hass.config.components.add(BLUETOOTH_DOMAIN)
    with patch(
        "custom_components.virtual_presence_tracker.ble._bluetooth",
        return_value=fake,
    ):
        yield fake


async def listen(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    fake: FakeBluetooth,
    seconds: int,
    *,
    advertise: str | None = None,
) -> None:
    """Let time pass in steps of the poll, advertising every step if asked to."""
    for _ in range(seconds // 30):
        fake.clock += 30
        if advertise is not None:
            fake.advertise(advertise)
        await tick(hass, freezer, 30)


def ble_entry(addresses: list[str] | None = None, **data: Any) -> MockConfigEntry:
    """Return an entry whose first tracker listens for Bluetooth devices."""
    return make_entry(
        make_subentry(
            TRACKER_A,
            "Kid",
            **{CONF_BLE_SOURCES: addresses or [ADDRESS], **data},
        ),
        make_subentry(TRACKER_B, "Granny"),
    )


async def test_a_bluetooth_device_switches_off_and_on_again(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, bluetooth: FakeBluetooth
) -> None:
    """Heard is present, silent for `away_after` is off, heard again is on."""
    bluetooth.advertise(ADDRESS)
    entry = await setup_entry(hass, ble_entry())
    manager = entry.runtime_data.manager
    await switch_on(hass, entry)

    # A beacon that keeps sending the very same payload is still heard.
    await listen(hass, freezer, bluetooth, 60 * MINUTE, advertise=ADDRESS)
    assert manager.is_home(TRACKER_A) is True

    # Silent: still present until the last advertisement is ten minutes old.
    await listen(hass, freezer, bluetooth, 10 * MINUTE - 30)
    assert manager.is_home(TRACKER_A) is True
    await listen(hass, freezer, bluetooth, 30)
    assert manager.is_home(TRACKER_A) is False

    # Heard again: on at the next look.
    bluetooth.advertise(ADDRESS)
    await listen(hass, freezer, bluetooth, 30)
    assert manager.is_home(TRACKER_A) is True

    await unload(hass, entry)


async def test_a_lost_advertisement_changes_nothing(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, bluetooth: FakeBluetooth
) -> None:
    """Gaps shorter than `away_after` are not an absence."""
    bluetooth.advertise(ADDRESS)
    entry = await setup_entry(hass, ble_entry(**{CONF_AWAY_AFTER: 2}))
    manager = entry.runtime_data.manager
    await switch_on(hass, entry)
    since = manager.since(TRACKER_A)

    for _ in range(10):
        await listen(hass, freezer, bluetooth, 90)
        bluetooth.advertise(ADDRESS)

    assert manager.is_home(TRACKER_A) is True
    assert manager.since(TRACKER_A) == since

    await unload(hass, entry)


async def test_a_bluetooth_device_heard_at_the_start_is_a_baseline(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, bluetooth: FakeBluetooth
) -> None:
    """Present at the start switches nothing on."""
    bluetooth.advertise(ADDRESS)
    entry = await setup_entry(hass, ble_entry())

    await listen(hass, freezer, bluetooth, 20 * MINUTE, advertise=ADDRESS)

    assert entry.runtime_data.manager.is_home(TRACKER_A) is False

    await unload(hass, entry)


async def test_a_bluetooth_device_first_heard_after_the_start_is_a_baseline(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, bluetooth: FakeBluetooth
) -> None:
    """The history is empty after a restart: not heard *yet* is not away."""
    entry = await setup_entry(hass, ble_entry())

    await listen(hass, freezer, bluetooth, 2 * MINUTE)
    bluetooth.advertise(ADDRESS)
    await listen(hass, freezer, bluetooth, 30)

    assert entry.runtime_data.manager.is_home(TRACKER_A) is False

    await unload(hass, entry)


async def test_a_bluetooth_device_never_heard_switches_off_after_the_start(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    bluetooth: FakeBluetooth,
    hass_storage: dict[str, Any],
) -> None:
    """Nothing heard for `away_after` since the start: a tracker that is on goes off."""
    hass_storage[STORE_KEY] = stored_home()
    entry = await setup_entry(hass, ble_entry())
    manager = entry.runtime_data.manager

    await listen(hass, freezer, bluetooth, 10 * MINUTE - 30)
    assert manager.is_home(TRACKER_A) is True
    await listen(hass, freezer, bluetooth, 30)
    assert manager.is_home(TRACKER_A) is False

    await unload(hass, entry)


async def test_bluetooth_and_entity_sources_combine(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, bluetooth: FakeBluetooth
) -> None:
    """Any of them present keeps the tracker present."""
    bluetooth.advertise(ADDRESS)
    hass.states.async_set(TAG, STATE_NOT_HOME)
    entry = await setup_entry(hass, ble_entry(**{CONF_PRESENCE_SOURCES: [TAG]}))
    manager = entry.runtime_data.manager
    await switch_on(hass, entry)

    await listen(hass, freezer, bluetooth, 30 * MINUTE, advertise=ADDRESS)
    assert manager.is_home(TRACKER_A) is True

    await listen(hass, freezer, bluetooth, 10 * MINUTE)
    assert manager.is_home(TRACKER_A) is False

    await unload(hass, entry)


async def test_without_bluetooth_an_address_is_never_known(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_storage: dict[str, Any]
) -> None:
    """No Bluetooth component: nothing is switched, nothing is imported."""
    hass_storage[STORE_KEY] = stored_home()
    with patch(
        "custom_components.virtual_presence_tracker.ble._bluetooth",
        side_effect=AssertionError("the Bluetooth API must not be touched"),
    ):
        entry = await setup_entry(hass, ble_entry())
        await tick(hass, freezer, 60 * MINUTE)

        assert entry.runtime_data.manager.is_home(TRACKER_A) is True

        await unload(hass, entry)


# --- The form ------------------------------------------------------------------


def field(result: dict[str, Any], key: str) -> Any:
    """Return the selector of one field of a form."""
    schema: vol.Schema = result["data_schema"]
    return next(value for marker, value in schema.schema.items() if marker == key)


def keys(result: dict[str, Any]) -> list[str]:
    """Return the fields of a form, in order."""
    return [str(marker) for marker in result["data_schema"].schema]


def suggested(result: dict[str, Any], key: str) -> Any:
    """Return the value a form suggests for one of its keys."""
    schema: vol.Schema = result["data_schema"]
    for marker in schema.schema:
        if marker == key:
            return (marker.description or {}).get("suggested_value")
    raise AssertionError(f"{key} is not part of the form")


async def start_form(hass: HomeAssistant, entry: MockConfigEntry) -> dict[str, Any]:
    """Open the form of a new tracker."""
    return await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_TRACKER), context={"source": SOURCE_USER}
    )


async def test_the_form_takes_presence_sources(hass: HomeAssistant) -> None:
    """Device trackers and binary sensors, stored as chosen, followed at once."""
    hass.states.async_set(TAG, STATE_NOT_HOME)
    entry = await setup_entry(hass, make_entry())

    result = await start_form(hass, entry)
    config = field(result, CONF_PRESENCE_SOURCES).config
    assert config["domain"] == ["device_tracker", "binary_sensor"]
    assert config["multiple"] is True
    # Without Bluetooth there is no field for it.
    assert CONF_BLE_SOURCES not in keys(result)

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {CONF_NAME: "Kid", CONF_CREATE_PERSON: False, CONF_PRESENCE_SOURCES: [TAG]},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    subentry = entry.get_subentries_of_type(SUBENTRY_TYPE_TRACKER)[0]
    assert subentry.data[CONF_PRESENCE_SOURCES] == [TAG]
    assert CONF_BLE_SOURCES not in subentry.data

    await set_state(hass, TAG, STATE_HOME)
    assert entry.runtime_data.manager.is_home(subentry.subentry_id) is True

    await unload(hass, entry)


async def test_the_form_leaves_out_the_own_entities(hass: HomeAssistant) -> None:
    """Our device trackers and the household sensor are neither offered nor kept."""
    entry = await setup_entry(
        hass,
        make_entry(
            make_subentry(
                TRACKER_A,
                "Kid",
                **{CONF_PRESENCE_SOURCES: [TAG, TRACKER_B_ENTITY]},
            ),
            make_subentry(TRACKER_B, "Granny"),
        ),
    )

    result = await entry.start_subentry_reconfigure_flow(hass, TRACKER_A)

    assert field(result, CONF_PRESENCE_SOURCES).config["exclude_entities"] == [
        SENSOR,
        TRACKER_B_ENTITY,
        TRACKER_A_ENTITY,
    ]
    assert suggested(result, CONF_PRESENCE_SOURCES) == [TAG]
    with pytest.raises(InvalidData):
        await hass.config_entries.subentries.async_configure(
            result["flow_id"],
            {
                CONF_NAME: "Kid",
                CONF_NOTIFY_PERSONS: [],
                CONF_PRESENCE_SOURCES: [TRACKER_B_ENTITY],
            },
        )

    await unload(hass, entry)


async def test_removing_every_source_clears_the_keys(
    hass: HomeAssistant, bluetooth: FakeBluetooth
) -> None:
    """A tracker without presence sources carries neither key, and no reload."""
    entry = await setup_entry(
        hass,
        ble_entry(**{CONF_PRESENCE_SOURCES: [TAG], CONF_NOTIFY_PERSONS: []}),
    )
    manager = entry.runtime_data.manager

    result = await entry.start_subentry_reconfigure_flow(hass, TRACKER_A)
    assert suggested(result, CONF_PRESENCE_SOURCES) == [TAG]
    assert suggested(result, CONF_BLE_SOURCES) == [ADDRESS]
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Kid",
            CONF_NOTIFY_PERSONS: [],
            CONF_PRESENCE_SOURCES: [],
            CONF_BLE_SOURCES: [],
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert dict(entry.subentries[TRACKER_A].data) == {CONF_NOTIFY_PERSONS: []}
    assert entry.runtime_data.manager is manager

    await unload(hass, entry)


async def test_the_bluetooth_field_is_kept_without_bluetooth(
    hass: HomeAssistant,
) -> None:
    """Edited while Bluetooth is not set up, the stored addresses stay."""
    entry = await setup_entry(hass, ble_entry(**{CONF_NOTIFY_PERSONS: []}))

    result = await entry.start_subentry_reconfigure_flow(hass, TRACKER_A)
    assert CONF_BLE_SOURCES not in keys(result)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_NAME: "Kid", CONF_NOTIFY_PERSONS: []}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert entry.subentries[TRACKER_A].data[CONF_BLE_SOURCES] == [ADDRESS]

    await unload(hass, entry)


async def test_the_bluetooth_devices_are_named_and_sorted(
    hass: HomeAssistant, bluetooth: FakeBluetooth
) -> None:
    """Registry name, else advertised name, else the address; strongest first."""
    bthome = MockConfigEntry(domain="bthome")
    bthome.add_to_hass(hass)
    dr.async_get(hass).async_get_or_create(
        config_entry_id=bthome.entry_id,
        connections={(dr.CONNECTION_BLUETOOTH, ADDRESS)},
        name="Shelly BLU Button1 5DC6",
    )
    bluetooth.advertise(OTHER_ADDRESS, name="ATC_000001", rssi=-80)
    bluetooth.advertise(ADDRESS, name="SBBT-002C", rssi=-60)
    bluetooth.advertise(THIRD_ADDRESS, rssi=-90)
    entry = await setup_entry(hass, make_entry())

    result = await start_form(hass, entry)

    assert keys(result)[-2:] == [CONF_PRESENCE_SOURCES, CONF_BLE_SOURCES]
    config = field(result, CONF_BLE_SOURCES).config
    assert config["options"] == [
        {"value": ADDRESS, "label": f"Shelly BLU Button1 5DC6 ({ADDRESS})"},
        {"value": OTHER_ADDRESS, "label": f"ATC_000001 ({OTHER_ADDRESS})"},
        {"value": THIRD_ADDRESS, "label": THIRD_ADDRESS},
    ]
    assert config["multiple"] is True
    assert config["custom_value"] is True

    await unload(hass, entry)


async def test_a_stored_address_stays_selectable(
    hass: HomeAssistant, bluetooth: FakeBluetooth
) -> None:
    """A device out of range is still offered, and pre-selected."""
    bluetooth.advertise(OTHER_ADDRESS, rssi=-50)
    entry = await setup_entry(hass, ble_entry(**{CONF_NOTIFY_PERSONS: []}))

    result = await entry.start_subentry_reconfigure_flow(hass, TRACKER_A)

    assert field(result, CONF_BLE_SOURCES).config["options"] == [
        {"value": OTHER_ADDRESS, "label": OTHER_ADDRESS},
        {"value": ADDRESS, "label": ADDRESS},
    ]
    assert suggested(result, CONF_BLE_SOURCES) == [ADDRESS]

    await unload(hass, entry)


async def test_a_typed_address_is_normalized(
    hass: HomeAssistant, bluetooth: FakeBluetooth
) -> None:
    """Lower case and dashes become the form the manager uses."""
    entry = await setup_entry(hass, make_entry())

    result = await start_form(hass, entry)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Kid",
            CONF_CREATE_PERSON: False,
            CONF_BLE_SOURCES: [" 7c-c6-b6-00-5d-c6 ", ADDRESS],
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    subentry = entry.get_subentries_of_type(SUBENTRY_TYPE_TRACKER)[0]
    assert subentry.data[CONF_BLE_SOURCES] == [ADDRESS]
    assert CONF_PRESENCE_SOURCES not in subentry.data

    await unload(hass, entry)


async def test_an_invalid_address_is_refused(
    hass: HomeAssistant, bluetooth: FakeBluetooth
) -> None:
    """The form names what it cannot read, and stores nothing."""
    entry = await setup_entry(hass, make_entry())

    result = await start_form(hass, entry)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Kid",
            CONF_CREATE_PERSON: False,
            CONF_BLE_SOURCES: [ADDRESS, "kid's tag"],
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_BLE_SOURCES: "invalid_ble_address"}
    assert result["description_placeholders"] == {"addresses": "kid's tag"}
    assert entry.get_subentries_of_type(SUBENTRY_TYPE_TRACKER) == []

    await unload(hass, entry)
