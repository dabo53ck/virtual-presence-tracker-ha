"""Tests for the repair issues of a config entry."""

from __future__ import annotations

from collections.abc import Iterable

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.virtual_presence_tracker.const import (
    ATTR_DEVICE_TRACKERS,
    ATTR_USER_ID,
    CONF_ASK_ON_DEPARTURE,
    CONF_BLE_SOURCES,
    CONF_BUTTON_SOURCES,
    CONF_DEVICE_NAME,
    CONF_NOTIFY_PERSONS,
    CONF_PRESENCE_SOURCES,
    CONF_REMIND_AFTER,
    CONF_USER_ID,
    DOMAIN,
    MOBILE_APP_DOMAIN,
    NOTIFY_DOMAIN,
    SUBENTRY_TYPE_TRACKER,
)
from custom_components.virtual_presence_tracker.issues import (
    ISSUE_NO_TRACKER,
    ISSUE_REAL_PERSON_HAS_VIRTUAL_TRACKER,
    ISSUE_REAL_PERSON_MISSING,
    ISSUE_RECIPIENT_WITHOUT_PHONE,
    ISSUE_SOURCE_MISSING,
    ISSUE_TRACKER_NOT_ASSIGNED,
    person_key,
)
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import (
    EVENT_HOMEASSISTANT_STARTED,
    STATE_HOME,
    STATE_NOT_HOME,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.helpers import entity_registry as er, issue_registry as ir

from .conftest import (
    ENTRY_ID,
    PERSON_A,
    PERSON_B,
    TRACKER_A,
    TRACKER_B,
    make_entry,
    make_subentry,
)

TRACKER_A_ENTITY = "device_tracker.kid"
TRACKER_B_ENTITY = "device_tracker.granny"

PERSON_KID = "person.kid"
DABO53CK_PHONE = "device_tracker.dabo53ck_phone"

USER_A = "user-dabo53ck"
PHONE_A = "mobile_app_dabo53ck_s_phone"


def issue_id(translation_key: str, *parts: str) -> str:
    """Return the issue ID the integration builds for the test entry."""
    return "_".join((ENTRY_ID, translation_key, *parts))


def issues(hass: HomeAssistant) -> dict[str, ir.IssueEntry]:
    """Return the issues of this integration, by issue ID."""
    return {
        issue.issue_id: issue
        for (domain, _), issue in ir.async_get(hass).issues.items()
        if domain == DOMAIN
    }


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Add a config entry to hass and set it up."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def set_person(
    hass: HomeAssistant,
    entity_id: str,
    trackers: Iterable[str] = (),
    state: str = STATE_NOT_HOME,
    user_id: str | None = None,
) -> None:
    """Set a person state with the device trackers and the user of it."""
    attributes: dict[str, object] = {ATTR_DEVICE_TRACKERS: list(trackers)}
    if user_id is not None:
        attributes[ATTR_USER_ID] = user_id
    hass.states.async_set(entity_id, state, attributes)
    await hass.async_block_till_done()


def add_phone(hass: HomeAssistant, device_name: str, user_id: str) -> None:
    """Register a Companion App phone of a user."""
    MockConfigEntry(
        domain=MOBILE_APP_DOMAIN,
        title=device_name,
        data={CONF_DEVICE_NAME: device_name, CONF_USER_ID: user_id},
    ).add_to_hass(hass)


def asking_entry(
    *recipients: str, asking: bool = True, remind_after: int = 0
) -> MockConfigEntry:
    """Return an entry with one tracker that asks the given persons."""
    return make_entry(
        make_subentry(
            TRACKER_A,
            "Kid",
            **{
                CONF_ASK_ON_DEPARTURE: asking,
                CONF_REMIND_AFTER: remind_after,
                CONF_NOTIFY_PERSONS: list(recipients),
            },
        ),
        persons=[PERSON_A, PERSON_B],
    )


async def test_an_entry_without_a_tracker_is_reported(hass: HomeAssistant) -> None:
    """An entry whose tracker form was closed says where the button is."""
    await set_person(hass, PERSON_A, [DABO53CK_PHONE])
    await setup_entry(hass, make_entry())

    current = issues(hass)
    assert set(current) == {issue_id(ISSUE_NO_TRACKER)}

    issue = current[issue_id(ISSUE_NO_TRACKER)]
    assert issue.translation_key == ISSUE_NO_TRACKER
    assert issue.translation_placeholders == {}
    # Repair issues have no informational severity, so a hint is a warning.
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.is_fixable is False
    assert issue.is_persistent is False


