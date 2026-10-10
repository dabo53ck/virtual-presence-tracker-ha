"""Tests for the button sources of a tracker (M3d).

An `event` entity of any integration can switch a tracker: a set of its event
types means "home" (on), another means "away" (off), and every other type is
left alone. Switching goes down the same path as the tracker's own switch, a
restore or a device coming back is never a press, and changing the sources
moves the listener without reloading the entry.
"""

from __future__ import annotations

from itertools import count
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
import voluptuous as vol

from custom_components.virtual_presence_tracker.const import (
    ATTR_REASON,
    CONF_AWAY_AFTER,
    CONF_BUTTON_AWAY_TYPES,
    CONF_BUTTON_HOME_TYPES,
    CONF_BUTTON_SOURCES,
    CONF_CREATE_PERSON,
    CONF_NOTIFY_PERSONS,
    DEFAULT_AWAY_AFTER,
    EVENT_CANCELLED,
    EVENT_REMINDER_CANCELLED,
    REASON_SWITCHED_OFF,
    REASON_SWITCHED_ON,
    SECTION_SOURCES,
    SUBENTRY_TYPE_TRACKER,
)
from custom_components.virtual_presence_tracker.manager import OpenPromptResult
from homeassistant.components.event import ATTR_EVENT_TYPE, ATTR_EVENT_TYPES
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import (
    CONF_NAME,
    EVENT_STATE_CHANGED,
    STATE_HOME,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import Event, HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData, section
from homeassistant.helpers import entity_registry as er

from .conftest import TRACKER_A, TRACKER_B, make_entry, make_subentry

BUTTON = "event.shelly_blu_button1_5dc6_taste"
OTHER_BUTTON = "event.hallway_remote"
SHELLY_TYPES = [
    "press",
    "double_press",
    "triple_press",
    "long_press",
    "long_double_press",
    "long_triple_press",
    "hold_press",
]
HUE_TYPES = ["initial_press", "repeat", "short_release", "long_press", "long_release"]

SWITCH_A = "switch.kid_at_home"
SWITCH_B = "switch.granny_at_home"
TRACKER_A_ENTITY = "device_tracker.kid"
EVENT_A = "event.kid_questions"

_moments = count()


def button_data(
    sources: list[str] | None = None,
    home: list[str] | None = None,
    away: list[str] | None = None,
) -> dict[str, Any]:
    """Return the subentry data of a tracker with button sources."""
    return {
        CONF_BUTTON_SOURCES: sources if sources is not None else [BUTTON],
        CONF_BUTTON_HOME_TYPES: home if home is not None else ["press"],
        CONF_BUTTON_AWAY_TYPES: away if away is not None else ["long_press"],
    }


def button_entry(**data: Any) -> MockConfigEntry:
    """Return an entry whose first tracker follows the Shelly button."""
    return make_entry(
        make_subentry(TRACKER_A, "Kid", **(button_data() | data)),
        make_subentry(TRACKER_B, "Granny"),
    )


def set_button(
    hass: HomeAssistant,
    entity_id: str = BUTTON,
    event_type: str | None = "press",
    *,
    state: str | None = None,
    event_types: list[str] | None = None,
) -> None:
    """Write a state of a button's event entity.

    Without an explicit state the state is a fresh timestamp, which is what an
    event entity shows after every event - so two presses of the same type are
    still two state changes.
    """
    if state is None:
        moment = next(_moments)
        state = f"2026-10-01T10:{moment // 60 % 60:02d}:{moment % 60:02d}.000+00:00"
    attributes: dict[str, Any] = {
        ATTR_EVENT_TYPES: event_types if event_types is not None else SHELLY_TYPES
    }
    if event_type is not None:
        attributes[ATTR_EVENT_TYPE] = event_type
    hass.states.async_set(entity_id, state, attributes)


async def press(hass: HomeAssistant, event_type: str, entity_id: str = BUTTON) -> None:
    """Press a button: a new event of the given type."""
    set_button(hass, entity_id, event_type)
    await hass.async_block_till_done()


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> MockConfigEntry:
    """Add a config entry to hass and set it up, with the buttons known."""
    # The buttons have a last event already, as they do after a restart.
    set_button(hass, BUTTON, "press")
    set_button(hass, OTHER_BUTTON, "short_release", event_types=HUE_TYPES)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def unload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Unload an entry, so that no timer is left running."""
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


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


# --- The manager -----------------------------------------------------------


async def test_a_home_event_switches_the_tracker_on(hass: HomeAssistant) -> None:
    """A press that means "home" switches the tracker on, like its switch."""
    entry = await setup_entry(hass, button_entry())

    await press(hass, "press")

    assert hass.states.get(SWITCH_A).state == STATE_ON
    assert hass.states.get(TRACKER_A_ENTITY).state == STATE_HOME
    # The other tracker does not follow this button.
    assert hass.states.get(SWITCH_B).state == STATE_OFF
    assert entry.runtime_data.manager.is_home(TRACKER_A) is True


async def test_switching_on_by_button_withdraws_an_open_prompt(
    hass: HomeAssistant,
) -> None:
    """The prompt is cancelled with `switched_on`, as by the switch."""
    entry = await setup_entry(hass, button_entry())
    manager = entry.runtime_data.manager
    assert manager.async_open_prompt(TRACKER_A) is OpenPromptResult.OPENED
    await hass.async_block_till_done()

    await press(hass, "press")

    assert manager.prompt_open(TRACKER_A) is False
    state = hass.states.get(EVENT_A)
    assert state.attributes[ATTR_EVENT_TYPE] == EVENT_CANCELLED
    assert state.attributes[ATTR_REASON] == REASON_SWITCHED_ON
    assert manager.is_home(TRACKER_A) is True

    await unload(hass, entry)


async def test_an_away_event_switches_the_tracker_off(hass: HomeAssistant) -> None:
    """A press that means "away" switches the tracker off."""
    entry = await setup_entry(hass, button_entry())
    entry.runtime_data.manager.async_set_home(TRACKER_A, True)
    await hass.async_block_till_done()

    await press(hass, "long_press")

    assert hass.states.get(SWITCH_A).state == STATE_OFF
    assert entry.runtime_data.manager.is_home(TRACKER_A) is False


async def test_switching_off_by_button_withdraws_an_open_reminder(
    hass: HomeAssistant,
) -> None:
    """The reminder is cancelled with `switched_off`, as by the switch."""
    entry = await setup_entry(hass, button_entry())
    manager = entry.runtime_data.manager
    manager.async_set_home(TRACKER_A, True)
    manager.async_open_reminder(TRACKER_A)
    await hass.async_block_till_done()
    assert manager.reminder_open(TRACKER_A) is True

    await press(hass, "long_press")

    assert manager.reminder_open(TRACKER_A) is False
    state = hass.states.get(EVENT_A)
    assert state.attributes[ATTR_EVENT_TYPE] == EVENT_REMINDER_CANCELLED
    assert state.attributes[ATTR_REASON] == REASON_SWITCHED_OFF
    assert manager.is_home(TRACKER_A) is False

    await unload(hass, entry)


@pytest.mark.parametrize("event_type", ["double_press", "hold_press", "unheard_of"])
async def test_other_event_types_are_ignored(
    hass: HomeAssistant, event_type: str
) -> None:
    """A type in neither set stays free for the user's own automations."""
    entry = await setup_entry(hass, button_entry())
    manager = entry.runtime_data.manager

    await press(hass, event_type)
    assert manager.is_home(TRACKER_A) is False

    manager.async_set_home(TRACKER_A, True)
    await press(hass, event_type)
    assert manager.is_home(TRACKER_A) is True


async def test_an_event_that_changes_nothing_is_a_no_op(hass: HomeAssistant) -> None:
    """Home while on and away while off leave the tracker exactly as it is."""
    entry = await setup_entry(hass, button_entry())
    manager = entry.runtime_data.manager

    watcher = Watcher(hass, SWITCH_A, TRACKER_A_ENTITY)
    await press(hass, "long_press")
    assert watcher.changes == []
    assert manager.since(TRACKER_A) is None

    await press(hass, "press")
    since = manager.since(TRACKER_A)
    watcher.changes.clear()
    await press(hass, "press")
    assert watcher.changes == []
    assert manager.since(TRACKER_A) == since


async def test_an_event_out_of_unavailable_is_ignored(hass: HomeAssistant) -> None:
    """A device that comes back shows its last event again; that is no press."""
    entry = await setup_entry(hass, button_entry())
    set_button(hass, event_type=None, state=STATE_UNAVAILABLE)
    await hass.async_block_till_done()

    await press(hass, "press")

    assert entry.runtime_data.manager.is_home(TRACKER_A) is False

    # The next real press after that counts.
    await press(hass, "press")

    assert entry.runtime_data.manager.is_home(TRACKER_A) is True


async def test_the_first_press_of_a_new_button_counts(hass: HomeAssistant) -> None:
    """`unknown` is what a button shows before its first event, not a replay.

    The same rule as Home Assistant's own "event received" trigger: the first
    press of a button that was never pressed must switch.
    """
    entry = await setup_entry(hass, button_entry())
    set_button(hass, event_type=None, state=STATE_UNKNOWN)
    await hass.async_block_till_done()

    await press(hass, "press")

    assert entry.runtime_data.manager.is_home(TRACKER_A) is True


async def test_an_event_entity_that_appears_is_ignored(hass: HomeAssistant) -> None:
    """A restored event entity comes from no state at all; that is no press."""
    entry = await setup_entry(hass, button_entry())
    hass.states.async_remove(BUTTON)
    await hass.async_block_till_done()

    await press(hass, "press")

    assert entry.runtime_data.manager.is_home(TRACKER_A) is False


@pytest.mark.parametrize("state", [STATE_UNAVAILABLE, STATE_UNKNOWN])
async def test_an_event_entity_that_goes_away_is_ignored(
    hass: HomeAssistant, state: str
) -> None:
    """Going unavailable keeps the last event type; that is no press either."""
    entry = await setup_entry(hass, button_entry())
    entry.runtime_data.manager.async_set_home(TRACKER_A, True)
    await hass.async_block_till_done()

    set_button(hass, event_type="long_press", state=state)
    await hass.async_block_till_done()

    assert entry.runtime_data.manager.is_home(TRACKER_A) is True


async def test_an_attribute_update_is_no_press(hass: HomeAssistant) -> None:
    """Only a new event changes the state of an event entity."""
    entry = await setup_entry(hass, button_entry())
    current = hass.states.get(BUTTON).state

    set_button(hass, event_type="press", state=current, event_types=["press"])
    await hass.async_block_till_done()

    assert entry.runtime_data.manager.is_home(TRACKER_A) is False


async def test_an_event_without_a_type_is_no_press(hass: HomeAssistant) -> None:
    """A state without an event type cannot mean anything."""
    entry = await setup_entry(hass, button_entry())

    set_button(hass, event_type=None)
    await hass.async_block_till_done()

    assert entry.runtime_data.manager.is_home(TRACKER_A) is False


async def test_one_button_can_switch_two_trackers(hass: HomeAssistant) -> None:
    """Each tracker reads its own event types out of the same button."""
    entry = await setup_entry(
        hass,
        make_entry(
            make_subentry(TRACKER_A, "Kid", **button_data(away=[])),
            make_subentry(
                TRACKER_B, "Granny", **button_data(home=["double_press"], away=[])
            ),
        ),
    )
    manager = entry.runtime_data.manager

    await press(hass, "press")
    assert (manager.is_home(TRACKER_A), manager.is_home(TRACKER_B)) == (True, False)

    await press(hass, "double_press")
    assert (manager.is_home(TRACKER_A), manager.is_home(TRACKER_B)) == (True, True)


async def test_changing_the_buttons_does_not_reload_the_entry(
    hass: HomeAssistant,
) -> None:
    """New sources and new types apply at once, without a flicker."""
    entry = await setup_entry(hass, button_entry())
    manager = entry.runtime_data.manager
    subentry = entry.subentries[TRACKER_A]

    watcher = Watcher(hass, TRACKER_A_ENTITY, SWITCH_A)
    hass.config_entries.async_update_subentry(
        entry,
        subentry,
        data={
            **subentry.data,
            **button_data(
                sources=[OTHER_BUTTON], home=["short_release"], away=["long_release"]
            ),
        },
    )
    await hass.async_block_till_done()

    assert entry.runtime_data.manager is manager
    assert watcher.changes == []

    # The button that was taken out switches nothing any more ...
    await press(hass, "press")
    assert manager.is_home(TRACKER_A) is False

    # ... and the new one does, with its own types.
    await press(hass, "short_release", OTHER_BUTTON)
    assert manager.is_home(TRACKER_A) is True
    await press(hass, "long_release", OTHER_BUTTON)
    assert manager.is_home(TRACKER_A) is False


async def test_buttons_added_to_a_tracker_without_any(hass: HomeAssistant) -> None:
    """A tracker without sources gets them, and the listener starts, unreloaded."""
    entry = await setup_entry(hass, make_entry(make_subentry(TRACKER_A, "Kid")))
    manager = entry.runtime_data.manager

    await press(hass, "press")
    assert manager.is_home(TRACKER_A) is False

    subentry = entry.subentries[TRACKER_A]
    hass.config_entries.async_update_subentry(
        entry, subentry, data={**subentry.data, **button_data()}
    )
    await hass.async_block_till_done()
    assert entry.runtime_data.manager is manager

    await press(hass, "press")
    assert manager.is_home(TRACKER_A) is True


async def test_unloading_stops_following_the_buttons(hass: HomeAssistant) -> None:
    """An unloaded entry switches nothing, whatever is pressed."""
    entry = await setup_entry(hass, button_entry())
    manager = entry.runtime_data.manager

    await unload(hass, entry)
    await press(hass, "press")

    assert manager.is_home(TRACKER_A) is False


# --- The form ---------------------------------------------------------------


def fields(result: dict[str, Any]) -> dict[Any, Any]:
    """Return every field of a form, the fields of its sections included."""
    schema: vol.Schema = result["data_schema"]
    found: dict[Any, Any] = {}
    for marker, value in schema.schema.items():
        if isinstance(value, section):
            found.update(value.schema.schema)
        else:
            found[marker] = value
    return found


def field(result: dict[str, Any], key: str) -> Any:
    """Return the selector of one field of a form."""
    return next(value for marker, value in fields(result).items() if marker == key)


def suggested(result: dict[str, Any], key: str) -> Any:
    """Return the value a form suggests for one of its keys."""
    for marker in fields(result):
        if marker == key:
            return (marker.description or {}).get("suggested_value")
    raise AssertionError(f"{key} is not part of the form")


async def start_new_tracker(
    hass: HomeAssistant, entry: MockConfigEntry, sources: list[str]
) -> dict[str, Any]:
    """Fill in the first step of a new tracker."""
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_TRACKER), context={"source": SOURCE_USER}
    )
    return await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Kid",
            CONF_CREATE_PERSON: False,
            SECTION_SOURCES: {CONF_BUTTON_SOURCES: sources},
        },
    )


