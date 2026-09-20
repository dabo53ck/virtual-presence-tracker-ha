"""Tests for the config flow and the virtual tracker subentry flow."""

from __future__ import annotations

from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
import voluptuous as vol

from custom_components.virtual_presence_tracker.const import (
    ATTR_DEVICE_TRACKERS,
    CONF_PERSONS,
    CONF_RESET_ON_RETURN,
    DOMAIN,
    SUBENTRY_TYPE_TRACKER,
)
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState, FlowType
from homeassistant.const import CONF_NAME, STATE_HOME, STATE_NOT_HOME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

PERSON_DABO53CK = "person.dabo53ck"
PERSON_KING53CK = "person.king53ck"
PERSON_KID = "person.kid"

TRACKER_A = "01JVPT000000000000000TRACKA"
TRACKER_B = "01JVPT000000000000000TRACKB"
TRACKER_A_ENTITY = "device_tracker.kid"


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
        flow_id, {CONF_NAME: "Kid", CONF_RESET_ON_RETURN: True}
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

    result = await add_tracker(
        hass, config_entry, {CONF_NAME: "  Kid  ", CONF_RESET_ON_RETURN: False}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Kid"

    subentries = config_entry.get_subentries_of_type(SUBENTRY_TYPE_TRACKER)
    assert len(subentries) == 1
    assert subentries[0].title == "Kid"
    assert dict(subentries[0].data) == {CONF_RESET_ON_RETURN: False}

    # The entry was reloaded, so the new tracker has a state.
    assert config_entry.runtime_data.manager.tracker_ids == [subentries[0].subentry_id]


async def test_subentry_defaults_to_reset_on_return(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """The form offers the documented default for the reset option."""
    await setup_entry(hass, config_entry)

    result = await hass.config_entries.subentries.async_init(
        (config_entry.entry_id, SUBENTRY_TYPE_TRACKER), context={"source": SOURCE_USER}
    )
    assert result["data_schema"]({CONF_NAME: "Kid"}) == {
        CONF_NAME: "Kid",
        CONF_RESET_ON_RETURN: True,
    }


async def test_subentry_needs_a_name(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """A blank name is refused."""
    await setup_entry(hass, config_entry)

    result = await add_tracker(
        hass, config_entry, {CONF_NAME: "   ", CONF_RESET_ON_RETURN: True}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_NAME: "name_required"}
    assert config_entry.subentries == {}


@pytest.mark.parametrize("name", ["Kid", "kid", "KID", "  kId  "])
async def test_subentry_rejects_a_duplicate_name(
    hass: HomeAssistant, name: str
) -> None:
    """Names are compared without case and without surrounding spaces."""
    entry = await setup_entry(hass, make_entry(make_subentry(TRACKER_A, "Kid")))

    result = await add_tracker(
        hass, entry, {CONF_NAME: name, CONF_RESET_ON_RETURN: True}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_NAME: "name_exists"}

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_NAME: "Granny", CONF_RESET_ON_RETURN: True}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert len(entry.get_subentries_of_type(SUBENTRY_TYPE_TRACKER)) == 2


async def test_subentry_reconfigure_renames_and_keeps_the_id(
    hass: HomeAssistant,
) -> None:
    """Renaming changes title and option but not the subentry ID."""
    entry = await setup_entry(
        hass,
        make_entry(make_subentry(TRACKER_A, "Kid", **{CONF_RESET_ON_RETURN: True})),
    )

    result = await entry.start_subentry_reconfigure_flow(hass, TRACKER_A)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    assert suggested(result, CONF_NAME) == "Kid"
    assert suggested(result, CONF_RESET_ON_RETURN) is True

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_NAME: "Kiddo", CONF_RESET_ON_RETURN: False}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"

    subentry = entry.subentries[TRACKER_A]
    assert subentry.title == "Kiddo"
    assert dict(subentry.data) == {CONF_RESET_ON_RETURN: False}
    assert entry.runtime_data.manager.tracker_ids == [TRACKER_A]


async def test_subentry_reconfigure_keeps_its_own_name(hass: HomeAssistant) -> None:
    """The duplicate check ignores the tracker that is being edited."""
    entry = await setup_entry(
        hass,
        make_entry(make_subentry(TRACKER_A, "Kid"), make_subentry(TRACKER_B, "Granny")),
    )

    result = await entry.start_subentry_reconfigure_flow(hass, TRACKER_A)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_NAME: "Kid", CONF_RESET_ON_RETURN: False}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert entry.subentries[TRACKER_A].title == "Kid"
    assert dict(entry.subentries[TRACKER_A].data) == {CONF_RESET_ON_RETURN: False}

    # The name of the other tracker is still taken.
    result = await entry.start_subentry_reconfigure_flow(hass, TRACKER_A)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_NAME: "granny", CONF_RESET_ON_RETURN: False}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_NAME: "name_exists"}
    assert entry.subentries[TRACKER_A].title == "Kid"
