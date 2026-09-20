"""Tests for the repair issues of a config entry."""

from __future__ import annotations

from collections.abc import Iterable

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.virtual_presence_tracker.const import (
    ATTR_DEVICE_TRACKERS,
    ATTR_USER_ID,
    CONF_ASK_ON_DEPARTURE,
    CONF_DEVICE_NAME,
    CONF_NOTIFY_PERSONS,
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
    ISSUE_TRACKER_NOT_ASSIGNED,
)
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, STATE_HOME, STATE_NOT_HOME
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.helpers import issue_registry as ir

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


def asking_entry(*recipients: str, asking: bool = True) -> MockConfigEntry:
    """Return an entry with one tracker that asks the given persons."""
    return make_entry(
        make_subentry(
            TRACKER_A,
            "Kid",
            **{
                CONF_ASK_ON_DEPARTURE: asking,
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

    hazard = issue_id(ISSUE_REAL_PERSON_HAS_VIRTUAL_TRACKER, PERSON_A, TRACKER_A_ENTITY)
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

    missing = issue_id(ISSUE_REAL_PERSON_MISSING, PERSON_A)
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

    reported = issue_id(ISSUE_RECIPIENT_WITHOUT_PHONE, PERSON_A)
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


async def test_a_recipient_of_a_tracker_that_does_not_ask_is_not_reported(
    hass: HomeAssistant,
) -> None:
    """Without the prompt nothing is ever sent, so nothing is missing."""
    await set_person(hass, PERSON_A, [DABO53CK_PHONE], user_id=USER_A)
    await set_person(hass, PERSON_B, [DABO53CK_PHONE])
    await set_person(hass, PERSON_KID, [TRACKER_A_ENTITY])

    await setup_entry(hass, asking_entry(PERSON_A, asking=False))

    assert issues(hass) == {}


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