async def test_without_buttons_there_is_no_second_step(hass: HomeAssistant) -> None:
    """A tracker without sources is stored right away, without any button key."""
    entry = await setup_entry(hass, make_entry())

    result = await start_new_tracker(hass, entry, [])
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    subentry = entry.get_subentries_of_type(SUBENTRY_TYPE_TRACKER)[0]
    assert (
        not {
            CONF_BUTTON_SOURCES,
            CONF_BUTTON_HOME_TYPES,
            CONF_BUTTON_AWAY_TYPES,
        }
        & subentry.data.keys()
    )


async def test_the_second_step_offers_the_types_of_the_buttons(
    hass: HomeAssistant,
) -> None:
    """The options are the union of what the buttons offer, in their order."""
    entry = await setup_entry(hass, make_entry())

    result = await start_new_tracker(hass, entry, [BUTTON, OTHER_BUTTON])

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "buttons"
    assert result["description_placeholders"]["name"] == "Kid"
    for key in (CONF_BUTTON_HOME_TYPES, CONF_BUTTON_AWAY_TYPES):
        config = field(result, key).config
        assert config["options"] == list(dict.fromkeys(SHELLY_TYPES + HUE_TYPES))
        assert config["multiple"] is True
        assert config["custom_value"] is False
    # A short press means home and a long press away, until the user says else.
    assert suggested(result, CONF_BUTTON_HOME_TYPES) == ["press"]
    assert suggested(result, CONF_BUTTON_AWAY_TYPES) == ["long_press"]

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            CONF_BUTTON_HOME_TYPES: ["press", "short_release"],
            CONF_BUTTON_AWAY_TYPES: ["long_press"],
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    subentry = entry.get_subentries_of_type(SUBENTRY_TYPE_TRACKER)[0]
    assert subentry.data[CONF_BUTTON_SOURCES] == [BUTTON, OTHER_BUTTON]
    assert subentry.data[CONF_BUTTON_HOME_TYPES] == ["press", "short_release"]
    assert subentry.data[CONF_BUTTON_AWAY_TYPES] == ["long_press"]
    # And the new tracker follows its buttons straight away.
    await press(hass, "short_release", OTHER_BUTTON)
    assert entry.runtime_data.manager.is_home(subentry.subentry_id) is True