async def test_adding_a_tracker_clears_the_no_tracker_issue(
    hass: HomeAssistant,
) -> None:
    """The hint goes away with the first tracker, the reload re-checks."""
    await set_person(hass, PERSON_A, [DABO53CK_PHONE])
    entry = make_entry()
    await setup_entry(hass, entry)
    assert issue_id(ISSUE_NO_TRACKER) in issues(hass)

    hass.config_entries.async_add_subentry(
        entry,
        ConfigSubentry(
            data={},
            subentry_id=TRACKER_A,
            subentry_type=SUBENTRY_TYPE_TRACKER,
            title="Kid",
            unique_id=None,
        ),
    )
    await hass.async_block_till_done()

    # The new tracker is not assigned to a person yet, which is the next hint.
    assert set(issues(hass)) == {issue_id(ISSUE_TRACKER_NOT_ASSIGNED, TRACKER_A)}


async def test_unloading_clears_the_no_tracker_issue(hass: HomeAssistant) -> None:
    """An entry that is not loaded has no hint either."""
    await set_person(hass, PERSON_A, [DABO53CK_PHONE])
    entry = make_entry()
    await setup_entry(hass, entry)
    assert issues(hass)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert issues(hass) == {}


async def test_no_tracker_is_not_reported_before_the_start(hass: HomeAssistant) -> None:
    """The hint waits for the start like every other check."""
    hass.set_state(CoreState.not_running)
    await setup_entry(hass, make_entry())

    assert issues(hass) == {}

    hass.set_state(CoreState.running)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()

    assert issue_id(ISSUE_NO_TRACKER) in issues(hass)


async def test_a_tracker_without_a_person_is_reported(
    hass: HomeAssistant, tracker_entry: MockConfigEntry
) -> None:
    """Every tracker that no person follows gets its own issue."""
    await set_person(hass, PERSON_A, [DABO53CK_PHONE])
    await setup_entry(hass, tracker_entry)

    current = issues(hass)
    assert set(current) == {
        issue_id(ISSUE_TRACKER_NOT_ASSIGNED, TRACKER_A),
        issue_id(ISSUE_TRACKER_NOT_ASSIGNED, TRACKER_B),
    }

    issue = current[issue_id(ISSUE_TRACKER_NOT_ASSIGNED, TRACKER_A)]
    assert issue.translation_key == ISSUE_TRACKER_NOT_ASSIGNED
    assert issue.translation_placeholders == {
        "name": "Kid",
        "entity_id": TRACKER_A_ENTITY,
    }
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.is_fixable is False
    assert issue.is_persistent is False


async def test_assigning_a_tracker_clears_the_issue(
    hass: HomeAssistant, tracker_entry: MockConfigEntry
) -> None:
    """The issue follows the assignment in both directions."""
    await set_person(hass, PERSON_A, [DABO53CK_PHONE])
    await setup_entry(hass, tracker_entry)
    assert issue_id(ISSUE_TRACKER_NOT_ASSIGNED, TRACKER_A) in issues(hass)

    await set_person(hass, PERSON_KID, [TRACKER_A_ENTITY])

    assert issue_id(ISSUE_TRACKER_NOT_ASSIGNED, TRACKER_A) not in issues(hass)
    # The other tracker is still waiting for a person of its own.
    assert issue_id(ISSUE_TRACKER_NOT_ASSIGNED, TRACKER_B) in issues(hass)

    await set_person(hass, PERSON_KID, [])

    assert issue_id(ISSUE_TRACKER_NOT_ASSIGNED, TRACKER_A) in issues(hass)


