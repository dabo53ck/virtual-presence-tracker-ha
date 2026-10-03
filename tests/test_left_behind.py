"""Tests for the question about a device left behind (M3f).

A tracker that a presence source keeps on while the house is empty is asked
about once per empty-house period, `away_after` after the last real person
left. "Yes" changes nothing, "no" and no answer switch the tracker off and lock
it against its presence sources until they have really been away, a real
person is home, the tracker is switched on another way, the option is switched
off or the sources change.
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

from custom_components.virtual_presence_tracker.const import (
    ANSWER_NO,
    ANSWER_YES,
    ATTR_ANSWER,
    ATTR_ANSWERED_BY,
    ATTR_EXPIRES_AT,
    ATTR_LEFT_BEHIND_EXPIRES_AT,
    ATTR_LEFT_BEHIND_ID,
    ATTR_LEFT_BEHIND_OPEN,
    ATTR_PROMPT_ID,
    ATTR_REASON,
    ATTR_REMINDER_ID,
    ATTR_SOURCES,
    ATTR_TRACKER,
    ATTR_USER_ID,
    BLUETOOTH_DOMAIN,
    CONF_ANSWER_TIMEOUT,
    CONF_ASK_LEFT_BEHIND,
    CONF_AWAY_AFTER,
    CONF_BLE_SOURCES,
    CONF_DEVICE_NAME,
    CONF_LEFT_BEHIND_OVERRIDE_DND,
    CONF_NOTIFY_ON_EXPIRY,
    CONF_NOTIFY_PERSONS,
    CONF_OVERRIDE_DND,
    CONF_PRESENCE_SOURCES,
    CONF_USER_ID,
    DOMAIN,
    EVENT_LEFT_BEHIND_ANSWERED_NO,
    EVENT_LEFT_BEHIND_ANSWERED_YES,
    EVENT_LEFT_BEHIND_CANCELLED,
    EVENT_LEFT_BEHIND_EXPIRED,
    EVENT_LEFT_BEHIND_STARTED,
    EVENT_NOTIFICATION_ACTION,
    EVENT_REMINDER_CANCELLED,
    MOBILE_APP_DOMAIN,
    NOTIFICATION_ICON,
    NOTIFY_DOMAIN,
    REASON_OPTION_DISABLED,
    REASON_PERSON_HOME,
    REASON_SWITCHED_OFF,
    SERVICE_ANSWER_LEFT_BEHIND,
    SERVICE_OPEN_LEFT_BEHIND,
    STORAGE_KEY_PREFIX,
    STORAGE_VERSION,
)
from custom_components.virtual_presence_tracker.issues import (
    ISSUE_RECIPIENT_WITHOUT_PHONE,
)
from custom_components.virtual_presence_tracker.manager import OpenLeftBehindResult
from custom_components.virtual_presence_tracker.messages import (
    _TEXTS,
    async_left_behind_message,
)
from homeassistant.components.event import ATTR_EVENT_TYPE
from homeassistant.components.switch import (
    DOMAIN as SWITCH_DOMAIN,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_FRIENDLY_NAME,
    STATE_HOME,
    STATE_NOT_HOME,
    STATE_OFF,
    EntityCategory,
)
from homeassistant.core import Context, HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.util import dt as dt_util

from .conftest import (
    ENTRY_ID,
    PERSON_A,
    TRACKER_A,
    TRACKER_B,
    make_entry,
    make_subentry,
)

TABLET = "device_tracker.xiaomi_tablet"
TABLET_NAME = "Xiaomi Tablet"
WATCH = "binary_sensor.kid_watch"
ADDRESS = "7C:C6:B6:00:5D:C6"

SWITCH_A = "switch.kid_at_home"
EVENT_A = "event.kid_questions"
ASK_A = "switch.kid_ask_about_a_device_left_behind"
DND_A = "switch.kid_override_do_not_disturb_for_a_device_left_behind"

USER_A = "user-dabo53ck"
PHONE_A = "mobile_app_dabo53ck_s_phone"
GROUP_KID = "Virtual presence: Kid"

MINUTE = 60
STORE_KEY = f"{STORAGE_KEY_PREFIX}.{ENTRY_ID}"


def left_behind_entry(sources: list[str] | None = None, **data: Any) -> MockConfigEntry:
    """Return an entry whose first tracker follows the tablet and asks about it."""
    return make_entry(
        make_subentry(
            TRACKER_A,
            "Kid",
            **{
                CONF_PRESENCE_SOURCES: sources if sources is not None else [TABLET],
                CONF_ASK_LEFT_BEHIND: True,
                CONF_AWAY_AFTER: 10,
                CONF_ANSWER_TIMEOUT: 10,
                CONF_NOTIFY_PERSONS: [PERSON_A],
                **data,
            },
        ),
        make_subentry(TRACKER_B, "Granny"),
    )


def add_phone(hass: HomeAssistant) -> list[ServiceCall]:
    """Register the real person's phone and mock its notify service."""
    MockConfigEntry(
        domain=MOBILE_APP_DOMAIN,
        title="dabo53ck's Phone",
        data={CONF_DEVICE_NAME: "dabo53ck's Phone", CONF_USER_ID: USER_A},
    ).add_to_hass(hass)
    return async_mock_service(hass, NOTIFY_DOMAIN, PHONE_A)


def set_person_state(hass: HomeAssistant, state: str) -> None:
    """Write the state of the one real person, with the user it belongs to."""
    hass.states.async_set(PERSON_A, state, {ATTR_USER_ID: USER_A})


def set_tablet_state(hass: HomeAssistant, state: str) -> None:
    """Write the state of the tablet, with its friendly name."""
    hass.states.async_set(TABLET, state, {ATTR_FRIENDLY_NAME: TABLET_NAME})


async def settle(hass: HomeAssistant) -> None:
    """Let everything follow, the messages that go out included."""
    await hass.async_block_till_done(wait_background_tasks=True)


async def set_person(hass: HomeAssistant, state: str) -> None:
    """Move the one real person of the household."""
    set_person_state(hass, state)
    await settle(hass)


async def set_tablet(hass: HomeAssistant, state: str) -> None:
    """Move the tablet."""
    set_tablet_state(hass, state)
    await settle(hass)