async def test_nothing_is_suggested_without_a_press(hass: HomeAssistant) -> None:
    """A button that knows no "press" comes up without a suggestion."""
    entry = await setup_entry(hass, make_entry())

    result = await start_new_tracker(hass, entry, [OTHER_BUTTON])

    assert field(result, CONF_BUTTON_HOME_TYPES).config["options"] == HUE_TYPES
    assert suggested(result, CONF_BUTTON_HOME_TYPES) == []
    assert suggested(result, CONF_BUTTON_AWAY_TYPES) == []


async def test_a_type_cannot_mean_home_and_away(hass: HomeAssistant) -> None:
    """The overlap is named, and the corrected form goes through."""
    entry = await setup_entry(hass, make_entry())
    result = await start_new_tracker(hass, entry, [BUTTON])

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            CONF_BUTTON_HOME_TYPES: ["press", "double_press"],
            CONF_BUTTON_AWAY_TYPES: ["double_press", "long_press"],
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "buttons"
    assert result["errors"] == {"base": "button_types_overlap"}
    assert result["description_placeholders"]["types"] == "double_press"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            CONF_BUTTON_HOME_TYPES: ["press", "double_press"],
            CONF_BUTTON_AWAY_TYPES: ["long_press"],
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_a_button_has_to_mean_something(hass: HomeAssistant) -> None:
    """Sources without a single event type are refused."""
    entry = await setup_entry(hass, make_entry())
    result = await start_new_tracker(hass, entry, [BUTTON])

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_BUTTON_HOME_TYPES: [], CONF_BUTTON_AWAY_TYPES: []}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "button_types_missing"}

    # One direction is enough.
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_BUTTON_HOME_TYPES: ["press"]}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    subentry = entry.get_subentries_of_type(SUBENTRY_TYPE_TRACKER)[0]
    assert subentry.data[CONF_BUTTON_AWAY_TYPES] == []


