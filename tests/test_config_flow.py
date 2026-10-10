"""Tests for the config flow and the virtual tracker subentry flow."""

from __future__ import annotations

from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
import voluptuous as vol

from custom_components.virtual_presence_tracker.const import (
    ATTR_DEVICE_TRACKERS,
    CONF_ANSWER_TIMEOUT,
    CONF_ASK_LEFT_BEHIND,
    CONF_ASK_ON_DEPARTURE,
    CONF_AWAY_AFTER,
    CONF_BUTTON_SOURCES,
    CONF_CREATE_PERSON,
    CONF_LEFT_BEHIND_OVERRIDE_DND,
    CONF_NOTIFY_ON_EXPIRY,
    CONF_NOTIFY_PERSONS,
    CONF_OVERRIDE_DND,
    CONF_PERSONS,
    CONF_PRESENCE_SOURCES,
    CONF_PROMPT_DELAY,
    CONF_REMIND_AFTER,
    CONF_REMINDER_TIMEOUT,
    CONF_RESET_ON_RETURN,
    DEFAULT_ANSWER_TIMEOUT,
    DEFAULT_ASK_LEFT_BEHIND,
    DEFAULT_AWAY_AFTER,
    DEFAULT_LEFT_BEHIND_OVERRIDE_DND,
    DEFAULT_NOTIFY_ON_EXPIRY,
    DEFAULT_OVERRIDE_DND,
    DEFAULT_PROMPT_DELAY,
    DEFAULT_REMINDER_TIMEOUT,
    DEFAULT_RESET_ON_RETURN,
    DOMAIN,
    NEW_TRACKER_ASK_ON_DEPARTURE,
    NEW_TRACKER_REMIND_AFTER,
    SECTION_QUESTIONS,
    SECTION_REMINDER,
    SECTION_SOURCES,
    SUBENTRY_TYPE_TRACKER,
)
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState, FlowType
from homeassistant.const import (
    CONF_NAME,
    EVENT_STATE_CHANGED,
    STATE_HOME,
    STATE_NOT_HOME,
    UnitOfTime,
)
from homeassistant.core import CoreState, Event, HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData, section

PERSON_DABO53CK = "person.dabo53ck"
PERSON_KING53CK = "person.king53ck"
PERSON_KID = "person.kid"

TRACKER_A = "01JVPT000000000000000TRACKA"
TRACKER_B = "01JVPT000000000000000TRACKB"
TRACKER_A_ENTITY = "device_tracker.kid"


def tracker_data(**overrides: Any) -> dict[str, Any]:
    """Return the subentry data a new tracker is written with.

    Every option is spelled out, so that the entities on the tracker's device
    page have a value from the start - and a new tracker asks and reminds, but
    does not ask about a device left behind (M3f).
    """
    return {
        CONF_RESET_ON_RETURN: DEFAULT_RESET_ON_RETURN,
        CONF_ASK_ON_DEPARTURE: NEW_TRACKER_ASK_ON_DEPARTURE,
        CONF_ANSWER_TIMEOUT: DEFAULT_ANSWER_TIMEOUT,
        CONF_PROMPT_DELAY: DEFAULT_PROMPT_DELAY,
        CONF_REMIND_AFTER: NEW_TRACKER_REMIND_AFTER,
        CONF_REMINDER_TIMEOUT: DEFAULT_REMINDER_TIMEOUT,
        CONF_NOTIFY_PERSONS: [],
        CONF_NOTIFY_ON_EXPIRY: DEFAULT_NOTIFY_ON_EXPIRY,
        CONF_OVERRIDE_DND: DEFAULT_OVERRIDE_DND,
        CONF_AWAY_AFTER: DEFAULT_AWAY_AFTER,
        CONF_ASK_LEFT_BEHIND: DEFAULT_ASK_LEFT_BEHIND,
        CONF_LEFT_BEHIND_OVERRIDE_DND: DEFAULT_LEFT_BEHIND_OVERRIDE_DND,
    } | overrides


def make_subentry(subentry_id: str, title: str, **data: Any) -> dict[str, Any]:
    """Return subentry data for one virtual tracker."""
    return {
        "data": data,
        "subentry_id": subentry_id,
        "subentry_type": SUBENTRY_TYPE_TRACKER,
        "title": title,
        "unique_id": None,
    }


