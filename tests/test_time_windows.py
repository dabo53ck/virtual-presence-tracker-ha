"""Tests for the time windows of the presence sources (M5).

A tracker with "Use time windows" ticked has a start and an end per weekday,
14 time entities on its device. Outside a window its presence sources do not
switch it on, and the departure rule treats them as not present; switching
off stays theirs. A window start ends the lock and switches on if a source is
present; a window end hands over to the question about a device left behind.
The use case: a cleaner who comes on Mondays and leaves a Bluetooth tag in the
house the rest of the week.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.virtual_presence_tracker import windows
from custom_components.virtual_presence_tracker.const import (
    CONF_ANSWER_TIMEOUT,
    CONF_ASK_LEFT_BEHIND,
    CONF_ASK_ON_DEPARTURE,
    CONF_AWAY_AFTER,
    CONF_CREATE_PERSON,
    CONF_NOTIFY_PERSONS,
    CONF_PRESENCE_SOURCES,
    CONF_USE_TIME_WINDOWS,
    DOMAIN,
    EVENT_LEFT_BEHIND_EXPIRED,
    EVENT_LEFT_BEHIND_STARTED,
    NO_RELOAD_KEYS,
    SECTION_SOURCES,
    SUBENTRY_TYPE_TRACKER,
    WINDOW_KEYS,
)
from homeassistant.components.time import DOMAIN as TIME_DOMAIN
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TIME,
    CONF_NAME,
    EVENT_STATE_CHANGED,
    STATE_HOME,
    STATE_NOT_HOME,
    STATE_UNAVAILABLE,
    EntityCategory,
)
from homeassistant.core import Event, HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .conftest import PERSON_A, TRACKER_A, TRACKER_B, make_entry, make_subentry

TAG = "device_tracker.cleaner_tag"
SWITCH_A = "switch.cleaner_at_home"
DEVICE_TRACKER_A = "device_tracker.cleaner"
MONDAY_START = "time.cleaner_monday_start"
MONDAY_END = "time.cleaner_monday_end"

# A time zone with daylight saving time, far from anybody's household.
ZONE = "America/Chicago"
CHICAGO = ZoneInfo(ZONE)
# Monday 2026-11-23, in the morning, before the cleaner's window.
MONDAY = datetime(2026, 11, 23, tzinfo=CHICAGO)

MINUTE = 60


def window_entry(**data: Any) -> MockConfigEntry:
    """Return an entry whose first tracker follows a tag on Mondays 09-12."""
    return make_entry(
        make_subentry(
            TRACKER_A,
            "Cleaner",
            **{
                CONF_PRESENCE_SOURCES: [TAG],
                CONF_USE_TIME_WINDOWS: True,
                "window_monday_start": "09:00:00",
                "window_monday_end": "12:00:00",
                CONF_AWAY_AFTER: 10,
                CONF_ANSWER_TIMEOUT: 10,
                CONF_NOTIFY_PERSONS: [],
                **data,
            },
        ),
        make_subentry(TRACKER_B, "Kid"),
    )


async def settle(hass: HomeAssistant) -> None:
    """Let everything follow."""
    await hass.async_block_till_done(wait_background_tasks=True)


async def move_to(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, moment: datetime
) -> None:
    """Let the clock run to a moment and fire whatever timer is due."""
    freezer.move_to(moment)
    async_fire_time_changed(hass, dt_util.as_utc(moment))
    await settle(hass)


def at(hour: int, minute: int = 0, days: int = 0) -> datetime:
    """Return a wall-clock moment on Monday, or `days` later, in Chicago."""
    day = MONDAY.date() + timedelta(days=days)
    return datetime.combine(day, time(hour, minute), tzinfo=CHICAGO)


async def set_tag(hass: HomeAssistant, state: str) -> None:
    """Move the cleaner's tag."""
    hass.states.async_set(TAG, state)
    await settle(hass)


