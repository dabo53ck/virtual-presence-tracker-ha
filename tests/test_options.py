"""Tests for the per-tracker options (M2f, split in M3g).

The options keep living in the data of the tracker's config subentry. Five of
them have a switch on the tracker's device page; the timings and the expiry
notice are set in the tracker's form (M3g) and written straight into the
subentry. Writing one must not reload the config entry either way: a reload
takes the device tracker and its person away for a moment, which looks like
somebody leaving and coming back.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.virtual_presence_tracker.const import (
    ATTR_PROMPT_OPEN,
    ATTR_REASON,
    ATTR_USER_ID,
    CONF_ANSWER_TIMEOUT,
    CONF_ASK_LEFT_BEHIND,
    CONF_ASK_ON_DEPARTURE,
    CONF_AWAY_AFTER,
    CONF_DEVICE_NAME,
    CONF_LEFT_BEHIND_OVERRIDE_DND,
    CONF_NOTIFY_ON_EXPIRY,
    CONF_NOTIFY_PERSONS,
    CONF_OVERRIDE_DND,
    CONF_PROMPT_DELAY,
    CONF_REMIND_AFTER,
    CONF_REMINDER_TIMEOUT,
    CONF_RESET_ON_RETURN,
    CONF_USER_ID,
    DEFAULT_ANSWER_TIMEOUT,
    DEFAULT_AWAY_AFTER,
    DEFAULT_PROMPT_DELAY,
    DEFAULT_REMIND_AFTER,
    DEFAULT_REMINDER_TIMEOUT,
    DOMAIN,
    EVENT_CANCELLED,
    EVENT_PROMPT_STARTED,
    EVENT_REMINDER_CANCELLED,
    EVENT_REMINDER_STARTED,
    MOBILE_APP_DOMAIN,
    NOTIFY_DOMAIN,
    REASON_OPTION_DISABLED,
    SERVICE_OPEN_PROMPT,
    SERVICE_OPEN_REMINDER,
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
    EVENT_STATE_CHANGED,
    STATE_HOME,
    STATE_NOT_HOME,
    STATE_OFF,
    STATE_ON,
    EntityCategory,
)
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .conftest import PERSON_A, TRACKER_A, TRACKER_B, make_entry, make_subentry

ASK_A = "switch.kid_ask_when_empty"
RESET_A = "switch.kid_reset_on_return"
DND_A = "switch.kid_override_do_not_disturb_for_the_prompt"
LEFT_BEHIND_A = "switch.kid_ask_about_a_device_left_behind"
LEFT_BEHIND_DND_A = "switch.kid_override_do_not_disturb_for_a_device_left_behind"

SWITCH_A = "switch.kid_at_home"
TRACKER_A_ENTITY = "device_tracker.kid"
EVENT_A = "event.kid_questions"
SENSOR = "binary_sensor.only_virtual_trackers_home"

# The entities of a tracker that a reload would take away for a moment.
WATCHED = (TRACKER_A_ENTITY, SWITCH_A, SENSOR)

USER_A = "user-dabo53ck"
PHONE_A = "mobile_app_dabo53ck_s_phone"


class Watcher:
    """Record the state *changes* of the given entities.

    An entity that writes the state it already has reports it instead of
    changing it, so an empty record means nothing happened to these entities -
    which is exactly what "no reload" has to look like.
    """

    def __init__(self, hass: HomeAssistant, entity_ids: tuple[str, ...]) -> None:
        """Listen for the state changes of the given entities."""
        self.changes: list[str] = []
        self._entity_ids = entity_ids
        hass.bus.async_listen(EVENT_STATE_CHANGED, self._record)

    def _record(self, event: Event[Any]) -> None:
        """Remember one state change."""
        if event.data["entity_id"] in self._entity_ids:
            self.changes.append(event.data["entity_id"])


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> MockConfigEntry:
    """Add a config entry to hass and set it up."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def unload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Unload an entry, so that no prompt timer is left running."""
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def turn(hass: HomeAssistant, entity_id: str, on: bool) -> None:
    """Switch one of the option switches on or off."""
    await hass.services.async_call(
        SWITCH_DOMAIN,
        SERVICE_TURN_ON if on else SERVICE_TURN_OFF,
        {ATTR_ENTITY_ID: entity_id},
        blocking=True,
    )
    await hass.async_block_till_done()