async def test_a_real_person_with_a_virtual_tracker_is_reported(
    hass: HomeAssistant, tracker_entry: MockConfigEntry
) -> None:
    """The self-reset hazard is reported when it happens after the setup."""
    await set_person(hass, PERSON_A, [DABO53CK_PHONE])
    await setup_entry(hass, tracker_entry)

    await set_person(hass, PERSON_A, [DABO53CK_PHONE, TRACKER_A_ENTITY])

    hazard = issue_id(
        ISSUE_REAL_PERSON_HAS_VIRTUAL_TRACKER, person_key(PERSON_A), TRACKER_A
    )
    current = issues(hass)
    assert hazard in current
    assert current[hazard].translation_placeholders == {
        "person": PERSON_A,
        "tracker": TRACKER_A_ENTITY,
    }
    # The tracker is assigned, even though it is assigned to the wrong person.
    assert issue_id(ISSUE_TRACKER_NOT_ASSIGNED, TRACKER_A) not in current

    # A person who simply comes home changes nothing.
    await set_person(hass, PERSON_A, [DABO53CK_PHONE, TRACKER_A_ENTITY], STATE_HOME)
    assert hazard in issues(hass)

    await set_person(hass, PERSON_A, [DABO53CK_PHONE], STATE_HOME)
    assert hazard not in issues(hass)


async def test_a_missing_real_person_is_reported(
    hass: HomeAssistant, tracker_entry: MockConfigEntry
) -> None:
    """A configured real person without an entity is reported."""
    await setup_entry(hass, tracker_entry)

    missing = issue_id(ISSUE_REAL_PERSON_MISSING, person_key(PERSON_A))
    current = issues(hass)
    assert missing in current
    assert current[missing].translation_placeholders == {"person": PERSON_A}

    await set_person(hass, PERSON_A, [DABO53CK_PHONE])

    assert missing not in issues(hass)


async def test_nothing_is_reported_before_home_assistant_has_started(
    hass: HomeAssistant, tracker_entry: MockConfigEntry
) -> None:
    """The persons of a starting instance are not there yet, and not judged."""
    hass.set_state(CoreState.not_running)

    await setup_entry(hass, tracker_entry)

    assert issues(hass) == {}

    # The person component is set up after this integration and brings the
    # states along, one of them with a virtual tracker already assigned.
    await set_person(hass, PERSON_A, [DABO53CK_PHONE])
    await set_person(hass, PERSON_KID, [TRACKER_A_ENTITY])
    assert issues(hass) == {}

    hass.set_state(CoreState.running)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()

    assert set(issues(hass)) == {issue_id(ISSUE_TRACKER_NOT_ASSIGNED, TRACKER_B)}


async def test_unloading_clears_the_issues(
    hass: HomeAssistant, tracker_entry: MockConfigEntry
) -> None:
    """An entry that is not loaded has no issues."""
    await setup_entry(hass, tracker_entry)
    assert issues(hass)

    assert await hass.config_entries.async_unload(tracker_entry.entry_id)
    await hass.async_block_till_done()

    assert issues(hass) == {}


async def test_a_recipient_without_a_phone_is_reported(hass: HomeAssistant) -> None:
    """Somebody who is asked but cannot be reached is reported, once.

    The issue goes away as soon as the phone registers: a Companion App that
    is set up after Home Assistant started brings its notify service with it.
    """
    await set_person(hass, PERSON_A, [DABO53CK_PHONE], user_id=USER_A)
    await set_person(hass, PERSON_B, [DABO53CK_PHONE])
    await set_person(hass, PERSON_KID, [TRACKER_A_ENTITY])
    await setup_entry(hass, asking_entry(PERSON_A))

    reported = issue_id(ISSUE_RECIPIENT_WITHOUT_PHONE, person_key(PERSON_A))
    current = issues(hass)
    assert reported in current
    issue = current[reported]
    assert issue.translation_key == ISSUE_RECIPIENT_WITHOUT_PHONE
    assert issue.translation_placeholders == {"person": PERSON_A, "tracker": "Kid"}
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.is_fixable is False
    assert issue.is_persistent is False

    add_phone(hass, "dabo53ck's Phone", USER_A)
    async_mock_service(hass, NOTIFY_DOMAIN, PHONE_A)
    await hass.async_block_till_done()

    assert reported not in issues(hass)


async def test_a_recipient_with_a_phone_is_not_reported(hass: HomeAssistant) -> None:
    """A person whose phone can be reached is fine."""
    await set_person(hass, PERSON_A, [DABO53CK_PHONE], user_id=USER_A)
    await set_person(hass, PERSON_B, [DABO53CK_PHONE])
    await set_person(hass, PERSON_KID, [TRACKER_A_ENTITY])
    add_phone(hass, "dabo53ck's Phone", USER_A)
    async_mock_service(hass, NOTIFY_DOMAIN, PHONE_A)

    await setup_entry(hass, asking_entry(PERSON_A))

    assert issues(hass) == {}