async def tick(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: float
) -> None:
    """Let time pass and fire whatever timer is due."""
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
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


class Recorder:
    """Collect the events of the question about a device left behind."""

    def __init__(self, entry: MockConfigEntry) -> None:
        """Subscribe to the first tracker's question about a device."""
        self.events: list[tuple[str, dict[str, Any]]] = []
        entry.runtime_data.manager.async_add_left_behind_listener(
            TRACKER_A, self._record
        )

    def _record(self, event_type: str, data: dict[str, Any]) -> None:
        """Remember one event."""
        self.events.append((event_type, dict(data)))

    @property
    def types(self) -> list[str]:
        """Return the types of the events seen so far."""
        return [event_type for event_type, _ in self.events]


async def start_with_tablet_at_home(
    hass: HomeAssistant, entry: MockConfigEntry | None = None
) -> MockConfigEntry:
    """Set up with the real person and the tablet at home, then leave.

    The person leaves while the tablet stays: the departure rule of the
    presence sources switches the tracker on, which is the case the question
    is there for.
    """
    set_person_state(hass, STATE_HOME)
    set_tablet_state(hass, STATE_HOME)
    entry = await setup_entry(hass, entry or left_behind_entry())
    await set_person(hass, STATE_NOT_HOME)
    assert entry.runtime_data.manager.is_home(TRACKER_A) is True
    return entry


async def ask(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    entry: MockConfigEntry | None = None,
) -> MockConfigEntry:
    """Leave the tablet at home and wait until the question is asked."""
    entry = await start_with_tablet_at_home(hass, entry)
    await tick(hass, freezer, 10 * MINUTE)
    assert entry.runtime_data.manager.left_behind_open(TRACKER_A) is True
    return entry


async def answer(hass: HomeAssistant, value: str, **data: Any) -> None:
    """Answer the question about a device left behind with the action."""
    await hass.services.async_call(
        DOMAIN,
        SERVICE_ANSWER_LEFT_BEHIND,
        {ATTR_ENTITY_ID: SWITCH_A, ATTR_ANSWER: value, **data},
        blocking=True,
    )
    await settle(hass)


async def flap(hass: HomeAssistant) -> None:
    """Let the router report the tablet away for a moment, then back."""
    await set_tablet(hass, STATE_NOT_HOME)
    await set_tablet(hass, STATE_HOME)


def last_event(hass: HomeAssistant) -> dict[str, Any]:
    """Return the attributes of the tracker's event entity."""
    return dict(hass.states.get(EVENT_A).attributes)


# --- When it asks ---------------------------------------------------------------


async def test_it_asks_away_after_after_the_departure(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Not at the departure, but `away_after` later - naming the device."""
    entry = await start_with_tablet_at_home(hass)
    events = Recorder(entry)
    manager = entry.runtime_data.manager

    await tick(hass, freezer, 10 * MINUTE - 1)
    assert events.types == []

    await tick(hass, freezer, 1)

    assert events.types == [EVENT_LEFT_BEHIND_STARTED]
    data = events.events[0][1]
    assert data[ATTR_LEFT_BEHIND_ID]
    assert data[ATTR_TRACKER] == "Kid"
    assert data[ATTR_SOURCES] == [TABLET]
    assert data[ATTR_EXPIRES_AT] == (
        manager.left_behind_expires_at(TRACKER_A).isoformat()
    )
    # A question of its own: it never carries the other two IDs.
    assert ATTR_PROMPT_ID not in data
    assert ATTR_REMINDER_ID not in data
    attributes = hass.states.get(SWITCH_A).attributes
    assert attributes[ATTR_LEFT_BEHIND_OPEN] is True
    assert attributes[ATTR_LEFT_BEHIND_EXPIRES_AT] == data[ATTR_EXPIRES_AT]
    assert last_event(hass)[ATTR_EVENT_TYPE] == EVENT_LEFT_BEHIND_STARTED
    # Asking changes nothing by itself.
    assert manager.is_home(TRACKER_A) is True

    await answer(hass, ANSWER_YES)
    await unload(hass, entry)


async def test_without_the_option_nothing_is_asked(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Off by default: a tracker without the key never asks."""
    entry = await start_with_tablet_at_home(
        hass, left_behind_entry(**{CONF_ASK_LEFT_BEHIND: False})
    )
    events = Recorder(entry)

    await tick(hass, freezer, 60 * MINUTE)

    assert events.types == []
    assert entry.runtime_data.manager.is_home(TRACKER_A) is True

    await unload(hass, entry)


async def test_a_tracker_without_sources_is_never_asked(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The question is about presence sources; without any there is none."""
    set_person_state(hass, STATE_HOME)
    entry = await setup_entry(hass, left_behind_entry(sources=[]))
    manager = entry.runtime_data.manager
    manager.async_set_home(TRACKER_A, True)
    events = Recorder(entry)

    await set_person(hass, STATE_NOT_HOME)
    await tick(hass, freezer, 60 * MINUTE)

    assert events.types == []

    await unload(hass, entry)


async def test_sources_that_left_are_not_asked_about(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """At the decision the sources are absent: nothing is asked."""
    entry = await start_with_tablet_at_home(hass)
    events = Recorder(entry)
    manager = entry.runtime_data.manager

    await tick(hass, freezer, 2 * MINUTE)
    await set_tablet(hass, STATE_NOT_HOME)
    await tick(hass, freezer, 8 * MINUTE)

    assert events.types == []
    # The sources switch the tracker off themselves, `away_after` after they left.
    await tick(hass, freezer, 2 * MINUTE)
    assert manager.is_home(TRACKER_A) is False

    # Coming back later in the same period is an arrival, not a device left
    # behind: the period's decision has been made.
    await set_tablet(hass, STATE_HOME)
    assert manager.is_home(TRACKER_A) is True
    await tick(hass, freezer, 60 * MINUTE)
    assert events.types == []

    await unload(hass, entry)


async def test_the_option_switched_on_while_the_house_is_empty_asks_at_once(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The waiting mark stays while the option is off, so it decides then."""
    entry = await start_with_tablet_at_home(
        hass, left_behind_entry(**{CONF_ASK_LEFT_BEHIND: False})
    )
    events = Recorder(entry)
    await tick(hass, freezer, 30 * MINUTE)
    assert events.types == []

    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: ASK_A}, blocking=True
    )
    await settle(hass)

    assert events.types == [EVENT_LEFT_BEHIND_STARTED]

    await answer(hass, ANSWER_YES)
    await unload(hass, entry)