async def test_a_button_without_a_state_allows_free_entry(
    hass: HomeAssistant,
) -> None:
    """Event types come from the registry, or are typed in when unknown."""
    entry = await setup_entry(hass, make_entry())
    er.async_get(hass).async_get_or_create(
        "event",
        "test",
        "registered_button",
        suggested_object_id="registered_button",
        capabilities={ATTR_EVENT_TYPES: ["single", "double"]},
    )

    result = await start_new_tracker(
        hass, entry, ["event.registered_button", "event.not_there_yet"]
    )

    config = field(result, CONF_BUTTON_HOME_TYPES).config
    assert config["options"] == ["single", "double"]
    assert config["custom_value"] is True

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_BUTTON_HOME_TYPES: ["single", "typed_in"]}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    subentry = entry.get_subentries_of_type(SUBENTRY_TYPE_TRACKER)[0]
    assert subentry.data[CONF_BUTTON_HOME_TYPES] == ["single", "typed_in"]


async def test_reconfigure_keeps_and_shows_the_buttons(hass: HomeAssistant) -> None:
    """Both steps come up with what the tracker has, and nothing reloads."""
    entry = await setup_entry(
        hass,
        button_entry(
            **{CONF_NOTIFY_PERSONS: []},
            **button_data(home=["double_press"], away=["hold_press"]),
        ),
    )
    manager = entry.runtime_data.manager

    result = await entry.start_subentry_reconfigure_flow(hass, TRACKER_A)
    assert suggested(result, CONF_BUTTON_SOURCES) == [BUTTON]

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Kid",
            CONF_NOTIFY_PERSONS: [],
            SECTION_SOURCES: {CONF_BUTTON_SOURCES: [BUTTON]},
        },
    )
    assert result["step_id"] == "buttons"
    # The stored mapping, not the suggestion for a new tracker.
    assert suggested(result, CONF_BUTTON_HOME_TYPES) == ["double_press"]
    assert suggested(result, CONF_BUTTON_AWAY_TYPES) == ["hold_press"]

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {CONF_BUTTON_HOME_TYPES: ["press"], CONF_BUTTON_AWAY_TYPES: ["hold_press"]},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.subentries[TRACKER_A].data[CONF_BUTTON_HOME_TYPES] == ["press"]
    assert entry.runtime_data.manager is manager

    await press(hass, "press")
    assert manager.is_home(TRACKER_A) is True