async def test_a_recipient_of_a_tracker_that_asks_nothing_is_not_reported(
    hass: HomeAssistant,
) -> None:
    """Neither prompt nor reminder means nothing is ever sent."""
    await set_person(hass, PERSON_A, [DABO53CK_PHONE], user_id=USER_A)
    await set_person(hass, PERSON_B, [DABO53CK_PHONE])
    await set_person(hass, PERSON_KID, [TRACKER_A_ENTITY])

    await setup_entry(hass, asking_entry(PERSON_A, asking=False, remind_after=0))

    assert issues(hass) == {}


async def test_a_recipient_of_a_tracker_that_only_reminds_is_reported(
    hass: HomeAssistant,
) -> None:
    """A tracker that never asks still reminds, on the very same phones."""
    await set_person(hass, PERSON_A, [DABO53CK_PHONE], user_id=USER_A)
    await set_person(hass, PERSON_B, [DABO53CK_PHONE])
    await set_person(hass, PERSON_KID, [TRACKER_A_ENTITY])

    await setup_entry(hass, asking_entry(PERSON_A, asking=False, remind_after=24))

    reported = issue_id(ISSUE_RECIPIENT_WITHOUT_PHONE, person_key(PERSON_A))
    current = issues(hass)
    assert reported in current
    assert current[reported].translation_key == ISSUE_RECIPIENT_WITHOUT_PHONE
    assert current[reported].translation_placeholders == {
        "person": PERSON_A,
        "tracker": "Kid",
    }


async def test_turning_the_reminder_off_clears_the_issue(hass: HomeAssistant) -> None:
    """The last question going away clears it - without reloading the entry.

    `remind_after` is one of the options an entity writes, so the change never
    reaches the issues through a reload: the update listener has to re-check.
    """
    await set_person(hass, PERSON_A, [DABO53CK_PHONE], user_id=USER_A)
    await set_person(hass, PERSON_B, [DABO53CK_PHONE])
    await set_person(hass, PERSON_KID, [TRACKER_A_ENTITY])
    entry = asking_entry(PERSON_A, asking=False, remind_after=24)
    await setup_entry(hass, entry)
    assert issue_id(ISSUE_RECIPIENT_WITHOUT_PHONE, person_key(PERSON_A)) in issues(hass)

    loaded = entry.runtime_data
    subentry = entry.subentries[TRACKER_A]
    hass.config_entries.async_update_subentry(
        entry, subentry, data={**subentry.data, CONF_REMIND_AFTER: 0}
    )
    await hass.async_block_till_done()

    assert issues(hass) == {}
    # Same runtime data: the entry stayed loaded through the change.
    assert entry.runtime_data is loaded


async def test_turning_the_prompt_off_clears_the_issue(hass: HomeAssistant) -> None:
    """The ask option alone still decides for a tracker that never reminds."""
    await set_person(hass, PERSON_A, [DABO53CK_PHONE], user_id=USER_A)
    await set_person(hass, PERSON_B, [DABO53CK_PHONE])
    await set_person(hass, PERSON_KID, [TRACKER_A_ENTITY])
    entry = asking_entry(PERSON_A)
    await setup_entry(hass, entry)
    assert issue_id(ISSUE_RECIPIENT_WITHOUT_PHONE, person_key(PERSON_A)) in issues(hass)

    loaded = entry.runtime_data
    subentry = entry.subentries[TRACKER_A]
    hass.config_entries.async_update_subentry(
        entry, subentry, data={**subentry.data, CONF_ASK_ON_DEPARTURE: False}
    )
    await hass.async_block_till_done()

    assert issues(hass) == {}
    assert entry.runtime_data is loaded