async def test_a_longer_away_after_moves_the_decision(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """`away_after` is read live: the decision follows a new value."""
    entry = await start_with_tablet_at_home(hass)
    events = Recorder(entry)
    manager = entry.runtime_data.manager

    await tick(hass, freezer, 5 * MINUTE)
    manager.async_set_option(TRACKER_A, CONF_AWAY_AFTER, 20)
    await tick(hass, freezer, 10 * MINUTE)
    assert events.types == []

    await tick(hass, freezer, 5 * MINUTE)
    assert events.types == [EVENT_LEFT_BEHIND_STARTED]

    await answer(hass, ANSWER_YES)
    await unload(hass, entry)


# --- Bluetooth tags that left with the person -----------------------------------


@dataclass
class _ServiceInfo:
    """What the Bluetooth manager hands out about one device."""

    address: str
    name: str
    rssi: int
    time: float


class FakeBluetooth:
    """The calls of Home Assistant's Bluetooth API the integration uses."""

    def __init__(self) -> None:
        """Start with an empty history at an arbitrary monotonic time."""
        self.clock = 5000.0
        self.history: dict[str, _ServiceInfo] = {}

    def MONOTONIC_TIME(self) -> float:
        """Return the manager's clock."""
        return self.clock

    def advertise(self, address: str) -> None:
        """Receive one advertisement."""
        self.history[address] = _ServiceInfo(address, address, -70, self.clock)

    def async_last_service_info(
        self, hass: HomeAssistant, address: str, connectable: bool = True
    ) -> _ServiceInfo | None:
        """Return the last advertisement of an address."""
        return self.history.get(address)


@pytest.fixture
def fake_bluetooth(hass: HomeAssistant) -> Iterator[FakeBluetooth]:
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


async def test_a_tag_that_left_with_the_person_is_not_counted(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, fake_bluetooth: FakeBluetooth
) -> None:
    """At the departure the tag is still "present"; at the decision it is not.

    The child leaves with the tag in the school bag, the tablet stays: the
    question names the tablet only, because the tag has not been heard for
    `away_after` by then.
    """
    set_person_state(hass, STATE_HOME)
    set_tablet_state(hass, STATE_HOME)
    fake_bluetooth.advertise(ADDRESS)
    entry = await setup_entry(hass, left_behind_entry(**{CONF_BLE_SOURCES: [ADDRESS]}))
    events = Recorder(entry)
    await listen(hass, freezer, fake_bluetooth, 15 * MINUTE, advertise=ADDRESS)

    await set_person(hass, STATE_NOT_HOME)
    assert entry.runtime_data.manager.is_home(TRACKER_A) is True
    await listen(hass, freezer, fake_bluetooth, 10 * MINUTE)

    assert events.types == [EVENT_LEFT_BEHIND_STARTED]
    assert events.events[0][1][ATTR_SOURCES] == [TABLET]

    await answer(hass, ANSWER_YES)
    await unload(hass, entry)


async def test_a_tag_alone_that_left_is_never_asked_about(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, fake_bluetooth: FakeBluetooth
) -> None:
    """The tag was the only source and it left: no question, the tracker goes off."""
    set_person_state(hass, STATE_HOME)
    fake_bluetooth.advertise(ADDRESS)
    entry = await setup_entry(
        hass, left_behind_entry(sources=[], **{CONF_BLE_SOURCES: [ADDRESS]})
    )
    events = Recorder(entry)
    await listen(hass, freezer, fake_bluetooth, 15 * MINUTE, advertise=ADDRESS)

    await set_person(hass, STATE_NOT_HOME)
    assert entry.runtime_data.manager.is_home(TRACKER_A) is True
    await listen(hass, freezer, fake_bluetooth, 15 * MINUTE)

    assert events.types == []
    assert entry.runtime_data.manager.is_home(TRACKER_A) is False

    await unload(hass, entry)


async def test_a_tag_left_at_home_is_named_by_its_device(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, fake_bluetooth: FakeBluetooth
) -> None:
    """A Bluetooth source is named after its device in the registry."""
    calls = add_phone(hass)
    other = MockConfigEntry(domain="bthome")
    other.add_to_hass(hass)
    dr.async_get(hass).async_get_or_create(
        config_entry_id=other.entry_id,
        connections={(dr.CONNECTION_BLUETOOTH, ADDRESS)},
        name="Shelly BLU Button1 5DC6",
    )
    set_person_state(hass, STATE_HOME)
    fake_bluetooth.advertise(ADDRESS)
    entry = await setup_entry(
        hass, left_behind_entry(sources=[], **{CONF_BLE_SOURCES: [ADDRESS]})
    )
    await listen(hass, freezer, fake_bluetooth, 15 * MINUTE, advertise=ADDRESS)

    await set_person(hass, STATE_NOT_HOME)
    await listen(hass, freezer, fake_bluetooth, 10 * MINUTE, advertise=ADDRESS)

    assert last_event(hass)[ATTR_SOURCES] == [ADDRESS]
    assert (
        calls[0]
        .data["message"]
        .startswith("Nobody else is home, but Shelly BLU Button1 5DC6 is.")
    )

    await answer(hass, ANSWER_YES)
    await unload(hass, entry)


async def test_a_tag_without_a_device_is_named_by_its_address(
    hass: HomeAssistant, fake_bluetooth: FakeBluetooth
) -> None:
    """No registry name: the address is the name."""
    calls = add_phone(hass)
    set_person_state(hass, STATE_HOME)
    fake_bluetooth.advertise(ADDRESS)
    entry = await setup_entry(
        hass, left_behind_entry(sources=[], **{CONF_BLE_SOURCES: [ADDRESS]})
    )
    manager = entry.runtime_data.manager
    manager.async_set_home(TRACKER_A, True)

    assert manager.async_open_left_behind(TRACKER_A) is OpenLeftBehindResult.OPENED
    await settle(hass)

    assert (
        calls[0].data["message"].startswith(f"Nobody else is home, but {ADDRESS} is.")
    )

    await answer(hass, ANSWER_YES)
    await unload(hass, entry)


# --- Answers ------------------------------------------------------------------------


async def test_yes_changes_nothing_and_asks_once_per_period(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """After "yes", nothing asks again until the next departure."""
    entry = await ask(hass, freezer)
    events = Recorder(entry)
    manager = entry.runtime_data.manager

    await answer(hass, ANSWER_YES, **{ATTR_ANSWERED_BY: PERSON_A})

    assert events.types == [EVENT_LEFT_BEHIND_ANSWERED_YES]
    assert events.events[0][1][ATTR_ANSWERED_BY] == PERSON_A
    assert manager.is_home(TRACKER_A) is True
    assert hass.states.get(SWITCH_A).attributes[ATTR_LEFT_BEHIND_OPEN] is False

    await flap(hass)
    await tick(hass, freezer, 120 * MINUTE)
    assert events.types == [EVENT_LEFT_BEHIND_ANSWERED_YES]

    # A real person comes home and leaves again: a new period, a new question.
    await set_person(hass, STATE_HOME)
    await set_person(hass, STATE_NOT_HOME)
    await tick(hass, freezer, 10 * MINUTE)
    assert events.types[-1] == EVENT_LEFT_BEHIND_STARTED

    await answer(hass, ANSWER_YES)
    await unload(hass, entry)


async def test_no_switches_off_and_a_flapping_source_does_not_switch_on(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The anti-flap lock: ask -> off -> on -> ask ... never happens."""
    entry = await ask(hass, freezer)
    events = Recorder(entry)
    manager = entry.runtime_data.manager

    await answer(hass, ANSWER_NO, **{ATTR_ANSWERED_BY: PERSON_A})

    assert events.types == [EVENT_LEFT_BEHIND_ANSWERED_NO]
    assert events.events[0][1][ATTR_ANSWERED_BY] == PERSON_A
    assert manager.is_home(TRACKER_A) is False
    assert manager.source_locked(TRACKER_A) is True
    # A "no" is not also a withdrawal.
    assert EVENT_LEFT_BEHIND_CANCELLED not in events.types

    # The router reports the tablet away for a minute and back: still off.
    await set_tablet(hass, STATE_NOT_HOME)
    await tick(hass, freezer, MINUTE)
    await set_tablet(hass, STATE_HOME)
    assert manager.is_home(TRACKER_A) is False
    await tick(hass, freezer, 120 * MINUTE)
    assert manager.is_home(TRACKER_A) is False
    assert events.types == [EVENT_LEFT_BEHIND_ANSWERED_NO]

    await unload(hass, entry)


async def test_no_answer_switches_off_locks_and_sends_the_notice(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The one place where no answer changes a tracker - deliberately."""
    calls = add_phone(hass)
    entry = await ask(hass, freezer, left_behind_entry(**{CONF_NOTIFY_ON_EXPIRY: True}))
    manager = entry.runtime_data.manager
    left_behind_id = last_event(hass)[ATTR_LEFT_BEHIND_ID]

    await tick(hass, freezer, 10 * MINUTE - 1)
    assert manager.is_home(TRACKER_A) is True
    await tick(hass, freezer, 1)

    assert manager.is_home(TRACKER_A) is False
    assert manager.source_locked(TRACKER_A) is True
    assert last_event(hass)[ATTR_EVENT_TYPE] == EVENT_LEFT_BEHIND_EXPIRED
    assert [call.data.get("message") for call in calls[1:]] == [
        "clear_notification",
        "No answer: Kid has been switched off.",
    ]
    assert calls[1].data["data"] == {"tag": f"vpt_left_behind_{left_behind_id}"}
    assert calls[2].data == {
        "title": "No answer",
        "message": "No answer: Kid has been switched off.",
        "data": {
            "tag": f"vpt_info_{left_behind_id}",
            "icon_url": NOTIFICATION_ICON,
            "group": GROUP_KID,
        },
    }

    await flap(hass)
    assert manager.is_home(TRACKER_A) is False

    await unload(hass, entry)


async def test_an_expiry_without_the_option_sends_no_notice(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Off is still off; only the message is left out."""
    calls = add_phone(hass)
    entry = await ask(hass, freezer)

    await tick(hass, freezer, 10 * MINUTE)

    assert entry.runtime_data.manager.is_home(TRACKER_A) is False
    assert [call.data["message"] for call in calls[1:]] == ["clear_notification"]

    await unload(hass, entry)


async def test_without_recipients_it_still_switches_off(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """An automation may be the delivery: the question runs without phones."""
    entry = await ask(hass, freezer, left_behind_entry(**{CONF_NOTIFY_PERSONS: []}))

    await tick(hass, freezer, 10 * MINUTE)

    assert entry.runtime_data.manager.is_home(TRACKER_A) is False
    assert last_event(hass)[ATTR_EVENT_TYPE] == EVENT_LEFT_BEHIND_EXPIRED

    await unload(hass, entry)


# --- The end of the lock --------------------------------------------------------------


async def lock(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> MockConfigEntry:
    """Ask, answer "no" and return the entry with its tracker locked."""
    entry = await ask(hass, freezer)
    await answer(hass, ANSWER_NO)
    assert entry.runtime_data.manager.source_locked(TRACKER_A) is True
    return entry


async def test_the_lock_ends_when_the_sources_were_really_away(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Away for `away_after`, then back: that is a real arrival again."""
    entry = await lock(hass, freezer)
    manager = entry.runtime_data.manager

    await set_tablet(hass, STATE_NOT_HOME)
    await tick(hass, freezer, 10 * MINUTE - 1)
    assert manager.source_locked(TRACKER_A) is True
    await tick(hass, freezer, 1)
    assert manager.source_locked(TRACKER_A) is False

    await set_tablet(hass, STATE_HOME)
    assert manager.is_home(TRACKER_A) is True

    await unload(hass, entry)


async def test_the_lock_ends_when_a_real_person_comes_home(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The empty-house period is over."""
    entry = await lock(hass, freezer)
    manager = entry.runtime_data.manager

    await set_person(hass, STATE_HOME)
    assert manager.source_locked(TRACKER_A) is False

    await flap(hass)
    assert manager.is_home(TRACKER_A) is True

    await unload(hass, entry)


async def test_the_lock_ends_on_any_other_switch_on(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The switch is never locked, and using it is better information."""
    entry = await lock(hass, freezer)
    manager = entry.runtime_data.manager

    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: SWITCH_A}, blocking=True
    )
    assert manager.is_home(TRACKER_A) is True
    assert manager.source_locked(TRACKER_A) is False
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: SWITCH_A}, blocking=True
    )

    await flap(hass)
    assert manager.is_home(TRACKER_A) is True

    await unload(hass, entry)


async def test_the_lock_ends_when_the_option_is_switched_off(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Without the question there is no loop to guard against."""
    entry = await lock(hass, freezer)
    manager = entry.runtime_data.manager

    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: ASK_A}, blocking=True
    )
    assert manager.source_locked(TRACKER_A) is False

    await flap(hass)
    assert manager.is_home(TRACKER_A) is True

    await unload(hass, entry)


async def test_the_lock_ends_when_the_sources_change(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The lock was about the old sources."""
    entry = await lock(hass, freezer)
    manager = entry.runtime_data.manager
    hass.states.async_set(WATCH, STATE_OFF)
    subentry = entry.subentries[TRACKER_A]

    hass.config_entries.async_update_subentry(
        entry,
        subentry,
        data={**subentry.data, CONF_PRESENCE_SOURCES: [TABLET, WATCH]},
    )
    await settle(hass)

    assert manager.source_locked(TRACKER_A) is False
    await flap(hass)
    assert manager.is_home(TRACKER_A) is True

    await unload(hass, entry)


async def test_the_lock_survives_a_restart(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """After a restart the next flap would be an edge again - not while locked."""
    entry = await lock(hass, freezer)

    assert await hass.config_entries.async_reload(entry.entry_id)
    await settle(hass)

    manager = entry.runtime_data.manager
    assert manager.source_locked(TRACKER_A) is True
    await flap(hass)
    assert manager.is_home(TRACKER_A) is False

    await unload(hass, entry)


# --- Withdrawn ----------------------------------------------------------------------


async def test_a_real_person_coming_home_withdraws_it(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Somebody real is at home: the question no longer applies."""
    entry = await ask(hass, freezer)

    await set_person(hass, STATE_HOME)

    assert last_event(hass)[ATTR_EVENT_TYPE] == EVENT_LEFT_BEHIND_CANCELLED
    assert last_event(hass)[ATTR_REASON] == REASON_PERSON_HOME
    assert entry.runtime_data.manager.is_home(TRACKER_A) is True

    await unload(hass, entry)


async def test_switching_off_withdraws_it(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Off by hand answers the question: withdrawn, and nothing is locked."""
    entry = await ask(hass, freezer)

    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: SWITCH_A}, blocking=True
    )
    await settle(hass)

    assert last_event(hass)[ATTR_EVENT_TYPE] == EVENT_LEFT_BEHIND_CANCELLED
    assert last_event(hass)[ATTR_REASON] == REASON_SWITCHED_OFF
    assert entry.runtime_data.manager.source_locked(TRACKER_A) is False

    await unload(hass, entry)


async def test_sources_going_away_keep_it_open_until_they_switch_off(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A source that goes away is not a withdrawal - only its switch-off is.

    Withdrawing at the absent edge would spend the period's question on a
    router that lost the tablet for a minute.
    """
    entry = await ask(hass, freezer, left_behind_entry(**{CONF_ANSWER_TIMEOUT: 30}))
    manager = entry.runtime_data.manager

    await set_tablet(hass, STATE_NOT_HOME)
    await tick(hass, freezer, 10 * MINUTE - 1)
    assert manager.left_behind_open(TRACKER_A) is True

    await tick(hass, freezer, 1)

    assert manager.is_home(TRACKER_A) is False
    assert last_event(hass)[ATTR_EVENT_TYPE] == EVENT_LEFT_BEHIND_CANCELLED
    assert last_event(hass)[ATTR_REASON] == REASON_SWITCHED_OFF
    assert manager.source_locked(TRACKER_A) is False

    await unload(hass, entry)


async def test_switching_the_option_off_withdraws_it(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """At once, and live - not at the next restart."""
    entry = await ask(hass, freezer)

    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: ASK_A}, blocking=True
    )
    await settle(hass)

    assert last_event(hass)[ATTR_EVENT_TYPE] == EVENT_LEFT_BEHIND_CANCELLED
    assert last_event(hass)[ATTR_REASON] == REASON_OPTION_DISABLED
    assert entry.runtime_data.manager.is_home(TRACKER_A) is True

    await unload(hass, entry)


async def test_switching_the_option_off_keeps_one_opened_by_hand(
    hass: HomeAssistant,
) -> None:
    """A question somebody opened was never about the option."""
    set_person_state(hass, STATE_HOME)
    set_tablet_state(hass, STATE_HOME)
    entry = await setup_entry(hass, left_behind_entry())
    manager = entry.runtime_data.manager
    manager.async_set_home(TRACKER_A, True)
    await hass.services.async_call(
        DOMAIN, SERVICE_OPEN_LEFT_BEHIND, {ATTR_ENTITY_ID: SWITCH_A}, blocking=True
    )

    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: ASK_A}, blocking=True
    )
    await settle(hass)

    assert manager.left_behind_open(TRACKER_A) is True

    await answer(hass, ANSWER_YES)
    await unload(hass, entry)


async def test_it_can_be_open_together_with_a_reminder(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Both are about a tracker that is on; "no" here withdraws the reminder."""
    entry = await ask(hass, freezer)
    manager = entry.runtime_data.manager
    manager.async_open_reminder(TRACKER_A)
    await settle(hass)
    assert manager.reminder_open(TRACKER_A) is True
    anchor = manager._trackers[TRACKER_A].anchor

    await answer(hass, ANSWER_NO)

    assert manager.reminder_open(TRACKER_A) is False
    # The reminder went first, with the switch-off; the answer followed it.
    assert last_event(hass)[ATTR_EVENT_TYPE] == EVENT_LEFT_BEHIND_ANSWERED_NO
    assert anchor is not None

    await unload(hass, entry)


async def test_yes_leaves_the_reminder_anchor_alone(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """ "Home right now" says nothing about how long somebody has been home."""
    entry = await ask(hass, freezer)
    manager = entry.runtime_data.manager
    anchor = manager._trackers[TRACKER_A].anchor

    await answer(hass, ANSWER_YES)

    assert manager._trackers[TRACKER_A].anchor == anchor

    await unload(hass, entry)


async def test_a_reminder_is_withdrawn_by_an_expiry(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The switch-off of an unanswered question withdraws an open reminder."""
    entry = await ask(hass, freezer)
    manager = entry.runtime_data.manager
    reminders: list[str] = []
    manager.async_add_reminder_listener(
        TRACKER_A, lambda event_type, data: reminders.append(event_type)
    )
    manager.async_open_reminder(TRACKER_A)

    await tick(hass, freezer, 10 * MINUTE)

    assert reminders[-1] == EVENT_REMINDER_CANCELLED
    assert manager.is_home(TRACKER_A) is False

    await unload(hass, entry)


# --- After a restart ------------------------------------------------------------------


def stored(
    tracker: dict[str, Any], left_behind: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Return a storage payload with the first tracker as given."""
    data: dict[str, Any] = {"trackers": {TRACKER_A: tracker}}
    if left_behind is not None:
        data["left_behind"] = {TRACKER_A: left_behind}
    return {
        "version": STORAGE_VERSION,
        "minor_version": 1,
        "key": STORE_KEY,
        "data": data,
    }


def at_home(**extra: Any) -> dict[str, Any]:
    """Return a stored tracker that is on."""
    since = (dt_util.utcnow() - timedelta(hours=1)).isoformat()
    return {"home": True, "since": since, "anchor": since, **extra}


def open_question(minutes_left: float, manual: bool = False) -> dict[str, Any]:
    """Return a stored open question with the given time left."""
    now = dt_util.utcnow()
    return {
        "left_behind_id": "abc",
        "started_at": (now - timedelta(minutes=5)).isoformat(),
        "expires_at": (now + timedelta(minutes=minutes_left)).isoformat(),
        "manual": manual,
    }


async def test_an_expiry_while_home_assistant_was_down_switches_off(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """Home Assistant being down vouches for nobody: off, locked, notice."""
    calls = add_phone(hass)
    set_person_state(hass, STATE_NOT_HOME)
    set_tablet_state(hass, STATE_HOME)
    hass_storage[STORE_KEY] = stored(at_home(), open_question(-1))

    entry = await setup_entry(hass, left_behind_entry(**{CONF_NOTIFY_ON_EXPIRY: True}))
    manager = entry.runtime_data.manager

    assert manager.is_home(TRACKER_A) is False
    assert manager.source_locked(TRACKER_A) is True
    assert last_event(hass)[ATTR_EVENT_TYPE] == EVENT_LEFT_BEHIND_EXPIRED
    assert last_event(hass)[ATTR_LEFT_BEHIND_ID] == "abc"
    assert [call.data["message"] for call in calls] == [
        "clear_notification",
        "No answer: Kid has been switched off.",
    ]

    await unload(hass, entry)


async def test_an_open_question_keeps_the_time_it_has_left(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_storage: dict[str, Any]
) -> None:
    """Still open after a restart, and it says nothing new."""
    set_person_state(hass, STATE_NOT_HOME)
    set_tablet_state(hass, STATE_HOME)
    hass_storage[STORE_KEY] = stored(at_home(), open_question(4))

    entry = await setup_entry(hass, left_behind_entry())
    manager = entry.runtime_data.manager

    assert manager.left_behind_open(TRACKER_A) is True
    assert hass.states.get(EVENT_A).attributes.get(ATTR_EVENT_TYPE) is None
    await tick(hass, freezer, 4 * MINUTE)
    assert manager.is_home(TRACKER_A) is False

    await unload(hass, entry)


async def test_a_real_person_at_home_after_a_restart_withdraws_it(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """The prompt's catch-up rule; one opened by hand would stay."""
    set_person_state(hass, STATE_HOME)
    set_tablet_state(hass, STATE_HOME)
    hass_storage[STORE_KEY] = stored(at_home(), open_question(4))

    entry = await setup_entry(hass, left_behind_entry())

    assert last_event(hass)[ATTR_EVENT_TYPE] == EVENT_LEFT_BEHIND_CANCELLED
    assert last_event(hass)[ATTR_REASON] == REASON_PERSON_HOME

    await unload(hass, entry)


async def test_a_restart_during_the_wait_decides_after_away_after(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_storage: dict[str, Any]
) -> None:
    """The decision waits until the sources have been followed for `away_after`."""
    set_person_state(hass, STATE_NOT_HOME)
    set_tablet_state(hass, STATE_HOME)
    waiting = (dt_util.utcnow() - timedelta(minutes=30)).isoformat()
    hass_storage[STORE_KEY] = stored(at_home(left_behind_wait_since=waiting))

    entry = await setup_entry(hass, left_behind_entry())
    events = Recorder(entry)

    await tick(hass, freezer, 10 * MINUTE - 1)
    assert events.types == []
    await tick(hass, freezer, 1)
    assert events.types == [EVENT_LEFT_BEHIND_STARTED]

    await answer(hass, ANSWER_YES)
    await unload(hass, entry)


async def test_a_real_person_at_home_after_a_restart_ends_the_period(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_storage: dict[str, Any]
) -> None:
    """No waiting mark and no lock survive an occupied house."""
    set_person_state(hass, STATE_HOME)
    set_tablet_state(hass, STATE_HOME)
    waiting = (dt_util.utcnow() - timedelta(minutes=30)).isoformat()
    hass_storage[STORE_KEY] = stored(
        {
            "home": False,
            "since": None,
            "left_behind_wait_since": waiting,
            "source_lock": True,
        }
    )

    entry = await setup_entry(hass, left_behind_entry())
    events = Recorder(entry)

    assert entry.runtime_data.manager.source_locked(TRACKER_A) is False
    await tick(hass, freezer, 30 * MINUTE)
    assert events.types == []

    await unload(hass, entry)


# --- Actions ------------------------------------------------------------------------


async def test_it_can_be_opened_by_hand(hass: HomeAssistant) -> None:
    """Whoever is at home, whatever the option says."""
    set_person_state(hass, STATE_HOME)
    set_tablet_state(hass, STATE_HOME)
    entry = await setup_entry(hass, left_behind_entry(**{CONF_ASK_LEFT_BEHIND: False}))
    entry.runtime_data.manager.async_set_home(TRACKER_A, True)

    await hass.services.async_call(
        DOMAIN, SERVICE_OPEN_LEFT_BEHIND, {ATTR_ENTITY_ID: SWITCH_A}, blocking=True
    )
    await settle(hass)

    assert last_event(hass)[ATTR_EVENT_TYPE] == EVENT_LEFT_BEHIND_STARTED
    assert last_event(hass)[ATTR_SOURCES] == [TABLET]

    await answer(hass, ANSWER_YES)
    await unload(hass, entry)


@pytest.mark.parametrize(
    ("tracker_on", "sources", "already_open", "error"),
    [
        (False, [TABLET], False, "tracker_not_home"),
        (True, [], False, "no_presence_sources"),
        (True, [TABLET], True, "left_behind_already_open"),
    ],
)
async def test_opening_by_hand_is_refused(
    hass: HomeAssistant,
    tracker_on: bool,
    sources: list[str],
    already_open: bool,
    error: str,
) -> None:
    """Off, without sources or already asked: refused, and nothing changes."""
    set_person_state(hass, STATE_HOME)
    set_tablet_state(hass, STATE_HOME)
    entry = await setup_entry(hass, left_behind_entry(sources=sources))
    manager = entry.runtime_data.manager
    if tracker_on:
        manager.async_set_home(TRACKER_A, True)
    if already_open:
        manager.async_open_left_behind(TRACKER_A)
    await settle(hass)
    before = last_event(hass).get(ATTR_LEFT_BEHIND_ID)

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN, SERVICE_OPEN_LEFT_BEHIND, {ATTR_ENTITY_ID: SWITCH_A}, blocking=True
        )

    assert err.value.translation_key == error
    assert last_event(hass).get(ATTR_LEFT_BEHIND_ID) == before
    assert manager.is_home(TRACKER_A) is tracker_on

    if already_open:
        await answer(hass, ANSWER_YES)
    await unload(hass, entry)


async def test_answering_without_a_question_is_refused(hass: HomeAssistant) -> None:
    """A late answer must not switch anything off."""
    set_tablet_state(hass, STATE_HOME)
    entry = await setup_entry(hass, left_behind_entry())
    entry.runtime_data.manager.async_set_home(TRACKER_A, True)

    with pytest.raises(ServiceValidationError) as err:
        await answer(hass, ANSWER_NO)

    assert err.value.translation_key == "no_open_left_behind"
    assert entry.runtime_data.manager.is_home(TRACKER_A) is True

    await unload(hass, entry)


@pytest.mark.parametrize("entity_id", [ASK_A, DND_A])
@pytest.mark.parametrize(
    ("service", "data"),
    [
        (SERVICE_ANSWER_LEFT_BEHIND, {ATTR_ANSWER: ANSWER_YES}),
        (SERVICE_OPEN_LEFT_BEHIND, {}),
    ],
)
async def test_a_settings_switch_is_not_a_target(
    hass: HomeAssistant, entity_id: str, service: str, data: dict[str, Any]
) -> None:
    """The new settings switches say what to target instead."""
    entry = await setup_entry(hass, left_behind_entry())

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN, service, {ATTR_ENTITY_ID: entity_id, **data}, blocking=True
        )

    assert err.value.translation_key == "not_a_tracker_switch"

    await unload(hass, entry)


# --- The settings ------------------------------------------------------------------


async def test_the_two_settings_are_configuration_switches(
    hass: HomeAssistant,
) -> None:
    """Off for a tracker without the keys, on the device page under Configuration."""
    entry = await setup_entry(hass, make_entry(make_subentry(TRACKER_A, "Kid")))
    registry = er.async_get(hass)

    for entity_id, key in (
        (ASK_A, CONF_ASK_LEFT_BEHIND),
        (DND_A, CONF_LEFT_BEHIND_OVERRIDE_DND),
    ):
        assert hass.states.get(entity_id).state == STATE_OFF
        registered = registry.async_get(entity_id)
        assert registered.entity_category is EntityCategory.CONFIG
        assert registered.unique_id == f"{TRACKER_A}_{key}"

    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: DND_A}, blocking=True
    )
    assert entry.subentries[TRACKER_A].data[CONF_LEFT_BEHIND_OVERRIDE_DND] is True

    await unload(hass, entry)


async def test_a_recipient_without_a_phone_is_reported(hass: HomeAssistant) -> None:
    """A tracker that only asks about devices still sends to its recipients."""
    set_person_state(hass, STATE_HOME)
    entry = await setup_entry(hass, left_behind_entry())
    await hass.async_block_till_done()

    reported = f"{ENTRY_ID}_{ISSUE_RECIPIENT_WITHOUT_PHONE}_{PERSON_A}"
    assert ir.async_get(hass).async_get_issue(DOMAIN, reported) is not None

    await unload(hass, entry)


# --- The message on the phone ----------------------------------------------------------


async def test_the_question_is_sent_to_the_phone(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Named devices, its own tag and buttons, the prompt's answer time."""
    calls = add_phone(hass)
    await ask(hass, freezer)
    left_behind_id = last_event(hass)[ATTR_LEFT_BEHIND_ID]

    assert calls[0].data == {
        "title": "Device left behind?",
        "message": "Nobody else is home, but Xiaomi Tablet is. Is Kid home? "
        "Without an answer within 10 minutes, Kid is switched off.",
        "data": {
            "tag": f"vpt_left_behind_{left_behind_id}",
            "actions": [
                {
                    "action": f"VPT_LEFT_BEHIND_YES_{left_behind_id}",
                    "title": "Yes, home",
                },
                {
                    "action": f"VPT_LEFT_BEHIND_NO_{left_behind_id}",
                    "title": "No, switch off",
                },
            ],
            "ttl": 0,
            "priority": "high",
            "timeout": 600,
            "push": {"interruption-level": "time-sensitive"},
            "icon_url": NOTIFICATION_ICON,
            "group": GROUP_KID,
        },
    }

    await answer(hass, ANSWER_YES)
    assert calls[-1].data == {
        "message": "clear_notification",
        "data": {"tag": f"vpt_left_behind_{left_behind_id}"},
    }


async def test_its_own_switch_makes_it_loud(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The M3c technique, through a switch of its own."""
    calls = add_phone(hass)
    await ask(hass, freezer, left_behind_entry(**{CONF_LEFT_BEHIND_OVERRIDE_DND: True}))

    data = calls[0].data["data"]
    assert data["push"] == {
        "interruption-level": "critical",
        "sound": {"name": "default", "critical": 1},
    }
    assert data["channel"] == "alarm_stream"

    await answer(hass, ANSWER_YES)


async def test_the_prompt_switch_does_not_make_it_loud(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The prompt's override is the prompt's alone."""
    calls = add_phone(hass)
    await ask(hass, freezer, left_behind_entry(**{CONF_OVERRIDE_DND: True}))

    data = calls[0].data["data"]
    assert data["push"] == {"interruption-level": "time-sensitive"}
    assert "channel" not in data

    await answer(hass, ANSWER_YES)


async def test_without_a_present_source_the_message_speaks_of_a_device(
    hass: HomeAssistant,
) -> None:
    """Opened by hand while the tablet is away: the generic text."""
    calls = add_phone(hass)
    set_person_state(hass, STATE_HOME)
    set_tablet_state(hass, STATE_NOT_HOME)
    entry = await setup_entry(hass, left_behind_entry())
    entry.runtime_data.manager.async_set_home(TRACKER_A, True)

    entry.runtime_data.manager.async_open_left_behind(TRACKER_A)
    await settle(hass)

    assert last_event(hass)[ATTR_SOURCES] == []
    assert calls[0].data["message"] == (
        "Nobody else is home, but a device of Kid is. Is Kid home? "
        "Without an answer within 10 minutes, Kid is switched off."
    )

    await answer(hass, ANSWER_YES)
    await unload(hass, entry)


async def test_an_answer_from_the_phone_answers_it(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The "no" button switches off, and names the person behind the phone."""
    add_phone(hass)
    entry = await ask(hass, freezer)
    left_behind_id = last_event(hass)[ATTR_LEFT_BEHIND_ID]

    hass.bus.async_fire(
        EVENT_NOTIFICATION_ACTION,
        {"action": f"VPT_LEFT_BEHIND_NO_{left_behind_id}"},
        context=Context(user_id=USER_A),
    )
    await settle(hass)

    assert entry.runtime_data.manager.is_home(TRACKER_A) is False
    assert last_event(hass)[ATTR_EVENT_TYPE] == EVENT_LEFT_BEHIND_ANSWERED_NO
    assert last_event(hass)[ATTR_ANSWERED_BY] == PERSON_A

    await unload(hass, entry)


async def test_a_prompt_button_never_answers_it(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The prefixes are kept apart: `VPT_NO_<id>` is not this question's "no"."""
    entry = await ask(hass, freezer)
    left_behind_id = last_event(hass)[ATTR_LEFT_BEHIND_ID]

    for action in (f"VPT_NO_{left_behind_id}", f"VPT_REMIND_NO_{left_behind_id}"):
        hass.bus.async_fire(EVENT_NOTIFICATION_ACTION, {"action": action})
        await settle(hass)

    assert entry.runtime_data.manager.left_behind_open(TRACKER_A) is True

    await answer(hass, ANSWER_YES)
    await unload(hass, entry)


async def test_the_question_is_sent_in_german(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The language of the instance picks the texts."""
    hass.config.language = "de"
    calls = add_phone(hass)
    await ask(hass, freezer)

    assert calls[0].data["title"] == "Gerät zurückgelassen?"
    assert calls[0].data["message"] == (
        "Es ist niemand sonst zu Hause, aber Xiaomi Tablet ist noch da. Ist Kid "
        "zu Hause? Ohne Antwort innerhalb von 10 Minuten wird Kid ausgeschaltet."
    )

    await answer(hass, ANSWER_YES)


def test_every_language_has_every_text() -> None:
    """A missing key would be a KeyError on the phone, not an English fallback."""
    english = set(_TEXTS["en"])
    for language, texts in _TEXTS.items():
        assert set(texts) == english, language


@pytest.mark.parametrize("language", ["en", "de", "fr", "es"])
@pytest.mark.parametrize(
    "devices", [[], ["Tablet"], ["Tablet", "Tag"], ["Tablet", "Tag", "Watch"]]
)
async def test_the_message_names_the_devices(
    hass: HomeAssistant, language: str, devices: list[str]
) -> None:
    """One, two, three or no devices, in every language."""
    hass.config.language = language

    message = async_left_behind_message(hass, "Kid", devices, 1)

    for device in devices:
        assert device in message
    assert "Kid" in message
    assert "{" not in message
    if len(devices) == 3:
        assert message.count(",") >= 1


def test_the_message_in_english_and_german() -> None:
    """The verb follows the number of devices, and one minute reads as one."""

    class _Config:
        language = "en"

    class _Hass:
        config = _Config()

    hass: Any = _Hass()
    assert async_left_behind_message(hass, "Kid", ["Tablet", "Tag"], 1) == (
        "Nobody else is home, but Tablet and Tag are. Is Kid home? "
        "Without an answer within 1 minute, Kid is switched off."
    )
    hass.config.language = "de"
    assert async_left_behind_message(hass, "Kid", ["A", "B", "C"], 5) == (
        "Es ist niemand sonst zu Hause, aber A, B und C sind noch da. Ist Kid zu "
        "Hause? Ohne Antwort innerhalb von 5 Minuten wird Kid ausgeschaltet."
    )