async def test_removing_every_button_clears_the_types(hass: HomeAssistant) -> None:
    """Without a source the event types go too, and the tracker stops following."""
    entry = await setup_entry(hass, button_entry(**{CONF_NOTIFY_PERSONS: []}))
    manager = entry.runtime_data.manager

    result = await entry.start_subentry_reconfigure_flow(hass, TRACKER_A)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Kid",
            CONF_NOTIFY_PERSONS: [],
            SECTION_SOURCES: {CONF_BUTTON_SOURCES: []},
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    # "Away after" sits in the same section and was written with its value.
    assert dict(entry.subentries[TRACKER_A].data) == {
        CONF_NOTIFY_PERSONS: [],
        CONF_AWAY_AFTER: DEFAULT_AWAY_AFTER,
    }
    assert entry.runtime_data.manager is manager

    await press(hass, "press")
    assert manager.is_home(TRACKER_A) is False


# --- The integration's own event entities -----------------------------------


async def test_the_own_questions_entities_are_not_offered(hass: HomeAssistant) -> None:
    """The form leaves out the trackers' questions entities, and refuses them."""
    entry = await setup_entry(hass, make_entry(make_subentry(TRACKER_A, "Kid")))

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_TRACKER), context={"source": SOURCE_USER}
    )

    config = field(result, CONF_BUTTON_SOURCES).config
    assert config["exclude_entities"] == [EVENT_A]
    with pytest.raises(InvalidData):
        await hass.config_entries.subentries.async_configure(
            result["flow_id"],
            {
                CONF_NAME: "Granny",
                CONF_CREATE_PERSON: False,
                SECTION_SOURCES: {CONF_BUTTON_SOURCES: [EVENT_A]},
            },
        )