async def set_person(hass: HomeAssistant, state: str) -> None:
    """Move the one real person of the household."""
    hass.states.async_set(PERSON_A, state)
    await settle(hass)


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> MockConfigEntry:
    """Add a config entry to hass and set it up."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await settle(hass)
    return entry


async def unload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Unload an entry, so that no timer is left running."""
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.fixture
async def chicago(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Run in Chicago, on Monday at 08:00, before the window opens."""
    await hass.config.async_set_time_zone(ZONE)
    freezer.move_to(at(8))


def make_windows(**days: tuple[str, str]) -> windows.Windows:
    """Return seven windows, every day without one unless given."""
    return windows.parse(
        {
            key: value
            for day, (start, end) in days.items()
            for key, value in (
                (f"window_{day}_start", start),
                (f"window_{day}_end", end),
            )
        }
    )


# --- The helper -------------------------------------------------------------------


def test_missing_keys_mean_no_windows() -> None:
    """Without the box and the times nothing is gated and nothing opens."""
    assert windows.enabled({}) is False
    parsed = windows.parse({})

    assert len(parsed) == 7
    assert all(window.empty for window in parsed)
    assert [window.describe() for window in parsed] == ["none"] * 7
    assert windows.in_window(parsed, at(10)) is False
    assert windows.next_boundary(parsed, at(10)) is None


def test_an_unreadable_time_is_midnight() -> None:
    """A value that cannot be read never opens a window by accident."""
    assert windows.parse_time("late") == time(0, 0)
    assert windows.parse_time(None) == time(0, 0)
    assert windows.parse_time("09:30:15") == time(9, 30, 15)
    assert windows.parse_time(time(7, 5)) == time(7, 5)


def test_start_is_inside_and_end_is_outside() -> None:
    """A window contains its start and not its end."""
    parsed = make_windows(monday=("09:00:00", "12:00:00"))

    assert parsed[0].describe() == "09:00-12:00"
    assert windows.in_window(parsed, at(8, 59)) is False
    assert windows.in_window(parsed, at(9)) is True
    assert windows.in_window(parsed, at(11, 59)) is True
    assert windows.in_window(parsed, at(12)) is False
    # The same hours on Tuesday are not Monday's window.
    assert windows.in_window(parsed, at(10, days=1)) is False


def test_the_same_start_and_end_mean_no_window() -> None:
    """Start = end is no window that day, at any time of it."""
    parsed = make_windows(monday=("09:00:00", "09:00:00"))

    assert parsed[0].empty is True
    assert windows.in_window(parsed, at(9)) is False
    assert windows.next_boundary(parsed, at(8)) is None


def test_a_window_runs_past_midnight() -> None:
    """Monday 22:00-06:00 is Monday 22:00 to Tuesday 06:00, and Monday's."""
    parsed = make_windows(monday=("22:00:00", "06:00:00"))

    assert windows.in_window(parsed, at(5, 59)) is False
    assert windows.in_window(parsed, at(21, 59)) is False
    assert windows.in_window(parsed, at(22)) is True
    assert windows.in_window(parsed, at(5, 59, days=1)) is True
    assert windows.in_window(parsed, at(6, days=1)) is False
    assert windows.next_boundary(parsed, at(8)) == at(22)
    assert windows.next_boundary(parsed, at(23)) == at(6, days=1)


def test_sunday_runs_into_monday() -> None:
    """The week wraps: Sunday's window may end on Monday morning."""
    parsed = make_windows(sunday=("23:00:00", "02:00:00"))

    assert windows.in_window(parsed, at(1)) is True
    assert windows.in_window(parsed, at(2)) is False
    assert windows.next_boundary(parsed, at(1)) == at(2)
    assert windows.next_boundary(parsed, at(3)) == at(23, days=6)


def test_the_next_boundary_is_always_after_now() -> None:
    """At a boundary the next one is the following start or end."""
    parsed = make_windows(
        monday=("09:00:00", "12:00:00"), wednesday=("14:00:00", "15:00:00")
    )

    assert windows.next_boundary(parsed, at(9)) == at(12)
    assert windows.next_boundary(parsed, at(12)) == at(14, days=2)
    assert windows.next_boundary(parsed, at(16, days=2)) == at(9, days=7)


def test_the_windows_follow_the_wall_clock_on_a_dst_day() -> None:
    """When the clocks go back, an overnight window ends at 06:00 local time.

    Chicago goes from daylight saving to standard time on Sunday 2026-11-01 at
    02:00, so Saturday 22:00-06:00 lasts nine hours, and its end is 12:00 UTC.
    """
    parsed = make_windows(saturday=("22:00:00", "06:00:00"))
    saturday = datetime(2026, 10, 31, 23, 0, tzinfo=CHICAGO)
    # 01:30 comes twice that night; both lie inside the window.
    first = datetime(2026, 11, 1, 6, 30, tzinfo=UTC).astimezone(CHICAGO)
    second = datetime(2026, 11, 1, 7, 30, tzinfo=UTC).astimezone(CHICAGO)

    end = windows.next_boundary(parsed, saturday)

    assert end is not None
    assert end.astimezone(UTC) == datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
    assert windows.in_window(parsed, first) is True
    assert windows.in_window(parsed, second) is True
    assert windows.next_boundary(parsed, second) == end


def test_a_start_the_clocks_skip_is_the_moment_of_the_jump() -> None:
    """When the clocks go forward, 02:30 does not exist; the jump at 03:00 is taken.

    Chicago skips from 02:00 to 03:00 on Sunday 2026-03-08.
    """
    parsed = make_windows(sunday=("02:30:00", "05:00:00"))
    before = datetime(2026, 3, 8, 1, 0, tzinfo=CHICAGO)
    jump = datetime(2026, 3, 8, 8, 0, tzinfo=UTC)

    start = windows.next_boundary(parsed, before)

    assert start is not None
    assert start.astimezone(UTC) == jump
    assert start.hour == 3 and start.minute == 0
    assert (
        windows.in_window(parsed, (jump - timedelta(seconds=1)).astimezone(CHICAGO))
        is False
    )
    assert windows.in_window(parsed, jump.astimezone(CHICAGO)) is True
    end = windows.next_boundary(parsed, jump.astimezone(CHICAGO))
    assert end is not None
    assert end.astimezone(UTC) == datetime(2026, 3, 8, 10, 0, tzinfo=UTC)


def test_an_end_the_clocks_skip_is_the_moment_of_the_jump() -> None:
    """A window until 02:30 on the night the clocks go forward ends at 03:00."""
    parsed = make_windows(sunday=("01:00:00", "02:30:00"))
    jump = datetime(2026, 3, 8, 8, 0, tzinfo=UTC)
    last_second = (jump - timedelta(seconds=1)).astimezone(CHICAGO)

    assert windows.in_window(parsed, last_second) is True
    assert windows.next_boundary(parsed, last_second) == jump
    assert windows.in_window(parsed, jump.astimezone(CHICAGO)) is False


def test_a_time_the_clocks_repeat_is_its_first_occurrence() -> None:
    """When the clocks go back, 01:30 comes twice; the first one counts.

    Chicago goes back from 02:00 CDT to 01:00 CST on Sunday 2026-11-01, so
    the first 01:30 is 06:30 UTC and the second one 07:30 UTC.
    """
    first = datetime(2026, 11, 1, 6, 30, tzinfo=UTC)
    ends = make_windows(sunday=("00:00:00", "01:30:00"))
    starts = make_windows(sunday=("01:30:00", "05:00:00"))
    before = datetime(2026, 11, 1, 0, 30, tzinfo=CHICAGO)

    # Compared in UTC: a time in the repeated hour never equals one in UTC.
    assert windows.next_boundary(ends, before).astimezone(UTC) == first
    assert windows.in_window(ends, first.astimezone(CHICAGO)) is False
    # The repeated hour after the end, 01:00-01:30 CST, stays outside.
    repeated = datetime(2026, 11, 1, 7, 15, tzinfo=UTC).astimezone(CHICAGO)
    assert windows.in_window(ends, repeated) is False

    assert windows.next_boundary(starts, before).astimezone(UTC) == first
    assert windows.in_window(starts, repeated) is True


# --- The entities -----------------------------------------------------------------


@pytest.mark.usefixtures("chicago")
async def test_a_tracker_with_time_windows_has_14_time_entities(
    hass: HomeAssistant,
) -> None:
    """A start and an end per weekday, on the device, under "Configuration"."""
    entry = await setup_entry(hass, window_entry())
    registry = er.async_get(hass)

    entities = [
        registry_entry
        for registry_entry in er.async_entries_for_config_entry(
            registry, entry.entry_id
        )
        if registry_entry.domain == TIME_DOMAIN
    ]

    assert sorted(registry_entry.unique_id for registry_entry in entities) == sorted(
        f"{TRACKER_A}_{key}" for key in WINDOW_KEYS
    )
    assert all(
        registry_entry.entity_category is EntityCategory.CONFIG
        and registry_entry.config_subentry_id == TRACKER_A
        and registry_entry.translation_key
        == registry_entry.unique_id.removeprefix(f"{TRACKER_A}_")
        for registry_entry in entities
    )
    assert hass.states.get(MONDAY_START).state == "09:00:00"
    assert hass.states.get(MONDAY_END).state == "12:00:00"
    # A day without a stored time shows midnight.
    assert hass.states.get("time.cleaner_tuesday_start").state == "00:00:00"
    assert hass.states.get("time.cleaner_sunday_end").state == "00:00:00"
    # The tracker without the box has none.
    assert not any(
        registry_entry.config_subentry_id == TRACKER_B for registry_entry in entities
    )
    await unload(hass, entry)


@pytest.mark.usefixtures("chicago")
async def test_writing_a_time_stores_it_without_a_reload(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The time lands in the subentry data, and the timer moves with it."""
    hass.states.async_set(TAG, STATE_HOME)
    entry = await setup_entry(hass, window_entry())
    manager = entry.runtime_data.manager
    changes: list[str] = []

    def record(event: Event[Any]) -> None:
        if event.data["entity_id"] == DEVICE_TRACKER_A:
            changes.append(event.data["new_state"].state)

    hass.bus.async_listen(EVENT_STATE_CHANGED, record)

    await hass.services.async_call(
        TIME_DOMAIN,
        "set_value",
        {ATTR_ENTITY_ID: MONDAY_START, ATTR_TIME: "08:30:00"},
        blocking=True,
    )
    await settle(hass)

    assert entry.subentries[TRACKER_A].data["window_monday_start"] == "08:30:00"
    assert hass.states.get(MONDAY_START).state == "08:30:00"
    assert entry.runtime_data.manager is manager
    assert changes == []
    assert all(key in NO_RELOAD_KEYS for key in WINDOW_KEYS)

    # The new start is the one that counts: the tag is there, so it goes on.
    await move_to(hass, freezer, at(8, 30))
    assert manager.is_home(TRACKER_A) is True
    await unload(hass, entry)


@pytest.mark.usefixtures("chicago")
async def test_unticking_the_box_removes_the_entities_and_keeps_the_times(
    hass: HomeAssistant,
) -> None:
    """The box reloads; the 14 entities go, their times stay for next time."""
    entry = await setup_entry(hass, window_entry())
    registry = er.async_get(hass)
    manager = entry.runtime_data.manager
    entity_id = registry.async_get_entity_id(
        TIME_DOMAIN, DOMAIN, f"{TRACKER_A}_window_monday_start"
    )
    assert entity_id == MONDAY_START

    subentry = entry.subentries[TRACKER_A]
    hass.config_entries.async_update_subentry(
        entry, subentry, data={**subentry.data, CONF_USE_TIME_WINDOWS: False}
    )
    await settle(hass)

    assert entry.runtime_data.manager is not manager
    assert not [
        registry_entry
        for registry_entry in er.async_entries_for_config_entry(
            registry, entry.entry_id
        )
        if registry_entry.domain == TIME_DOMAIN
    ]
    assert hass.states.get(MONDAY_START) is None
    assert entry.subentries[TRACKER_A].data["window_monday_start"] == "09:00:00"

    subentry = entry.subentries[TRACKER_A]
    hass.config_entries.async_update_subentry(
        entry, subentry, data={**subentry.data, CONF_USE_TIME_WINDOWS: True}
    )
    await settle(hass)

    assert hass.states.get(MONDAY_START).state == "09:00:00"
    await unload(hass, entry)


@pytest.mark.usefixtures("chicago")
async def test_the_form_box_adds_the_time_entities(hass: HomeAssistant) -> None:
    """Ticked in "Sources" of a new tracker, it is stored and the entities come."""
    entry = await setup_entry(hass, make_entry())

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_TRACKER), context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Cleaner",
            CONF_CREATE_PERSON: False,
            SECTION_SOURCES: {
                CONF_PRESENCE_SOURCES: [TAG],
                CONF_USE_TIME_WINDOWS: True,
            },
        },
    )
    await settle(hass)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    subentry = entry.get_subentries_of_type(SUBENTRY_TYPE_TRACKER)[0]
    assert subentry.data[CONF_USE_TIME_WINDOWS] is True
    # Only the box: no time is written until an entity writes one.
    assert not set(WINDOW_KEYS) & subentry.data.keys()
    assert hass.states.get(MONDAY_START).state == "00:00:00"
    await unload(hass, entry)


# --- The gate ---------------------------------------------------------------------


@pytest.mark.usefixtures("chicago")
async def test_outside_a_window_a_source_does_not_switch_on(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The edge is recorded, but only inside a window does it switch."""
    hass.states.async_set(TAG, STATE_NOT_HOME)
    entry = await setup_entry(hass, window_entry())
    manager = entry.runtime_data.manager

    await set_tag(hass, STATE_HOME)

    assert manager.is_home(TRACKER_A) is False
    assert manager.presence.known_presence(TRACKER_A) is True

    await set_tag(hass, STATE_NOT_HOME)
    await move_to(hass, freezer, at(9, 30))
    await set_tag(hass, STATE_HOME)

    assert manager.is_home(TRACKER_A) is True
    await unload(hass, entry)


@pytest.mark.usefixtures("chicago")
async def test_switching_off_is_not_gated(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """After the window, a tag that leaves still switches the tracker off."""
    hass.states.async_set(TAG, STATE_NOT_HOME)
    entry = await setup_entry(hass, window_entry())
    manager = entry.runtime_data.manager
    await move_to(hass, freezer, at(9, 30))
    await set_tag(hass, STATE_HOME)
    assert manager.is_home(TRACKER_A) is True

    await move_to(hass, freezer, at(12, 30))
    await set_tag(hass, STATE_NOT_HOME)
    await move_to(hass, freezer, at(12, 40))

    assert manager.is_home(TRACKER_A) is False
    await unload(hass, entry)


@pytest.mark.usefixtures("chicago")
async def test_buttons_and_the_switch_are_never_gated(hass: HomeAssistant) -> None:
    """Outside a window the tracker's own switch still switches it on."""
    hass.states.async_set(TAG, STATE_HOME)
    entry = await setup_entry(hass, window_entry())

    await hass.services.async_call(
        "switch", "turn_on", {ATTR_ENTITY_ID: SWITCH_A}, blocking=True
    )
    await settle(hass)

    assert entry.runtime_data.manager.is_home(TRACKER_A) is True
    await unload(hass, entry)


@pytest.mark.usefixtures("chicago")
async def test_the_departure_rule_asks_outside_a_window(
    hass: HomeAssistant,
) -> None:
    """A present tag outside a window is no reason to switch on: it asks."""
    hass.states.async_set(PERSON_A, STATE_HOME)
    hass.states.async_set(TAG, STATE_HOME)
    entry = await setup_entry(hass, window_entry(**{CONF_ASK_ON_DEPARTURE: True}))
    manager = entry.runtime_data.manager

    await set_person(hass, STATE_NOT_HOME)

    assert manager.is_home(TRACKER_A) is False
    assert manager.prompt_open(TRACKER_A) is True
    await unload(hass, entry)


@pytest.mark.usefixtures("chicago")
async def test_the_departure_rule_switches_on_inside_a_window(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Inside a window the present tag switches on instead of a prompt."""
    hass.states.async_set(PERSON_A, STATE_HOME)
    hass.states.async_set(TAG, STATE_NOT_HOME)
    entry = await setup_entry(hass, window_entry(**{CONF_ASK_ON_DEPARTURE: True}))
    manager = entry.runtime_data.manager
    await move_to(hass, freezer, at(9, 30))
    # Switched off by hand while the tag is there, then everybody leaves.
    await set_tag(hass, STATE_HOME)
    manager.async_set_home(TRACKER_A, False)
    await settle(hass)

    await set_person(hass, STATE_NOT_HOME)

    assert manager.is_home(TRACKER_A) is True
    assert manager.prompt_open(TRACKER_A) is False
    await unload(hass, entry)


# --- Window start -----------------------------------------------------------------


@pytest.mark.usefixtures("chicago")
async def test_a_window_start_switches_on_a_present_source(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The cleaner who arrives five minutes early is on at 09:00."""
    hass.states.async_set(TAG, STATE_NOT_HOME)
    entry = await setup_entry(hass, window_entry())
    manager = entry.runtime_data.manager
    await move_to(hass, freezer, at(8, 55))
    await set_tag(hass, STATE_HOME)
    assert manager.is_home(TRACKER_A) is False

    await move_to(hass, freezer, at(8, 59))
    assert manager.is_home(TRACKER_A) is False
    await move_to(hass, freezer, at(9))

    assert manager.is_home(TRACKER_A) is True
    await unload(hass, entry)


@pytest.mark.usefixtures("chicago")
async def test_a_window_start_without_a_present_source_does_nothing(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Nobody there at 09:00: the tracker stays off until the tag arrives."""
    hass.states.async_set(TAG, STATE_NOT_HOME)
    entry = await setup_entry(hass, window_entry())
    manager = entry.runtime_data.manager

    await move_to(hass, freezer, at(9))

    assert manager.is_home(TRACKER_A) is False
    await set_tag(hass, STATE_HOME)
    assert manager.is_home(TRACKER_A) is True
    await unload(hass, entry)


@pytest.mark.usefixtures("chicago")
async def test_writing_a_time_that_opens_the_window_is_a_start(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A start written to before now ends the lock and switches on the tag.

    The tag is left behind on Monday and the tracker locked after the
    unanswered question. On Tuesday at 10:00 a start of 09:00 is written; with
    the end at midnight the window is open now, so it counts as a window start.
    """
    hass.states.async_set(PERSON_A, STATE_NOT_HOME)
    hass.states.async_set(TAG, STATE_NOT_HOME)
    entry = await setup_entry(hass, window_entry(**{CONF_ASK_LEFT_BEHIND: True}))
    manager = entry.runtime_data.manager
    await move_to(hass, freezer, at(9, 5))
    await set_tag(hass, STATE_HOME)
    await move_to(hass, freezer, at(12))
    await move_to(hass, freezer, at(12, 10))
    await move_to(hass, freezer, at(12, 20))
    assert manager.source_locked(TRACKER_A) is True
    await move_to(hass, freezer, at(10, days=1))

    await hass.services.async_call(
        TIME_DOMAIN,
        "set_value",
        {ATTR_ENTITY_ID: "time.cleaner_tuesday_start", ATTR_TIME: "09:00:00"},
        blocking=True,
    )
    await settle(hass)

    assert manager.source_locked(TRACKER_A) is False
    assert manager.is_home(TRACKER_A) is True
    await unload(hass, entry)


@pytest.mark.usefixtures("chicago")
async def test_writing_a_time_that_closes_the_window_is_an_end(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """An end written to before now sets the wait mark; the question follows."""
    hass.states.async_set(PERSON_A, STATE_NOT_HOME)
    hass.states.async_set(TAG, STATE_NOT_HOME)
    entry = await setup_entry(hass, window_entry(**{CONF_ASK_LEFT_BEHIND: True}))
    manager = entry.runtime_data.manager
    events: list[str] = []
    manager.async_add_left_behind_listener(
        TRACKER_A, lambda event_type, _data: events.append(event_type)
    )
    await move_to(hass, freezer, at(9, 5))
    await set_tag(hass, STATE_HOME)
    await move_to(hass, freezer, at(10))
    tracker = manager.tracker_state(TRACKER_A)
    assert tracker.wait_since is None

    await hass.services.async_call(
        TIME_DOMAIN,
        "set_value",
        {ATTR_ENTITY_ID: MONDAY_END, ATTR_TIME: "09:30:00"},
        blocking=True,
    )
    await settle(hass)

    assert manager.presence.inside_window(TRACKER_A) is False
    assert tracker.wait_since == dt_util.as_utc(at(10))
    await move_to(hass, freezer, at(10, 9))
    assert events == []
    await move_to(hass, freezer, at(10, 10))
    assert events == [EVENT_LEFT_BEHIND_STARTED]
    await unload(hass, entry)


@pytest.mark.usefixtures("chicago")
async def test_writing_a_time_that_keeps_the_state_acts_on_nothing(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Moving the end of an open window later is neither a start nor an end."""
    hass.states.async_set(PERSON_A, STATE_NOT_HOME)
    hass.states.async_set(TAG, STATE_NOT_HOME)
    entry = await setup_entry(hass, window_entry(**{CONF_ASK_LEFT_BEHIND: True}))
    manager = entry.runtime_data.manager
    await move_to(hass, freezer, at(9, 5))
    await set_tag(hass, STATE_HOME)
    await move_to(hass, freezer, at(10))

    await hass.services.async_call(
        TIME_DOMAIN,
        "set_value",
        {ATTR_ENTITY_ID: MONDAY_END, ATTR_TIME: "13:00:00"},
        blocking=True,
    )
    await settle(hass)

    assert manager.tracker_state(TRACKER_A).wait_since is None
    await move_to(hass, freezer, at(12))
    assert manager.tracker_state(TRACKER_A).wait_since is None
    await move_to(hass, freezer, at(13))
    assert manager.tracker_state(TRACKER_A).wait_since == dt_util.as_utc(at(13))
    await unload(hass, entry)


@pytest.mark.usefixtures("chicago")
async def test_a_restart_inside_a_window_switches_nothing_on(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A tag present at the start is a baseline, as without windows."""
    freezer.move_to(at(10))
    hass.states.async_set(TAG, STATE_HOME)
    entry = await setup_entry(hass, window_entry())
    manager = entry.runtime_data.manager

    assert manager.is_home(TRACKER_A) is False

    await set_tag(hass, STATE_NOT_HOME)
    await set_tag(hass, STATE_HOME)
    assert manager.is_home(TRACKER_A) is True
    await unload(hass, entry)


@pytest.mark.usefixtures("chicago")
async def test_back_to_back_windows_neither_end_nor_start(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Monday until midnight and Tuesday from midnight are one long window."""
    hass.states.async_set(TAG, STATE_NOT_HOME)
    entry = await setup_entry(
        hass,
        window_entry(
            **{
                CONF_ASK_LEFT_BEHIND: True,
                "window_monday_end": "00:00:00",
                "window_tuesday_start": "00:00:00",
                "window_tuesday_end": "03:00:00",
            }
        ),
    )
    manager = entry.runtime_data.manager
    await move_to(hass, freezer, at(9, 30))
    await set_tag(hass, STATE_HOME)
    tracker = manager.tracker_state(TRACKER_A)

    await move_to(hass, freezer, at(0, days=1))

    assert manager.presence.inside_window(TRACKER_A) is True
    assert tracker.wait_since is None

    await move_to(hass, freezer, at(3, days=1))

    assert tracker.wait_since == dt_util.as_utc(at(3, days=1))
    await unload(hass, entry)


@pytest.mark.usefixtures("chicago")
async def test_a_change_of_the_time_zone_moves_the_window(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """In Denver the same 09:00 comes an hour later than in Chicago."""
    hass.states.async_set(TAG, STATE_NOT_HOME)
    entry = await setup_entry(hass, window_entry())
    manager = entry.runtime_data.manager
    await set_tag(hass, STATE_HOME)
    denver = ZoneInfo("America/Denver")

    await hass.config.async_update(time_zone="America/Denver")
    await settle(hass)
    await move_to(hass, freezer, at(9))
    assert manager.is_home(TRACKER_A) is False

    await move_to(hass, freezer, datetime(2026, 11, 23, 9, 0, tzinfo=denver))
    assert manager.is_home(TRACKER_A) is True
    await unload(hass, entry)


# --- The lock and the question about a device left behind -------------------------


@pytest.mark.usefixtures("chicago")
async def test_a_tag_left_behind_is_asked_about_after_the_window(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The whole week of a cleaner who forgot the tag.

    The window ends at 12:00 in an empty house, so the question comes at
    12:10; nobody answers, the tracker goes off and is locked. A flap the
    next day switches nothing; the next Monday's window ends the lock, and
    the tag that is still there switches the tracker on again.
    """
    hass.states.async_set(PERSON_A, STATE_NOT_HOME)
    hass.states.async_set(TAG, STATE_NOT_HOME)
    entry = await setup_entry(hass, window_entry(**{CONF_ASK_LEFT_BEHIND: True}))
    manager = entry.runtime_data.manager
    events: list[str] = []
    manager.async_add_left_behind_listener(
        TRACKER_A, lambda event_type, _data: events.append(event_type)
    )
    await move_to(hass, freezer, at(9, 5))
    await set_tag(hass, STATE_HOME)
    assert manager.is_home(TRACKER_A) is True

    await move_to(hass, freezer, at(12))
    tracker = manager.tracker_state(TRACKER_A)
    assert tracker.wait_since == dt_util.as_utc(at(12))
    await move_to(hass, freezer, at(12, 9))
    assert events == []

    await move_to(hass, freezer, at(12, 10))
    assert events == [EVENT_LEFT_BEHIND_STARTED]

    await move_to(hass, freezer, at(12, 20))
    assert events == [EVENT_LEFT_BEHIND_STARTED, EVENT_LEFT_BEHIND_EXPIRED]
    assert manager.is_home(TRACKER_A) is False
    assert manager.source_locked(TRACKER_A) is True

    await move_to(hass, freezer, at(10, days=1))
    await set_tag(hass, STATE_UNAVAILABLE)
    await set_tag(hass, STATE_NOT_HOME)
    await set_tag(hass, STATE_HOME)
    assert manager.is_home(TRACKER_A) is False

    await move_to(hass, freezer, at(9, days=7))
    assert manager.source_locked(TRACKER_A) is False
    assert manager.is_home(TRACKER_A) is True
    await unload(hass, entry)


@pytest.mark.usefixtures("chicago")
async def test_no_question_inside_a_window(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The cleaner alone in the empty house is not asked about.

    The last real person leaves at 09:30; the decision due at 09:40 is not
    made and the mark stays. The window end sets it again, so the question
    comes at 12:10.
    """
    hass.states.async_set(PERSON_A, STATE_HOME)
    hass.states.async_set(TAG, STATE_NOT_HOME)
    entry = await setup_entry(hass, window_entry(**{CONF_ASK_LEFT_BEHIND: True}))
    manager = entry.runtime_data.manager
    await move_to(hass, freezer, at(9, 5))
    await set_tag(hass, STATE_HOME)
    await move_to(hass, freezer, at(9, 30))
    await set_person(hass, STATE_NOT_HOME)
    tracker = manager.tracker_state(TRACKER_A)

    await move_to(hass, freezer, at(9, 40))

    assert manager.left_behind_open(TRACKER_A) is False
    assert tracker.wait_since == dt_util.as_utc(at(9, 30))

    await move_to(hass, freezer, at(12))
    assert tracker.wait_since == dt_util.as_utc(at(12))
    await move_to(hass, freezer, at(12, 10))

    assert manager.left_behind_open(TRACKER_A) is True
    await unload(hass, entry)


@pytest.mark.usefixtures("chicago")
async def test_a_window_end_with_somebody_home_sets_no_mark(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """With a real person at home there is no empty house to ask about."""
    hass.states.async_set(PERSON_A, STATE_HOME)
    hass.states.async_set(TAG, STATE_NOT_HOME)
    entry = await setup_entry(hass, window_entry(**{CONF_ASK_LEFT_BEHIND: True}))
    manager = entry.runtime_data.manager
    await move_to(hass, freezer, at(9, 5))
    await set_tag(hass, STATE_HOME)

    await move_to(hass, freezer, at(12))
    await move_to(hass, freezer, at(12, 10))

    assert manager.tracker_state(TRACKER_A).wait_since is None
    assert manager.left_behind_open(TRACKER_A) is False
    await unload(hass, entry)


# --- Diagnostics ------------------------------------------------------------------


@pytest.mark.usefixtures("chicago")
async def test_the_diagnostics_show_the_windows(
    hass: HomeAssistant, hass_client: ClientSessionGenerator
) -> None:
    """Per tracker: the box, the seven windows, now and the next boundary."""
    entry = await setup_entry(
        hass,
        window_entry(
            **{"window_friday_start": "22:00:00", "window_friday_end": "02:30:00"}
        ),
    )

    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    trackers = diagnostics["trackers"]
    assert trackers["tracker_1"]["time_windows"] == {
        "enabled": True,
        "windows": {
            "monday": "09:00-12:00",
            "tuesday": "none",
            "wednesday": "none",
            "thursday": "none",
            "friday": "22:00-02:30",
            "saturday": "none",
            "sunday": "none",
        },
        "in_window_now": False,
        "next_boundary": at(9).isoformat(),
    }
    assert trackers["tracker_2"]["time_windows"] == {
        "enabled": False,
        "windows": dict.fromkeys(
            (
                "monday",
                "tuesday",
                "wednesday",
                "thursday",
                "friday",
                "saturday",
                "sunday",
            ),
            "none",
        ),
        "in_window_now": None,
        "next_boundary": None,
    }
    await unload(hass, entry)