async def test_a_recipient_who_is_not_a_real_person_is_not_reported(
    hass: HomeAssistant,
) -> None:
    """A recipient who is not a real person is dropped, not reported."""
    await set_person(hass, PERSON_A, [DABO53CK_PHONE], user_id=USER_A)
    await set_person(hass, PERSON_B, [DABO53CK_PHONE])
    await set_person(hass, PERSON_KID, [TRACKER_A_ENTITY])
    add_phone(hass, "dabo53ck's Phone", USER_A)
    async_mock_service(hass, NOTIFY_DOMAIN, PHONE_A)

    entry = asking_entry(PERSON_A, PERSON_KID)
    await setup_entry(hass, entry)

    assert issues(hass) == {}


async def test_removing_a_tracker_clears_its_issue(
    hass: HomeAssistant, tracker_entry: MockConfigEntry
) -> None:
    """A tracker that is gone takes its issue with it."""
    await set_person(hass, PERSON_A, [DABO53CK_PHONE])
    await setup_entry(hass, tracker_entry)
    assert issue_id(ISSUE_TRACKER_NOT_ASSIGNED, TRACKER_B) in issues(hass)

    hass.config_entries.async_remove_subentry(tracker_entry, TRACKER_B)
    await hass.async_block_till_done()

    assert set(issues(hass)) == {issue_id(ISSUE_TRACKER_NOT_ASSIGNED, TRACKER_A)}


# --- Sources that no longer exist --------------------------------------------

BUTTON = "event.kid_button"
TAG = "device_tracker.kid_tag"
WIFI = "binary_sensor.kid_tablet_wifi"
ADDRESS = "AA:BB:CC:11:22:33"


def source_entry(**data: object) -> MockConfigEntry:
    """Return an entry whose first tracker follows the given sources."""
    return make_entry(make_subentry(TRACKER_A, "Kid", **data))


async def quiet_household(hass: HomeAssistant) -> None:
    """Set up the persons so that no other issue is raised."""
    await set_person(hass, PERSON_A, [DABO53CK_PHONE])
    await set_person(hass, PERSON_KID, [TRACKER_A_ENTITY])


def register(hass: HomeAssistant, entity_id: str) -> None:
    """Add an entity of another integration to the entity registry."""
    domain, object_id = entity_id.split(".")
    er.async_get(hass).async_get_or_create(
        domain, "test", object_id, suggested_object_id=object_id
    )


async def test_a_deleted_button_source_is_reported(hass: HomeAssistant) -> None:
    """A button whose entity is deleted is named in an issue of its tracker."""
    await quiet_household(hass)
    register(hass, BUTTON)
    hass.states.async_set(BUTTON, STATE_UNKNOWN)
    await setup_entry(hass, source_entry(**{CONF_BUTTON_SOURCES: [BUTTON]}))
    assert issues(hass) == {}

    er.async_get(hass).async_remove(BUTTON)
    hass.states.async_remove(BUTTON)
    await hass.async_block_till_done()

    reported = issue_id(ISSUE_SOURCE_MISSING, TRACKER_A)
    current = issues(hass)
    assert set(current) == {reported}
    issue = current[reported]
    assert issue.translation_key == ISSUE_SOURCE_MISSING
    assert issue.translation_placeholders == {"name": "Kid", "sources": BUTTON}
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.is_fixable is False
    assert issue.is_persistent is False


async def test_a_renamed_presence_source_is_reported(hass: HomeAssistant) -> None:
    """Renaming leaves nothing under the old entity ID, in state or registry."""
    await quiet_household(hass)
    register(hass, TAG)
    hass.states.async_set(TAG, STATE_HOME)
    await setup_entry(hass, source_entry(**{CONF_PRESENCE_SOURCES: [TAG]}))

    # The state goes first; the registry entry alone still keeps it existing.
    hass.states.async_remove(TAG)
    await hass.async_block_till_done()
    assert issues(hass) == {}

    er.async_get(hass).async_update_entity(TAG, new_entity_id="device_tracker.tag")
    await hass.async_block_till_done()

    reported = issue_id(ISSUE_SOURCE_MISSING, TRACKER_A)
    current = issues(hass)
    assert set(current) == {reported}
    assert current[reported].translation_placeholders["sources"] == TAG