async def test_the_edit_form_drops_a_stored_questions_entity(
    hass: HomeAssistant,
) -> None:
    """A questions entity stored anyway is neither offered nor pre-filled."""
    entry = await setup_entry(
        hass, button_entry(**button_data(sources=[BUTTON, EVENT_A]))
    )

    result = await entry.start_subentry_reconfigure_flow(hass, TRACKER_A)

    assert field(result, CONF_BUTTON_SOURCES).config["exclude_entities"] == [
        "event.granny_questions",
        EVENT_A,
    ]
    assert suggested(result, CONF_BUTTON_SOURCES) == [BUTTON]


async def test_a_stored_questions_entity_switches_nothing(
    hass: HomeAssistant,
) -> None:
    """A tracker never follows the integration's own announcements."""
    entry = await setup_entry(
        hass,
        make_entry(
            make_subentry(TRACKER_A, "Kid"),
            make_subentry(
                TRACKER_B,
                "Granny",
                **button_data(sources=[EVENT_A], home=["prompt_started"], away=[]),
            ),
        ),
    )
    manager = entry.runtime_data.manager

    # Kid's questions entity announces a prompt: a real event of an event
    # entity, out of `unknown`, with a type the stored mapping names.
    assert manager.async_open_prompt(TRACKER_A) is OpenPromptResult.OPENED
    await hass.async_block_till_done()
    assert hass.states.get(EVENT_A).attributes[ATTR_EVENT_TYPE] == "prompt_started"

    assert manager.is_home(TRACKER_B) is False

    await unload(hass, entry)