def make_entry(*subentries: dict[str, Any]) -> MockConfigEntry:
    """Return a config entry with one real person and the given trackers."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Virtual Presence Tracker",
        data={CONF_PERSONS: [PERSON_DABO53CK]},
        subentries_data=subentries,
    )


def add_persons(hass: HomeAssistant) -> None:
    """Add two persons with a device tracker and one without."""
    hass.states.async_set(
        PERSON_DABO53CK,
        STATE_HOME,
        {ATTR_DEVICE_TRACKERS: ["device_tracker.dabo53ck_phone"]},
    )
    hass.states.async_set(
        PERSON_KING53CK,
        STATE_NOT_HOME,
        {ATTR_DEVICE_TRACKERS: ["device_tracker.king53ck_phone"]},
    )
    hass.states.async_set(PERSON_KID, STATE_NOT_HOME, {ATTR_DEVICE_TRACKERS: []})


def suggested(result: dict[str, Any], key: str) -> Any:
    """Return the value a form suggests for one of its keys."""
    schema: vol.Schema = result["data_schema"]
    for marker in schema.schema:
        if marker == key:
            return (marker.description or {}).get("suggested_value")
    raise AssertionError(f"{key} is not part of the form")


def sections(result: dict[str, Any]) -> dict[str, section]:
    """Return the sections of a form by their key (M3g)."""
    schema: vol.Schema = result["data_schema"]
    return {
        str(marker): value
        for marker, value in schema.schema.items()
        if isinstance(value, section)
    }


def section_fields(result: dict[str, Any], section_key: str) -> dict[str, Any]:
    """Return the fields of one section by their key."""
    return {
        str(marker): value
        for marker, value in sections(result)[section_key].schema.schema.items()
    }


def section_suggested(result: dict[str, Any], section_key: str, key: str) -> Any:
    """Return the value one section suggests for one of its keys."""
    for marker in sections(result)[section_key].schema.schema:
        if marker == key:
            return (marker.description or {}).get("suggested_value")
    raise AssertionError(f"{key} is not part of the section {section_key}")


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> MockConfigEntry:
    """Add a config entry to hass and set it up."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def add_tracker(
    hass: HomeAssistant, entry: MockConfigEntry, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Run the tracker subentry flow to its end."""
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_TRACKER), context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    return await hass.config_entries.subentries.async_configure(
        result["flow_id"], user_input
    )


async def run_user_flow(hass: HomeAssistant, persons: list[str]) -> dict[str, Any]:
    """Run the config flow to its end and return the create-entry result."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_PERSONS: persons}
    )
    await hass.async_block_till_done()
    return result


async def test_user_flow_creates_entry(hass: HomeAssistant) -> None:
    """The user step suggests the locatable persons and creates the entry."""
    add_persons(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    # The person without a device tracker is the one a virtual tracker is for.
    assert suggested(result, CONF_PERSONS) == [PERSON_DABO53CK, PERSON_KING53CK]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_PERSONS: [PERSON_DABO53CK, PERSON_KING53CK]}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Virtual Presence Tracker"
    assert result["data"] == {CONF_PERSONS: [PERSON_DABO53CK, PERSON_KING53CK]}