async def test_a_source_without_a_registry_entry_is_reported(
    hass: HomeAssistant,
) -> None:
    """An entity without a unique ID only has a state, and it can go too."""
    await quiet_household(hass)
    hass.states.async_set(WIFI, STATE_ON)
    await setup_entry(hass, source_entry(**{CONF_PRESENCE_SOURCES: [WIFI]}))
    assert issues(hass) == {}

    hass.states.async_remove(WIFI)
    await hass.async_block_till_done()

    assert set(issues(hass)) == {issue_id(ISSUE_SOURCE_MISSING, TRACKER_A)}

    # Back again: the issue goes with it.
    hass.states.async_set(WIFI, STATE_OFF)
    await hass.async_block_till_done()

    assert issues(hass) == {}


@pytest.mark.parametrize("state", [STATE_UNAVAILABLE, STATE_UNKNOWN, None])
async def test_a_source_that_still_exists_is_not_reported(
    hass: HomeAssistant, state: str | None
) -> None:
    """Unavailable, unknown or registered without a state is not missing."""
    await quiet_household(hass)
    register(hass, TAG)
    if state is not None:
        hass.states.async_set(TAG, state)

    await setup_entry(hass, source_entry(**{CONF_PRESENCE_SOURCES: [TAG]}))

    assert issues(hass) == {}


async def test_a_bluetooth_source_is_never_reported(hass: HomeAssistant) -> None:
    """An address that is never heard is away, not missing."""
    await quiet_household(hass)

    await setup_entry(hass, source_entry(**{CONF_BLE_SOURCES: [ADDRESS]}))

    assert issues(hass) == {}


async def test_one_issue_names_every_missing_source_of_a_tracker(
    hass: HomeAssistant,
) -> None:
    """Buttons first, then presence sources, in the order of the form."""
    await quiet_household(hass)
    await set_person(hass, "person.granny", [TRACKER_B_ENTITY])
    hass.states.async_set(TAG, STATE_HOME)
    entry = make_entry(
        make_subentry(
            TRACKER_A,
            "Kid",
            **{
                CONF_BUTTON_SOURCES: [BUTTON],
                CONF_PRESENCE_SOURCES: [WIFI, TAG],
                CONF_BLE_SOURCES: [ADDRESS],
            },
        ),
        make_subentry(TRACKER_B, "Granny", **{CONF_PRESENCE_SOURCES: [WIFI]}),
    )

    await setup_entry(hass, entry)

    kid = issue_id(ISSUE_SOURCE_MISSING, TRACKER_A)
    granny = issue_id(ISSUE_SOURCE_MISSING, TRACKER_B)
    current = issues(hass)
    assert set(current) == {kid, granny}
    assert current[kid].translation_placeholders == {
        "name": "Kid",
        "sources": f"{BUTTON}, {WIFI}",
    }
    assert current[granny].translation_placeholders == {
        "name": "Granny",
        "sources": WIFI,
    }


async def test_removing_the_source_in_the_form_clears_the_issue(
    hass: HomeAssistant,
) -> None:
    """Saving the form re-checks - without reloading the entry."""
    await quiet_household(hass)
    entry = source_entry(**{CONF_BUTTON_SOURCES: [BUTTON]})
    await setup_entry(hass, entry)
    assert set(issues(hass)) == {issue_id(ISSUE_SOURCE_MISSING, TRACKER_A)}

    loaded = entry.runtime_data
    subentry = entry.subentries[TRACKER_A]
    data = {
        key: value for key, value in subentry.data.items() if key != CONF_BUTTON_SOURCES
    }
    hass.config_entries.async_update_subentry(entry, subentry, data=data)
    await hass.async_block_till_done()

    assert issues(hass) == {}
    assert entry.runtime_data is loaded


async def test_adding_a_missing_source_in_the_form_is_reported(
    hass: HomeAssistant,
) -> None:
    """A source picked in the form is checked as soon as it is saved."""
    await quiet_household(hass)
    entry = source_entry()
    await setup_entry(hass, entry)
    assert issues(hass) == {}

    subentry = entry.subentries[TRACKER_A]
    hass.config_entries.async_update_subentry(
        entry, subentry, data={**subentry.data, CONF_PRESENCE_SOURCES: [TAG]}
    )
    await hass.async_block_till_done()

    assert set(issues(hass)) == {issue_id(ISSUE_SOURCE_MISSING, TRACKER_A)}