async def write(hass: HomeAssistant, entry: MockConfigEntry, **values: Any) -> None:
    """Write options of the first tracker the way its form does (M3g)."""
    subentry = entry.subentries[TRACKER_A]
    hass.config_entries.async_update_subentry(
        entry, subentry, data={**subentry.data, **values}
    )
    await hass.async_block_till_done()


async def set_person(hass: HomeAssistant, state: str) -> None:
    """Move the one real person of the household."""
    hass.states.async_set(PERSON_A, state, {ATTR_USER_ID: USER_A})
    await hass.async_block_till_done(wait_background_tasks=True)


async def ask(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Set the entry up with the person at home and then empty the house."""
    await set_person(hass, STATE_HOME)
    await setup_entry(hass, entry)
    await set_person(hass, STATE_NOT_HOME)
    assert entry.runtime_data.manager.prompt_open(TRACKER_A) is True


def asking_entry(**overrides: Any) -> MockConfigEntry:
    """Return an entry whose first tracker asks when the house empties."""
    return make_entry(
        make_subentry(TRACKER_A, "Kid", **{CONF_ASK_ON_DEPARTURE: True, **overrides}),
        make_subentry(TRACKER_B, "Granny"),
    )


def add_phone(hass: HomeAssistant) -> list[Any]:
    """Register a Companion App phone for the real person and mock its service."""
    MockConfigEntry(
        domain=MOBILE_APP_DOMAIN,
        title="dabo53ck's Phone",
        data={CONF_DEVICE_NAME: "dabo53ck's Phone", CONF_USER_ID: USER_A},
    ).add_to_hass(hass)
    return async_mock_service(hass, NOTIFY_DOMAIN, PHONE_A)


async def test_every_tracker_gets_the_option_switches(
    hass: HomeAssistant, tracker_entry: MockConfigEntry
) -> None:
    """Five switches per tracker, on the tracker's own device, all settings.

    The timings and the expiry notice have no entity any more (M3g): they are
    set in the tracker's form.
    """
    await setup_entry(hass, tracker_entry)

    registry = er.async_get(hass)
    expected = {
        ASK_A: CONF_ASK_ON_DEPARTURE,
        RESET_A: CONF_RESET_ON_RETURN,
        DND_A: CONF_OVERRIDE_DND,
        LEFT_BEHIND_A: CONF_ASK_LEFT_BEHIND,
        LEFT_BEHIND_DND_A: CONF_LEFT_BEHIND_OVERRIDE_DND,
    }
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, TRACKER_A), tracker_entry.entry_id
    )
    assert device is not None

    for entity_id, key in expected.items():
        entity_entry = registry.async_get(entity_id)
        assert entity_entry is not None, entity_id
        assert entity_entry.unique_id == f"{TRACKER_A}_{key}"
        assert entity_entry.entity_category is EntityCategory.CONFIG
        assert entity_entry.config_subentry_id == TRACKER_A
        assert entity_entry.device_id == device.id

    # Next to them only the tracker's own switch and its questions entity.
    on_device = {
        entity.entity_id for entity in er.async_entries_for_device(registry, device.id)
    }
    assert on_device == {*expected, SWITCH_A, EVENT_A}
    assert not [
        entity
        for entity in er.async_entries_for_config_entry(
            registry, tracker_entry.entry_id
        )
        if entity.domain == "number"
    ]

    # The second tracker has its own set, and the tracker's name is in front.
    assert registry.async_get("switch.granny_ask_when_empty") is not None
    assert hass.states.get(ASK_A).attributes[ATTR_FRIENDLY_NAME] == "Kid Ask when empty"


async def test_an_old_tracker_shows_the_defaults_of_a_missing_key(
    hass: HomeAssistant, tracker_entry: MockConfigEntry
) -> None:
    """A tracker from before these options shows what it behaves like.

    Above all the ask switch is off and the reminder is at zero: a subentry
    without those keys never asked and never reminded, and it must not start
    doing either because it grew an entity.
    """
    await setup_entry(hass, tracker_entry)
    manager = tracker_entry.runtime_data.manager

    assert hass.states.get(ASK_A).state == STATE_OFF
    assert hass.states.get(RESET_A).state == STATE_ON
    # Loud enough to get through a silenced phone is opt-in, never a default.
    assert hass.states.get(DND_A).state == STATE_OFF
    assert hass.states.get(LEFT_BEHIND_A).state == STATE_OFF
    assert hass.states.get(LEFT_BEHIND_DND_A).state == STATE_OFF
    # The options of the form apply their defaults just the same.
    assert manager.option(TRACKER_A, CONF_NOTIFY_ON_EXPIRY) is False
    assert manager.option(TRACKER_A, CONF_ANSWER_TIMEOUT) == DEFAULT_ANSWER_TIMEOUT
    assert manager.option(TRACKER_A, CONF_PROMPT_DELAY) == DEFAULT_PROMPT_DELAY
    assert manager.option(TRACKER_A, CONF_REMIND_AFTER) == DEFAULT_REMIND_AFTER == 0
    assert manager.option(TRACKER_A, CONF_REMINDER_TIMEOUT) == (
        DEFAULT_REMINDER_TIMEOUT
    )
    assert manager.option(TRACKER_A, CONF_AWAY_AFTER) == DEFAULT_AWAY_AFTER == 10
    # Nothing was written to the subentry by showing it.
    assert dict(tracker_entry.subentries[TRACKER_A].data) == {}


async def test_the_entities_show_what_the_tracker_has_stored(
    hass: HomeAssistant,
) -> None:
    """Every entity reports the value of its own tracker."""
    await setup_entry(
        hass,
        make_entry(
            make_subentry(
                TRACKER_A,
                "Kid",
                **{
                    CONF_ASK_ON_DEPARTURE: True,
                    CONF_RESET_ON_RETURN: False,
                    CONF_OVERRIDE_DND: True,
                    CONF_ASK_LEFT_BEHIND: True,
                    CONF_LEFT_BEHIND_OVERRIDE_DND: True,
                },
            ),
            make_subentry(TRACKER_B, "Granny"),
        ),
    )

    assert hass.states.get(ASK_A).state == STATE_ON
    assert hass.states.get(RESET_A).state == STATE_OFF
    assert hass.states.get(DND_A).state == STATE_ON
    assert hass.states.get(LEFT_BEHIND_A).state == STATE_ON
    assert hass.states.get(LEFT_BEHIND_DND_A).state == STATE_ON
    # The other tracker is untouched by it.
    assert hass.states.get("switch.granny_ask_when_empty").state == STATE_OFF


@pytest.mark.parametrize(
    ("entity_id", "key"),
    [
        (ASK_A, CONF_ASK_ON_DEPARTURE),
        (RESET_A, CONF_RESET_ON_RETURN),
        (DND_A, CONF_OVERRIDE_DND),
        (LEFT_BEHIND_A, CONF_ASK_LEFT_BEHIND),
        (LEFT_BEHIND_DND_A, CONF_LEFT_BEHIND_OVERRIDE_DND),
    ],
)
async def test_a_switch_writes_its_option(
    hass: HomeAssistant, tracker_entry: MockConfigEntry, entity_id: str, key: str
) -> None:
    """Switching writes the subentry data and shows the new value at once."""
    await setup_entry(hass, tracker_entry)

    await turn(hass, entity_id, True)

    assert tracker_entry.subentries[TRACKER_A].data[key] is True
    assert hass.states.get(entity_id).state == STATE_ON

    await turn(hass, entity_id, False)

    assert tracker_entry.subentries[TRACKER_A].data[key] is False
    assert hass.states.get(entity_id).state == STATE_OFF
    # The tracker of the other subentry is not written to.
    assert dict(tracker_entry.subentries[TRACKER_B].data) == {}


async def test_the_new_value_is_there_when_the_action_returns(
    hass: HomeAssistant, tracker_entry: MockConfigEntry
) -> None:
    """Nothing has to settle first: the entity is written on the way.

    Home Assistant hands a subentry change to the update listeners as a task,
    so waiting for that would show the old value for a moment - long enough to
    look like a switch that did not take.
    """
    await setup_entry(hass, tracker_entry)

    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: ASK_A}, blocking=True
    )

    assert hass.states.get(ASK_A).state == STATE_ON

    await hass.async_block_till_done()


async def test_changing_an_option_does_not_reload_the_entry(
    hass: HomeAssistant, tracker_entry: MockConfigEntry
) -> None:
    """The tracker and its person stay exactly where they are.

    This is the point of the whole milestone: a reload would take the device
    tracker to `unavailable` and back, and an automation that waits for
    somebody to come home cannot tell that apart from an arrival.
    """
    await setup_entry(hass, tracker_entry)
    manager = tracker_entry.runtime_data.manager
    await turn(hass, SWITCH_A, True)

    watcher = Watcher(hass, WATCHED)
    for entity_id in (ASK_A, RESET_A, DND_A, LEFT_BEHIND_A, LEFT_BEHIND_DND_A):
        await turn(hass, entity_id, True)
    # And the options of the form, written the way the form writes them.
    await write(
        hass,
        tracker_entry,
        **{
            CONF_NOTIFY_ON_EXPIRY: True,
            CONF_ANSWER_TIMEOUT: 30,
            CONF_PROMPT_DELAY: 5,
            CONF_REMIND_AFTER: 48,
            CONF_REMINDER_TIMEOUT: 90,
            CONF_AWAY_AFTER: 20,
        },
    )

    assert watcher.changes == []
    # The same manager, so nothing was rebuilt behind the entities either.
    assert tracker_entry.runtime_data.manager is manager
    assert hass.states.get(TRACKER_A_ENTITY).state == STATE_HOME
    assert hass.states.get(SWITCH_A).state == STATE_ON
    # And the values did arrive.
    assert manager.option(TRACKER_A, CONF_ANSWER_TIMEOUT) == 30
    assert manager.option(TRACKER_A, CONF_PROMPT_DELAY) == 5
    assert manager.option(TRACKER_A, CONF_REMIND_AFTER) == 48
    assert manager.option(TRACKER_A, CONF_REMINDER_TIMEOUT) == 90
    assert manager.option(TRACKER_A, CONF_AWAY_AFTER) == 20
    assert manager.option(TRACKER_A, CONF_NOTIFY_ON_EXPIRY) is True
    assert manager.option(TRACKER_A, CONF_OVERRIDE_DND) is True
    assert manager.option(TRACKER_A, CONF_LEFT_BEHIND_OVERRIDE_DND) is True

    await unload(hass, tracker_entry)


async def test_renaming_a_tracker_still_reloads_the_entry(
    hass: HomeAssistant, tracker_entry: MockConfigEntry
) -> None:
    """A change that is not one of the settings options is a reload as before."""
    await setup_entry(hass, tracker_entry)
    manager = tracker_entry.runtime_data.manager

    hass.config_entries.async_update_subentry(
        tracker_entry, tracker_entry.subentries[TRACKER_A], title="Teenager"
    )
    await hass.async_block_till_done()

    assert tracker_entry.runtime_data.manager is not manager


async def test_changing_the_recipients_still_reloads_the_entry(
    hass: HomeAssistant, tracker_entry: MockConfigEntry
) -> None:
    """Who is asked is read when the entry is set up, so it reloads."""
    await setup_entry(hass, tracker_entry)
    manager = tracker_entry.runtime_data.manager
    subentry = tracker_entry.subentries[TRACKER_A]

    hass.config_entries.async_update_subentry(
        tracker_entry,
        subentry,
        data={**subentry.data, CONF_NOTIFY_PERSONS: [PERSON_A]},
    )
    await hass.async_block_till_done()

    assert tracker_entry.runtime_data.manager is not manager


async def test_changing_the_real_persons_still_reloads_the_entry(
    hass: HomeAssistant, tracker_entry: MockConfigEntry
) -> None:
    """The manager watches the persons, so a change of them rebuilds it."""
    await setup_entry(hass, tracker_entry)
    manager = tracker_entry.runtime_data.manager

    hass.config_entries.async_update_entry(
        tracker_entry,
        data={**tracker_entry.data, "persons": [PERSON_A, "person.king53ck"]},
    )
    await hass.async_block_till_done()

    assert tracker_entry.runtime_data.manager is not manager


async def test_switching_ask_off_takes_an_open_prompt_back(
    hass: HomeAssistant,
) -> None:
    """The question goes away the moment the tracker stops asking."""
    entry = asking_entry(**{CONF_NOTIFY_PERSONS: [PERSON_A]})
    calls = add_phone(hass)
    await ask(hass, entry)
    assert len(calls) == 1

    await turn(hass, ASK_A, False)
    await hass.async_block_till_done(wait_background_tasks=True)

    state = hass.states.get(EVENT_A)
    assert state.attributes[ATTR_EVENT_TYPE] == EVENT_CANCELLED
    assert state.attributes[ATTR_REASON] == REASON_OPTION_DISABLED
    assert entry.runtime_data.manager.prompt_open(TRACKER_A) is False
    assert hass.states.get(SWITCH_A).attributes[ATTR_PROMPT_OPEN] is False
    # The message is taken off the phone, as on every other ending.
    assert calls[1].data["message"] == "clear_notification"


async def test_switching_ask_off_drops_a_scheduled_prompt(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A prompt that is still waiting for its delay is taken back too."""
    entry = asking_entry(**{CONF_PROMPT_DELAY: 60})
    await set_person(hass, STATE_HOME)
    await setup_entry(hass, entry)
    await set_person(hass, STATE_NOT_HOME)
    assert entry.runtime_data.manager.prompt_open(TRACKER_A) is False

    await turn(hass, ASK_A, False)

    state = hass.states.get(EVENT_A)
    assert state.attributes[ATTR_EVENT_TYPE] == EVENT_CANCELLED
    assert state.attributes[ATTR_REASON] == REASON_OPTION_DISABLED

    # The timer of the dropped prompt has nothing left to open.
    freezer.tick(timedelta(seconds=61))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert entry.runtime_data.manager.prompt_open(TRACKER_A) is False


async def test_switching_ask_off_leaves_a_prompt_opened_by_hand(
    hass: HomeAssistant,
) -> None:
    """A prompt somebody opened themselves was never about the option."""
    entry = await setup_entry(hass, make_entry(make_subentry(TRACKER_A, "Kid")))
    await hass.services.async_call(
        DOMAIN, SERVICE_OPEN_PROMPT, {ATTR_ENTITY_ID: SWITCH_A}, blocking=True
    )
    await hass.async_block_till_done()

    # Switching the option on and off again while the manual prompt is open.
    await turn(hass, ASK_A, True)
    await turn(hass, ASK_A, False)

    assert entry.runtime_data.manager.prompt_open(TRACKER_A) is True
    assert hass.states.get(EVENT_A).attributes[ATTR_EVENT_TYPE] == EVENT_PROMPT_STARTED

    await unload(hass, entry)


async def test_switching_ask_on_makes_the_tracker_ask(hass: HomeAssistant) -> None:
    """A tracker that did not ask asks from the moment its switch is on."""
    entry = await setup_entry(hass, make_entry(make_subentry(TRACKER_A, "Kid")))
    await set_person(hass, STATE_HOME)

    await turn(hass, ASK_A, True)
    await set_person(hass, STATE_NOT_HOME)

    assert entry.runtime_data.manager.prompt_open(TRACKER_A) is True
    assert hass.states.get(EVENT_A).attributes[ATTR_EVENT_TYPE] == EVENT_PROMPT_STARTED

    await unload(hass, entry)


async def test_the_new_timeout_is_for_the_next_prompt(hass: HomeAssistant) -> None:
    """An open prompt keeps the deadline it was opened with."""
    entry = asking_entry()
    await ask(hass, entry)
    manager = entry.runtime_data.manager
    expires_at = manager.prompt_expires_at(TRACKER_A)

    await write(hass, entry, **{CONF_ANSWER_TIMEOUT: 60})

    assert manager.prompt_expires_at(TRACKER_A) == expires_at

    # The next prompt uses the new value.
    await turn(hass, SWITCH_A, True)
    await turn(hass, SWITCH_A, False)
    await hass.services.async_call(
        DOMAIN, SERVICE_OPEN_PROMPT, {ATTR_ENTITY_ID: SWITCH_A}, blocking=True
    )
    await hass.async_block_till_done()

    reopened = manager.prompt_expires_at(TRACKER_A)
    assert (reopened - expires_at) > timedelta(minutes=45)

    await unload(hass, entry)


async def test_the_reset_option_is_read_where_it_is_used(hass: HomeAssistant) -> None:
    """Switching the reset off keeps the tracker on when somebody comes home."""
    await setup_entry(hass, make_entry(make_subentry(TRACKER_A, "Kid")))
    await set_person(hass, STATE_NOT_HOME)
    await turn(hass, SWITCH_A, True)

    await turn(hass, RESET_A, False)
    await set_person(hass, STATE_HOME)

    assert hass.states.get(SWITCH_A).state == STATE_ON

    # And with the option back on the next arrival resets it.
    await set_person(hass, STATE_NOT_HOME)
    await turn(hass, RESET_A, True)
    await set_person(hass, STATE_HOME)

    assert hass.states.get(SWITCH_A).state == STATE_OFF


async def test_setting_the_reminder_to_zero_takes_an_open_one_back(
    hass: HomeAssistant,
) -> None:
    """Switching the reminder off withdraws the question it had started."""
    entry = await setup_entry(hass, make_entry(make_subentry(TRACKER_A, "Kid")))
    await set_person(hass, STATE_NOT_HOME)
    await turn(hass, SWITCH_A, True)
    await write(hass, entry, **{CONF_REMIND_AFTER: 2})

    await hass.services.async_call(
        DOMAIN, SERVICE_OPEN_REMINDER, {ATTR_ENTITY_ID: SWITCH_A}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(EVENT_A).attributes[ATTR_EVENT_TYPE] == (
        EVENT_REMINDER_STARTED
    )

    await write(hass, entry, **{CONF_REMIND_AFTER: 0})

    state = hass.states.get(EVENT_A)
    assert state.attributes[ATTR_EVENT_TYPE] == EVENT_REMINDER_CANCELLED
    assert state.attributes[ATTR_REASON] == REASON_OPTION_DISABLED
    assert entry.runtime_data.manager.reminder_open(TRACKER_A) is False
    # The tracker itself is untouched: nobody answered anything.
    assert hass.states.get(SWITCH_A).state == STATE_ON

    await unload(hass, entry)