async def test_user_flow_continues_with_the_tracker_form(hass: HomeAssistant) -> None:
    """The setup hands the user straight on to the first virtual tracker."""
    add_persons(hass)

    result = await run_user_flow(hass, [PERSON_DABO53CK])
    entry = result["result"]

    flow_type, flow_id = result["next_flow"]
    assert flow_type is FlowType.CONFIG_SUBENTRIES_FLOW

    # The chained flow is the only one in progress and waits with the form that
    # adds a tracker to the entry that was just created.
    in_progress = hass.config_entries.subentries.async_progress()
    assert len(in_progress) == 1
    assert in_progress[0]["flow_id"] == flow_id
    assert in_progress[0]["step_id"] == "user"
    assert in_progress[0]["handler"] == (entry.entry_id, SUBENTRY_TYPE_TRACKER)

    result = await hass.config_entries.subentries.async_configure(
        flow_id, {CONF_NAME: "Kid"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Kid"
    subentries = entry.get_subentries_of_type(SUBENTRY_TYPE_TRACKER)
    assert len(subentries) == 1
    assert entry.runtime_data.manager.tracker_ids == [subentries[0].subentry_id]


async def test_an_abandoned_tracker_form_leaves_a_working_entry(
    hass: HomeAssistant,
) -> None:
    """Closing the chained form is allowed; the repair issue takes over."""
    add_persons(hass)

    result = await run_user_flow(hass, [PERSON_DABO53CK])
    entry = result["result"]

    hass.config_entries.subentries.async_abort(result["next_flow"][1])
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.get_subentries_of_type(SUBENTRY_TYPE_TRACKER) == []
    assert entry.runtime_data.manager.tracker_ids == []


@pytest.mark.parametrize("user_input", [{}, {CONF_PERSONS: []}])
async def test_user_flow_needs_a_person(
    hass: HomeAssistant, user_input: dict[str, Any]
) -> None:
    """An empty selection is refused, the form can be completed afterwards."""
    add_persons(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=user_input
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {CONF_PERSONS: "no_persons"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_PERSONS: [PERSON_DABO53CK]}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_PERSONS: [PERSON_DABO53CK]}


async def test_only_one_entry_allowed(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """A second entry is refused (manifest: single_config_entry)."""
    config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_reconfigure_changes_the_persons(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """New persons are stored and watched by the manager after the reload."""
    add_persons(hass)
    await setup_entry(hass, config_entry)

    result = await config_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    assert suggested(result, CONF_PERSONS) == [PERSON_DABO53CK, PERSON_KING53CK]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_PERSONS: [PERSON_KING53CK]}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data == {CONF_PERSONS: [PERSON_KING53CK]}

    manager = config_entry.runtime_data.manager
    assert manager.real_home is False

    hass.states.async_set(PERSON_KING53CK, STATE_HOME)
    await hass.async_block_till_done()
    assert manager.real_persons_home == 1

    # dabo53ck is not watched any more.
    hass.states.async_set(PERSON_DABO53CK, STATE_NOT_HOME)
    await hass.async_block_till_done()
    assert manager.real_persons_home == 1


async def test_reconfigure_needs_a_person(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Reconfiguring cannot empty the list of real persons."""
    add_persons(hass)
    await setup_entry(hass, config_entry)

    result = await config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_PERSONS: []}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    assert result["errors"] == {CONF_PERSONS: "no_persons"}
    assert config_entry.data == {CONF_PERSONS: [PERSON_DABO53CK, PERSON_KING53CK]}


async def test_reconfigure_rejects_a_person_with_a_virtual_tracker(
    hass: HomeAssistant,
) -> None:
    """A person that carries one of our trackers cannot be a real person.

    Switching that tracker on would look like a real arrival and reset every
    tracker at once.
    """
    add_persons(hass)
    hass.states.async_set(
        PERSON_KID, STATE_NOT_HOME, {ATTR_DEVICE_TRACKERS: [TRACKER_A_ENTITY]}
    )
    entry = await setup_entry(hass, make_entry(make_subentry(TRACKER_A, "Kid")))

    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_PERSONS: [PERSON_DABO53CK, PERSON_KID]}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    assert result["errors"] == {CONF_PERSONS: "person_has_virtual_tracker"}
    # The message names the person that has to go.
    assert result["description_placeholders"] == {"persons": PERSON_KID}
    assert entry.data == {CONF_PERSONS: [PERSON_DABO53CK]}

    # Taking the tracker off the person makes the same selection acceptable.
    hass.states.async_set(PERSON_KID, STATE_NOT_HOME, {ATTR_DEVICE_TRACKERS: []})
    await hass.async_block_till_done()
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={CONF_PERSONS: [PERSON_DABO53CK, PERSON_KID]}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data == {CONF_PERSONS: [PERSON_DABO53CK, PERSON_KID]}


async def test_subentry_adds_a_tracker(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """A tracker is stored under its name and known to the manager."""
    await setup_entry(hass, config_entry)

    result = await add_tracker(hass, config_entry, {CONF_NAME: "  Kid  "})
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Kid"

    subentries = config_entry.get_subentries_of_type(SUBENTRY_TYPE_TRACKER)
    assert len(subentries) == 1
    assert subentries[0].title == "Kid"
    # A new tracker is written with every option spelled out, and it asks.
    assert dict(subentries[0].data) == tracker_data()
    assert subentries[0].data[CONF_ASK_ON_DEPARTURE] is True

    # The entry was reloaded, so the new tracker has a state.
    assert config_entry.runtime_data.manager.tracker_ids == [subentries[0].subentry_id]


async def test_the_form_has_the_general_fields_and_three_sections(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Name, recipients and person at the top, the rest in sections (M3g).

    The sections are collapsed for a new tracker, and the Bluetooth field is
    only there while Bluetooth is set up, which it is not here.
    """
    await setup_entry(hass, config_entry)

    result = await hass.config_entries.subentries.async_init(
        (config_entry.entry_id, SUBENTRY_TYPE_TRACKER), context={"source": SOURCE_USER}
    )
    schema: vol.Schema = result["data_schema"]

    assert [str(key) for key in schema.schema] == [
        CONF_NAME,
        CONF_NOTIFY_PERSONS,
        CONF_CREATE_PERSON,
        SECTION_QUESTIONS,
        SECTION_REMINDER,
        SECTION_SOURCES,
    ]
    assert list(section_fields(result, SECTION_QUESTIONS)) == [
        CONF_ANSWER_TIMEOUT,
        CONF_PROMPT_DELAY,
        CONF_NOTIFY_ON_EXPIRY,
    ]
    assert list(section_fields(result, SECTION_REMINDER)) == [
        CONF_REMIND_AFTER,
        CONF_REMINDER_TIMEOUT,
    ]
    assert list(section_fields(result, SECTION_SOURCES)) == [
        CONF_BUTTON_SOURCES,
        CONF_PRESENCE_SOURCES,
        CONF_AWAY_AFTER,
    ]
    assert all(value.options["collapsed"] for value in sections(result).values())
    # A section key has no default: the frontend would take an empty default
    # as the section's data and lose the values of the fields inside.
    assert schema({CONF_NAME: "Kid"}) == {
        CONF_NAME: "Kid",
        CONF_NOTIFY_PERSONS: [],
        CONF_CREATE_PERSON: True,
    }
    # The fields inside default to what a new tracker is written with.
    assert sections(result)[SECTION_QUESTIONS]({}) == {
        CONF_ANSWER_TIMEOUT: DEFAULT_ANSWER_TIMEOUT,
        CONF_PROMPT_DELAY: DEFAULT_PROMPT_DELAY,
        CONF_NOTIFY_ON_EXPIRY: DEFAULT_NOTIFY_ON_EXPIRY,
    }
    assert sections(result)[SECTION_REMINDER]({}) == {
        CONF_REMIND_AFTER: NEW_TRACKER_REMIND_AFTER,
        CONF_REMINDER_TIMEOUT: DEFAULT_REMINDER_TIMEOUT,
    }
    assert sections(result)[SECTION_SOURCES]({}) == {
        CONF_BUTTON_SOURCES: [],
        CONF_PRESENCE_SOURCES: [],
        CONF_AWAY_AFTER: DEFAULT_AWAY_AFTER,
    }


@pytest.mark.parametrize(
    ("section_key", "key", "minimum", "maximum", "unit"),
    [
        (SECTION_QUESTIONS, CONF_ANSWER_TIMEOUT, 1, 120, UnitOfTime.MINUTES),
        (SECTION_QUESTIONS, CONF_PROMPT_DELAY, 0, 600, UnitOfTime.SECONDS),
        (SECTION_REMINDER, CONF_REMIND_AFTER, 0, 168, UnitOfTime.HOURS),
        (SECTION_REMINDER, CONF_REMINDER_TIMEOUT, 1, 360, UnitOfTime.MINUTES),
        (SECTION_SOURCES, CONF_AWAY_AFTER, 1, 120, UnitOfTime.MINUTES),
    ],
)
async def test_the_timings_keep_their_range_and_unit(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    section_key: str,
    key: str,
    minimum: int,
    maximum: int,
    unit: str,
) -> None:
    """The ranges the number entities had, and a value outside is refused."""
    await setup_entry(hass, config_entry)

    result = await hass.config_entries.subentries.async_init(
        (config_entry.entry_id, SUBENTRY_TYPE_TRACKER), context={"source": SOURCE_USER}
    )
    config = section_fields(result, section_key)[key].config
    assert config["min"] == minimum
    assert config["max"] == maximum
    assert config["step"] == 1
    assert config["mode"] == "box"
    assert config["unit_of_measurement"] == unit

    with pytest.raises(InvalidData):
        await hass.config_entries.subentries.async_configure(
            result["flow_id"],
            {CONF_NAME: "Kid", section_key: {key: maximum + 1}},
        )
    assert config_entry.subentries == {}


async def test_a_new_tracker_stores_the_sections_flat(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """The values of the sections land under their keys, as whole numbers."""
    await setup_entry(hass, config_entry)

    result = await add_tracker(
        hass,
        config_entry,
        {
            CONF_NAME: "Kid",
            CONF_CREATE_PERSON: False,
            SECTION_QUESTIONS: {
                CONF_ANSWER_TIMEOUT: 15.0,
                CONF_PROMPT_DELAY: 30.0,
                CONF_NOTIFY_ON_EXPIRY: True,
            },
            SECTION_REMINDER: {CONF_REMIND_AFTER: 0.0, CONF_REMINDER_TIMEOUT: 120.0},
            SECTION_SOURCES: {CONF_AWAY_AFTER: 5.0},
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    data = dict(config_entry.get_subentries_of_type(SUBENTRY_TYPE_TRACKER)[0].data)
    assert data == tracker_data(
        **{
            CONF_ANSWER_TIMEOUT: 15,
            CONF_PROMPT_DELAY: 30,
            CONF_NOTIFY_ON_EXPIRY: True,
            CONF_REMIND_AFTER: 0,
            CONF_REMINDER_TIMEOUT: 120,
            CONF_AWAY_AFTER: 5,
        }
    )
    assert all(
        type(data[key]) is int
        for key in (
            CONF_ANSWER_TIMEOUT,
            CONF_PROMPT_DELAY,
            CONF_REMIND_AFTER,
            CONF_REMINDER_TIMEOUT,
            CONF_AWAY_AFTER,
        )
    )
    # No section key is ever stored.
    assert not {SECTION_QUESTIONS, SECTION_REMINDER, SECTION_SOURCES} & data.keys()


async def test_the_edit_form_shows_the_stored_values_by_section(
    hass: HomeAssistant,
) -> None:
    """Each section comes up with what the tracker has stored."""
    stored = tracker_data(
        **{
            CONF_ANSWER_TIMEOUT: 25,
            CONF_PROMPT_DELAY: 45,
            CONF_NOTIFY_ON_EXPIRY: True,
            CONF_REMIND_AFTER: 12,
            CONF_REMINDER_TIMEOUT: 90,
            CONF_AWAY_AFTER: 15,
        }
    )
    entry = await setup_entry(
        hass, make_entry(make_subentry(TRACKER_A, "Kid", **stored))
    )

    result = await entry.start_subentry_reconfigure_flow(hass, TRACKER_A)

    for section_key, key in (
        (SECTION_QUESTIONS, CONF_ANSWER_TIMEOUT),
        (SECTION_QUESTIONS, CONF_PROMPT_DELAY),
        (SECTION_QUESTIONS, CONF_NOTIFY_ON_EXPIRY),
        (SECTION_REMINDER, CONF_REMIND_AFTER),
        (SECTION_REMINDER, CONF_REMINDER_TIMEOUT),
        (SECTION_SOURCES, CONF_AWAY_AFTER),
    ):
        assert section_suggested(result, section_key, key) == stored[key], key
    # Without sources the sources stay closed, like the other two.
    assert all(value.options["collapsed"] for value in sections(result).values())


async def test_the_edit_form_of_an_old_tracker_shows_what_applies(
    hass: HomeAssistant,
) -> None:
    """A missing key shows the value that applies to it, not a new tracker's.

    A tracker from before the reminder never reminds, so it shows 0 - not the
    24 hours a new tracker gets.
    """
    entry = await setup_entry(hass, make_entry(make_subentry(TRACKER_A, "Kid")))

    result = await entry.start_subentry_reconfigure_flow(hass, TRACKER_A)

    assert section_suggested(result, SECTION_REMINDER, CONF_REMIND_AFTER) == 0
    assert (
        section_suggested(result, SECTION_QUESTIONS, CONF_ANSWER_TIMEOUT)
        == DEFAULT_ANSWER_TIMEOUT
    )
    assert section_suggested(result, SECTION_QUESTIONS, CONF_NOTIFY_ON_EXPIRY) is False
    assert section_suggested(result, SECTION_SOURCES, CONF_AWAY_AFTER) == (
        DEFAULT_AWAY_AFTER
    )

    # Saved as shown, the values that applied are now spelled out - and the
    # tracker still does not remind.
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Kid",
            SECTION_QUESTIONS: {},
            SECTION_REMINDER: {},
            SECTION_SOURCES: {},
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert dict(entry.subentries[TRACKER_A].data) == {
        CONF_NOTIFY_PERSONS: [],
        CONF_ANSWER_TIMEOUT: DEFAULT_ANSWER_TIMEOUT,
        CONF_PROMPT_DELAY: DEFAULT_PROMPT_DELAY,
        CONF_NOTIFY_ON_EXPIRY: False,
        CONF_REMIND_AFTER: 0,
        CONF_REMINDER_TIMEOUT: DEFAULT_REMINDER_TIMEOUT,
        CONF_AWAY_AFTER: DEFAULT_AWAY_AFTER,
    }


async def test_the_sources_are_open_for_a_tracker_that_has_some(
    hass: HomeAssistant,
) -> None:
    """Edit opens "Sources" where they matter; the other sections stay closed."""
    entry = await setup_entry(
        hass,
        make_entry(
            make_subentry(
                TRACKER_A, "Kid", **{CONF_PRESENCE_SOURCES: ["device_tracker.tag"]}
            ),
            make_subentry(TRACKER_B, "Granny"),
        ),
    )

    result = await entry.start_subentry_reconfigure_flow(hass, TRACKER_A)

    assert sections(result)[SECTION_SOURCES].options["collapsed"] is False
    assert sections(result)[SECTION_QUESTIONS].options["collapsed"] is True
    assert sections(result)[SECTION_REMINDER].options["collapsed"] is True
    assert section_suggested(result, SECTION_SOURCES, CONF_PRESENCE_SOURCES) == [
        "device_tracker.tag"
    ]

    result = await entry.start_subentry_reconfigure_flow(hass, TRACKER_B)

    assert sections(result)[SECTION_SOURCES].options["collapsed"] is True


async def test_saving_only_the_timings_does_not_reload(hass: HomeAssistant) -> None:
    """The form writes the timings live, as their entities used to (M3g).

    The device tracker must not go through `unavailable`: an automation that
    waits for somebody to come home could not tell that from an arrival.
    """
    entry = await setup_entry(
        hass,
        make_entry(make_subentry(TRACKER_A, "Kid", **tracker_data())),
    )
    manager = entry.runtime_data.manager
    changes: list[str] = []

    def record(event: Event[Any]) -> None:
        if event.data["entity_id"] == TRACKER_A_ENTITY:
            changes.append(event.data["new_state"].state)

    hass.bus.async_listen(EVENT_STATE_CHANGED, record)

    result = await entry.start_subentry_reconfigure_flow(hass, TRACKER_A)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Kid",
            CONF_NOTIFY_PERSONS: [],
            SECTION_QUESTIONS: {CONF_ANSWER_TIMEOUT: 30, CONF_PROMPT_DELAY: 20},
            SECTION_REMINDER: {CONF_REMIND_AFTER: 6},
            SECTION_SOURCES: {CONF_AWAY_AFTER: 25},
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert entry.runtime_data.manager is manager
    assert changes == []
    assert manager.option(TRACKER_A, CONF_ANSWER_TIMEOUT) == 30
    assert manager.option(TRACKER_A, CONF_PROMPT_DELAY) == 20
    assert manager.option(TRACKER_A, CONF_REMIND_AFTER) == 6
    assert manager.option(TRACKER_A, CONF_AWAY_AFTER) == 25


async def test_the_reconfigure_form_does_not_offer_a_person(
    hass: HomeAssistant,
) -> None:
    """An existing tracker has its person, or the user said no to it once."""
    entry = await setup_entry(hass, make_entry(make_subentry(TRACKER_A, "Kid")))

    result = await entry.start_subentry_reconfigure_flow(hass, TRACKER_A)
    schema: vol.Schema = result["data_schema"]

    assert [str(key) for key in schema.schema] == [
        CONF_NAME,
        CONF_NOTIFY_PERSONS,
        SECTION_QUESTIONS,
        SECTION_REMINDER,
        SECTION_SOURCES,
    ]


async def test_a_new_tracker_asks_for_a_person_to_be_created(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """The form leaves a marker; the person is created after the start.

    The tracker's device tracker entity does not exist while the form is open,
    so the flow cannot create the person itself.
    """
    hass.set_state(CoreState.not_running)
    await setup_entry(hass, config_entry)

    await add_tracker(hass, config_entry, {CONF_NAME: "Kid"})
    await hass.async_block_till_done()

    subentry = config_entry.get_subentries_of_type(SUBENTRY_TYPE_TRACKER)[0]
    assert dict(subentry.data) == tracker_data(**{CONF_CREATE_PERSON: True})


async def test_a_new_tracker_can_be_added_without_a_person(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Unticking the box stores no marker at all, so nothing is created."""
    hass.set_state(CoreState.not_running)
    await setup_entry(hass, config_entry)

    await add_tracker(hass, config_entry, {CONF_NAME: "Kid", CONF_CREATE_PERSON: False})
    await hass.async_block_till_done()

    subentry = config_entry.get_subentries_of_type(SUBENTRY_TYPE_TRACKER)[0]
    assert dict(subentry.data) == tracker_data()


async def test_subentry_stores_the_recipients(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """The recipients are stored as chosen, the rest keeps its defaults."""
    add_persons(hass)
    await setup_entry(hass, config_entry)

    await add_tracker(
        hass, config_entry, {CONF_NAME: "Kid", CONF_NOTIFY_PERSONS: [PERSON_DABO53CK]}
    )
    await hass.async_block_till_done()

    subentry = config_entry.get_subentries_of_type(SUBENTRY_TYPE_TRACKER)[0]
    assert dict(subentry.data) == tracker_data(
        **{CONF_NOTIFY_PERSONS: [PERSON_DABO53CK]}
    )


async def test_subentry_offers_only_the_real_persons(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Only a real person of this household can be picked as a recipient."""
    add_persons(hass)
    await setup_entry(hass, config_entry)

    result = await hass.config_entries.subentries.async_init(
        (config_entry.entry_id, SUBENTRY_TYPE_TRACKER), context={"source": SOURCE_USER}
    )
    schema: vol.Schema = result["data_schema"]
    selector = next(
        value for key, value in schema.schema.items() if key == CONF_NOTIFY_PERSONS
    )
    assert selector.config["include_entities"] == [PERSON_DABO53CK, PERSON_KING53CK]
    assert selector.config["multiple"] is True


async def test_a_new_tracker_starts_with_every_real_person_ticked(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """The recipients of a new tracker are pre-selected, and can be emptied."""
    add_persons(hass)
    await setup_entry(hass, config_entry)

    result = await hass.config_entries.subentries.async_init(
        (config_entry.entry_id, SUBENTRY_TYPE_TRACKER), context={"source": SOURCE_USER}
    )
    assert suggested(result, CONF_NOTIFY_PERSONS) == [PERSON_DABO53CK, PERSON_KING53CK]

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_NAME: "Kid", CONF_NOTIFY_PERSONS: []}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    subentry = config_entry.get_subentries_of_type(SUBENTRY_TYPE_TRACKER)[0]
    assert subentry.data[CONF_NOTIFY_PERSONS] == []


async def test_subentry_rejects_a_recipient_who_is_not_real(
    hass: HomeAssistant,
) -> None:
    """A recipient who lost their real-person status is named and refused.

    The form still offers the stored recipient, so the user can take them out;
    submitting the tracker unchanged is what the error stops.
    """
    add_persons(hass)
    entry = await setup_entry(
        hass,
        make_entry(
            make_subentry(
                TRACKER_A,
                "Kid",
                **tracker_data(
                    **{
                        CONF_ASK_ON_DEPARTURE: True,
                        CONF_NOTIFY_PERSONS: [PERSON_DABO53CK, PERSON_KING53CK],
                    }
                ),
            )
        ),
    )

    result = await entry.start_subentry_reconfigure_flow(hass, TRACKER_A)
    assert suggested(result, CONF_NOTIFY_PERSONS) == [PERSON_DABO53CK, PERSON_KING53CK]

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {CONF_NAME: "Kid", CONF_NOTIFY_PERSONS: [PERSON_DABO53CK, PERSON_KING53CK]},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_NOTIFY_PERSONS: "person_not_real"}
    assert result["description_placeholders"] == {"persons": PERSON_KING53CK}

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_NAME: "Kid", CONF_NOTIFY_PERSONS: [PERSON_DABO53CK]}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert entry.subentries[TRACKER_A].data[CONF_NOTIFY_PERSONS] == [PERSON_DABO53CK]


async def test_subentry_needs_a_name(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """A blank name is refused."""
    await setup_entry(hass, config_entry)

    result = await add_tracker(hass, config_entry, {CONF_NAME: "   "})

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_NAME: "name_required"}
    assert config_entry.subentries == {}


@pytest.mark.parametrize("name", ["Kid", "kid", "KID", "  kId  "])
async def test_subentry_rejects_a_duplicate_name(
    hass: HomeAssistant, name: str
) -> None:
    """Names are compared without case and without surrounding spaces."""
    entry = await setup_entry(hass, make_entry(make_subentry(TRACKER_A, "Kid")))

    result = await add_tracker(hass, entry, {CONF_NAME: name})

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_NAME: "name_exists"}

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_NAME: "Granny"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert len(entry.get_subentries_of_type(SUBENTRY_TYPE_TRACKER)) == 2


async def test_subentry_reconfigure_renames_and_keeps_the_id(
    hass: HomeAssistant,
) -> None:
    """Renaming changes the title but not the subentry ID or the settings."""
    settings = tracker_data(
        **{
            CONF_RESET_ON_RETURN: False,
            CONF_ASK_ON_DEPARTURE: False,
            CONF_ANSWER_TIMEOUT: 20,
            CONF_PROMPT_DELAY: 45,
            CONF_NOTIFY_ON_EXPIRY: True,
        }
    )
    entry = await setup_entry(
        hass, make_entry(make_subentry(TRACKER_A, "Kid", **settings))
    )

    result = await entry.start_subentry_reconfigure_flow(hass, TRACKER_A)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    assert suggested(result, CONF_NAME) == "Kid"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_NAME: "Kiddo"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"

    subentry = entry.subentries[TRACKER_A]
    assert subentry.title == "Kiddo"
    # Everything the entities of the tracker write survives the form.
    assert dict(subentry.data) == settings
    assert entry.runtime_data.manager.tracker_ids == [TRACKER_A]


async def test_subentry_reconfigure_keeps_the_settings_of_an_old_tracker(
    hass: HomeAssistant,
) -> None:
    """A tracker without the keys does not get them from the form either.

    A missing key means "no" for the ask option, and a form that wrote the
    defaults in would silently switch the prompt on.
    """
    entry = await setup_entry(hass, make_entry(make_subentry(TRACKER_A, "Kid")))

    result = await entry.start_subentry_reconfigure_flow(hass, TRACKER_A)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_NAME: "Kid"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert dict(entry.subentries[TRACKER_A].data) == {CONF_NOTIFY_PERSONS: []}


async def test_subentry_reconfigure_keeps_its_own_name(hass: HomeAssistant) -> None:
    """The duplicate check ignores the tracker that is being edited."""
    entry = await setup_entry(
        hass,
        make_entry(make_subentry(TRACKER_A, "Kid"), make_subentry(TRACKER_B, "Granny")),
    )

    result = await entry.start_subentry_reconfigure_flow(hass, TRACKER_A)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_NAME: "Kid"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert entry.subentries[TRACKER_A].title == "Kid"

    # The name of the other tracker is still taken.
    result = await entry.start_subentry_reconfigure_flow(hass, TRACKER_A)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_NAME: "granny"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_NAME: "name_exists"}
    assert entry.subentries[TRACKER_A].title == "Kid"