async def test_a_source_that_is_registered_again_clears_the_issue(
    hass: HomeAssistant,
) -> None:
    """A registry entry under the old entity ID is enough to exist again."""
    await quiet_household(hass)
    await setup_entry(hass, source_entry(**{CONF_BUTTON_SOURCES: [BUTTON]}))
    assert set(issues(hass)) == {issue_id(ISSUE_SOURCE_MISSING, TRACKER_A)}

    register(hass, BUTTON)
    await hass.async_block_till_done()

    assert issues(hass) == {}


async def test_a_missing_source_is_not_reported_before_the_start(
    hass: HomeAssistant,
) -> None:
    """The integration of a source may simply not be set up yet."""
    hass.set_state(CoreState.not_running)
    await setup_entry(hass, source_entry(**{CONF_PRESENCE_SOURCES: [TAG]}))
    await quiet_household(hass)

    assert issues(hass) == {}

    hass.set_state(CoreState.running)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()

    assert set(issues(hass)) == {issue_id(ISSUE_SOURCE_MISSING, TRACKER_A)}


# --- Issue IDs ----------------------------------------------------------------


async def test_no_issue_id_carries_an_entity_id(hass: HomeAssistant) -> None:
    """Persons are hashed and trackers named by subentry, in every issue ID.

    Home Assistant puts the issue IDs into every diagnostics download, and an
    entity ID is usually a name. The placeholders still name both.
    """
    await set_person(hass, PERSON_A, [DABO53CK_PHONE, TRACKER_A_ENTITY])
    entry = make_entry(
        make_subentry(
            TRACKER_A,
            "Kid",
            **{
                CONF_ASK_ON_DEPARTURE: True,
                CONF_NOTIFY_PERSONS: [PERSON_A],
                CONF_BUTTON_SOURCES: ["event.kid_button"],
            },
        ),
        make_subentry(TRACKER_B, "Granny"),
        persons=[PERSON_A, PERSON_B],
    )

    await setup_entry(hass, entry)

    current = issues(hass)
    assert set(current) == {
        issue_id(
            ISSUE_REAL_PERSON_HAS_VIRTUAL_TRACKER, person_key(PERSON_A), TRACKER_A
        ),
        issue_id(ISSUE_RECIPIENT_WITHOUT_PHONE, person_key(PERSON_A)),
        issue_id(ISSUE_REAL_PERSON_MISSING, person_key(PERSON_B)),
        issue_id(ISSUE_TRACKER_NOT_ASSIGNED, TRACKER_B),
        issue_id(ISSUE_SOURCE_MISSING, TRACKER_A),
    }
    for reported in current:
        for forbidden in ("person.", "device_tracker.", "event.", "kid", "granny"):
            assert forbidden not in reported.lower(), reported
    assert person_key(PERSON_A) == person_key(PERSON_A.upper())
    assert len(person_key(PERSON_A)) == 10
    assert person_key(PERSON_A) != person_key(PERSON_B)
    hazard = current[
        issue_id(ISSUE_REAL_PERSON_HAS_VIRTUAL_TRACKER, person_key(PERSON_A), TRACKER_A)
    ]
    assert hazard.translation_placeholders == {
        "person": PERSON_A,
        "tracker": TRACKER_A_ENTITY,
    }


async def test_an_issue_id_of_the_old_format_is_cleaned_up(
    hass: HomeAssistant, tracker_entry: MockConfigEntry
) -> None:
    """An issue of an older version, with an entity ID in its ID, goes away.

    Home Assistant keeps the issues of a previous run in its registry, so the
    first check after the update finds them under their old IDs.
    """
    old = [
        issue_id(ISSUE_REAL_PERSON_MISSING, PERSON_A),
        issue_id(ISSUE_RECIPIENT_WITHOUT_PHONE, PERSON_A),
        issue_id(ISSUE_REAL_PERSON_HAS_VIRTUAL_TRACKER, PERSON_A, TRACKER_A_ENTITY),
    ]
    for reported in old:
        ir.async_create_issue(
            hass,
            DOMAIN,
            reported,
            is_fixable=False,
            is_persistent=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_REAL_PERSON_MISSING,
            translation_placeholders={"person": PERSON_A},
        )

    await setup_entry(hass, tracker_entry)

    current = issues(hass)
    assert not set(old) & set(current)
    assert issue_id(ISSUE_REAL_PERSON_MISSING, person_key(PERSON_A)) in current
