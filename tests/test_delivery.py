"""Tests for the built-in delivery of the prompt to the Companion App."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.virtual_presence_tracker.const import (
    ATTR_USER_ID,
    CONF_ANSWER_TIMEOUT,
    CONF_ASK_ON_DEPARTURE,
    CONF_DEVICE_NAME,
    CONF_NOTIFY_ON_EXPIRY,
    CONF_NOTIFY_PERSONS,
    CONF_PERSONS,
    CONF_USER_ID,
    DOMAIN,
    EVENT_NOTIFICATION_ACTION,
    MOBILE_APP_DOMAIN,
    NOTIFICATION_ICON,
    NOTIFICATION_ICON_FILE,
    NOTIFY_DOMAIN,
    STORAGE_KEY_PREFIX,
    STORAGE_VERSION,
    SUBENTRY_TYPE_TRACKER,
)
from homeassistant.components.brands.const import ALLOWED_IMAGES
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.const import SERVICE_TURN_ON, STATE_HOME, STATE_NOT_HOME
from homeassistant.core import Context, HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

ENTRY_ID = "01JVPT0000000000000000ENTRY"
STORE_KEY = f"{STORAGE_KEY_PREFIX}.{ENTRY_ID}"

TRACKER_A = "01JVPT000000000000000TRACKA"
SWITCH_A = "switch.kid_at_home"

PERSON_A = "person.dabo53ck"
PERSON_B = "person.king53ck"
USER_A = "user-dabo53ck"
USER_B = "user-king53ck"

PHONE_A = "mobile_app_dabo53ck_s_phone"
PHONE_A2 = "mobile_app_dabo53ck_tablet"
PHONE_B = "mobile_app_king53ck_phone"

BRAND_DIR = Path(__file__).parents[1] / "custom_components" / DOMAIN / "brand"


def make_entry(
    *,
    persons: list[str] | None = None,
    recipients: list[str] | None = None,
    asking: bool = True,
    notify_on_expiry: bool = False,
    timeout: int = 10,
) -> MockConfigEntry:
    """Return an entry with one tracker that asks and notifies."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Virtual Presence Tracker",
        entry_id=ENTRY_ID,
        data={CONF_PERSONS: persons if persons is not None else [PERSON_A]},
        subentries_data=[
            {
                "data": {
                    CONF_ASK_ON_DEPARTURE: asking,
                    CONF_ANSWER_TIMEOUT: timeout,
                    CONF_NOTIFY_PERSONS: (
                        recipients if recipients is not None else [PERSON_A]
                    ),
                    CONF_NOTIFY_ON_EXPIRY: notify_on_expiry,
                },
                "subentry_id": TRACKER_A,
                "subentry_type": SUBENTRY_TYPE_TRACKER,
                "title": "Kid",
                "unique_id": None,
            }
        ],
    )


def add_phone(hass: HomeAssistant, device_name: str, user_id: str) -> None:
    """Register a Companion App phone of a user."""
    MockConfigEntry(
        domain=MOBILE_APP_DOMAIN,
        title=device_name,
        data={CONF_DEVICE_NAME: device_name, CONF_USER_ID: user_id},
    ).add_to_hass(hass)


def add_person(
    hass: HomeAssistant,
    entity_id: str,
    state: str = STATE_HOME,
    user_id: str | None = None,
) -> None:
    """Add a person state, with the user it belongs to."""
    hass.states.async_set(entity_id, state, {ATTR_USER_ID: user_id} if user_id else {})


def add_dabo53ck(hass: HomeAssistant, state: str = STATE_HOME) -> list[ServiceCall]:
    """Add dabo53ck, his phone and the notify service of that phone."""
    add_person(hass, PERSON_A, state, USER_A)
    add_phone(hass, "dabo53ck's Phone", USER_A)
    return async_mock_service(hass, NOTIFY_DOMAIN, PHONE_A)


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> MockConfigEntry:
    """Add a config entry to hass and set it up."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def unload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Unload an entry so that no prompt timer is left running."""
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def move_person(
    hass: HomeAssistant, entity_id: str, state: str, user_id: str | None = None
) -> None:
    """Move a person and let the messages that follow go out."""
    add_person(hass, entity_id, state, user_id)
    await settle(hass)


async def empty_the_house(hass: HomeAssistant) -> None:
    """Send the only real person away and let the messages go out."""
    await move_person(hass, PERSON_A, STATE_NOT_HOME, USER_A)


async def settle(hass: HomeAssistant) -> None:
    """Wait for the background tasks the delivery sends its messages in."""
    await hass.async_block_till_done(wait_background_tasks=True)


def prompt_id_of(call: ServiceCall) -> str:
    """Return the prompt ID a notification carries in its tag."""
    tag: str = call.data["data"]["tag"]
    return tag.removeprefix("vpt_")


async def answer_from_phone(
    hass: HomeAssistant, action: str, user_id: str | None = USER_A
) -> None:
    """Fire the event a tapped notification button produces."""
    hass.bus.async_fire(
        EVENT_NOTIFICATION_ACTION,
        {"action": action},
        context=Context(user_id=user_id),
    )
    await settle(hass)


async def test_the_prompt_is_sent_to_the_phone(hass: HomeAssistant) -> None:
    """The question arrives with its buttons and its delivery hints."""
    calls = add_dabo53ck(hass)
    entry = await setup_entry(hass, make_entry(timeout=15))

    await empty_the_house(hass)

    assert len(calls) == 1
    data = calls[0].data
    assert data["title"] == "Is Kid home alone?"
    assert data["message"] == "Nobody else is home. Answer within 15 minutes."
    prompt_id = prompt_id_of(calls[0])
    assert data["data"]["tag"] == f"vpt_{prompt_id}"
    assert data["data"]["actions"] == [
        {"action": f"VPT_YES_{prompt_id}", "title": "Yes, home"},
        {"action": f"VPT_NO_{prompt_id}", "title": "No"},
    ]
    # Android wakes the phone up and drops the message when the time is over.
    assert data["data"]["ttl"] == 0
    assert data["data"]["priority"] == "high"
    assert data["data"]["timeout"] == 15 * 60
    # iOS says the same thing in its own words.
    assert data["data"]["push"] == {"interruption-level": "time-sensitive"}

    await unload(hass, entry)


async def test_the_message_carries_the_integration_icon(hass: HomeAssistant) -> None:
    """The question shows the integration's icon, the clearing shows nothing."""
    calls = add_dabo53ck(hass)
    await setup_entry(hass, make_entry())

    await empty_the_house(hass)

    # The icon stands beside the message in place of the app's own. It is not
    # an attachment, so no `image` goes along with it - that would show the
    # very same picture a second time.
    assert calls[0].data["data"]["icon_url"] == NOTIFICATION_ICON
    assert "image" not in calls[0].data["data"]

    await answer_from_phone(hass, f"VPT_YES_{prompt_id_of(calls[0])}")

    # Taking a message off a phone is not a message with an icon.
    assert "icon_url" not in calls[1].data["data"]
    assert "image" not in calls[1].data["data"]


def test_the_icon_of_the_message_is_served_by_home_assistant() -> None:
    """The icon names a brand image that is really there.

    Home Assistant serves the `brand` folder of a custom integration under
    /api/brands, but only under the file names the brands component knows.
    """
    assert NOTIFICATION_ICON_FILE in ALLOWED_IMAGES
    assert (
        NOTIFICATION_ICON
        == f"/api/brands/integration/{DOMAIN}/{NOTIFICATION_ICON_FILE}"
    )
    assert (BRAND_DIR / NOTIFICATION_ICON_FILE).is_file()


async def test_the_prompt_is_sent_in_german(hass: HomeAssistant) -> None:
    """A German instance asks in German."""
    hass.config.language = "de-DE"
    calls = add_dabo53ck(hass)
    entry = await setup_entry(hass, make_entry(timeout=1))

    await empty_the_house(hass)

    assert calls[0].data["title"] == "Ist Kid alleine zu Hause?"
    # One minute is not "1 Minuten".
    assert (
        calls[0].data["message"]
        == "Es ist niemand sonst zu Hause. Antworte innerhalb von einer Minute."
    )
    assert [action["title"] for action in calls[0].data["data"]["actions"]] == [
        "Ja, ist da",
        "Nein",
    ]

    await unload(hass, entry)


async def test_every_phone_of_a_person_is_asked(hass: HomeAssistant) -> None:
    """A person with two registered phones is asked on both."""
    calls = add_dabo53ck(hass)
    add_phone(hass, "dabo53ck Tablet", USER_A)
    tablet = async_mock_service(hass, NOTIFY_DOMAIN, PHONE_A2)
    entry = await setup_entry(hass, make_entry())

    await empty_the_house(hass)

    assert len(calls) == 1
    assert len(tablet) == 1
    assert prompt_id_of(calls[0]) == prompt_id_of(tablet[0])

    await unload(hass, entry)


def add_king53ck(hass: HomeAssistant, state: str = STATE_HOME) -> list[ServiceCall]:
    """Add king53ck, her phone and the notify service of that phone."""
    add_person(hass, PERSON_B, state, USER_B)
    add_phone(hass, "king53ck Phone", USER_B)
    return async_mock_service(hass, NOTIFY_DOMAIN, PHONE_B)


async def empty_the_house_of_two(hass: HomeAssistant) -> None:
    """Send both real persons away, king53ck last."""
    await move_person(hass, PERSON_A, STATE_NOT_HOME, USER_A)
    await move_person(hass, PERSON_B, STATE_NOT_HOME, USER_B)


async def test_two_recipients_are_asked(hass: HomeAssistant) -> None:
    """Every chosen person is asked on their own phone."""
    calls = add_dabo53ck(hass)
    king53ck = add_king53ck(hass)
    entry = await setup_entry(
        hass,
        make_entry(persons=[PERSON_A, PERSON_B], recipients=[PERSON_A, PERSON_B]),
    )

    await empty_the_house_of_two(hass)

    assert len(calls) == 1
    assert len(king53ck) == 1

    await unload(hass, entry)


async def test_a_person_without_a_user_is_not_asked(hass: HomeAssistant) -> None:
    """Without a Home Assistant user there is no phone to find."""
    add_person(hass, PERSON_A, STATE_HOME)
    add_phone(hass, "dabo53ck's Phone", USER_A)
    calls = async_mock_service(hass, NOTIFY_DOMAIN, PHONE_A)
    entry = await setup_entry(hass, make_entry())

    await move_person(hass, PERSON_A, STATE_NOT_HOME)

    assert calls == []
    assert entry.runtime_data.manager.prompt_open(TRACKER_A) is True

    await unload(hass, entry)


async def test_a_phone_without_a_service_is_not_asked(hass: HomeAssistant) -> None:
    """A registration whose notify service does not exist is skipped."""
    add_person(hass, PERSON_A, STATE_HOME, USER_A)
    add_phone(hass, "dabo53ck's Phone", USER_A)
    other = async_mock_service(hass, NOTIFY_DOMAIN, PHONE_B)
    entry = await setup_entry(hass, make_entry())

    await empty_the_house(hass)

    assert other == []

    await unload(hass, entry)


async def test_a_phone_of_somebody_else_is_not_asked(hass: HomeAssistant) -> None:
    """The mapping goes by the user of the registration, not by the name."""
    calls = add_dabo53ck(hass)
    king53ck = add_king53ck(hass)
    entry = await setup_entry(hass, make_entry())

    await empty_the_house(hass)

    assert len(calls) == 1
    assert king53ck == []

    await unload(hass, entry)


async def test_without_recipients_nothing_is_sent(hass: HomeAssistant) -> None:
    """An empty selection leaves the prompt to the automations of the user."""
    calls = add_dabo53ck(hass)
    entry = await setup_entry(hass, make_entry(recipients=[]))

    await empty_the_house(hass)

    assert calls == []
    # The prompt itself is untouched by the choice.
    assert entry.runtime_data.manager.prompt_open(TRACKER_A) is True

    await unload(hass, entry)


async def test_without_the_prompt_nothing_is_sent(hass: HomeAssistant) -> None:
    """A tracker that does not ask has nothing to deliver."""
    calls = add_dabo53ck(hass)
    await setup_entry(hass, make_entry(asking=False))

    await empty_the_house(hass)

    assert calls == []


async def test_a_recipient_who_is_not_real_any_more_is_skipped(
    hass: HomeAssistant,
) -> None:
    """A recipient who lost their real-person status is quietly dropped."""
    calls = add_dabo53ck(hass)
    king53ck = add_king53ck(hass)
    entry = await setup_entry(
        hass,
        make_entry(persons=[PERSON_A, PERSON_B], recipients=[PERSON_A, PERSON_B]),
    )

    # king53ck is taken out of the real persons and stays a recipient of the
    # tracker: the reconfigure flow only touches the persons of the entry.
    hass.config_entries.async_update_entry(entry, data={CONF_PERSONS: [PERSON_A]})
    await hass.async_block_till_done()

    await empty_the_house(hass)

    assert len(calls) == 1
    assert king53ck == []
    assert entry.runtime_data.manager.prompt_open(TRACKER_A) is True

    await unload(hass, entry)


@pytest.mark.parametrize(
    ("prefix", "answer", "home"),
    [("VPT_YES_", "yes", True), ("VPT_NO_", "no", False)],
)
async def test_an_answer_from_the_phone_answers_the_prompt(
    hass: HomeAssistant, prefix: str, answer: str, home: bool
) -> None:
    """A tapped button answers the prompt and names who tapped it."""
    calls = add_dabo53ck(hass)
    entry = await setup_entry(hass, make_entry())

    await empty_the_house(hass)
    prompt_id = prompt_id_of(calls[0])

    await answer_from_phone(hass, f"{prefix}{prompt_id}")

    manager = entry.runtime_data.manager
    assert manager.prompt_open(TRACKER_A) is False
    assert manager.is_home(TRACKER_A) is home
    state = hass.states.get("event.kid_prompt")
    assert state.attributes["event_type"] == f"answered_{answer}"
    # The user of the phone is the person who answered.
    assert state.attributes["answered_by"] == PERSON_A
    # The question is taken off the phone.
    assert calls[1].data == {
        "message": "clear_notification",
        "data": {"tag": f"vpt_{prompt_id}"},
    }


async def test_an_answer_of_an_unknown_user_names_nobody(
    hass: HomeAssistant,
) -> None:
    """Without a person behind the user the answer stays anonymous."""
    calls = add_dabo53ck(hass)
    entry = await setup_entry(hass, make_entry())

    await empty_the_house(hass)
    await answer_from_phone(
        hass, f"VPT_YES_{prompt_id_of(calls[0])}", user_id="somebody-else"
    )

    assert entry.runtime_data.manager.is_home(TRACKER_A) is True
    assert hass.states.get("event.kid_prompt").attributes["answered_by"] is None


async def test_an_answer_without_a_user_names_nobody(hass: HomeAssistant) -> None:
    """An event without a user behind it still answers, anonymously."""
    calls = add_dabo53ck(hass)
    entry = await setup_entry(hass, make_entry())

    await empty_the_house(hass)
    await answer_from_phone(hass, f"VPT_NO_{prompt_id_of(calls[0])}", user_id=None)

    assert entry.runtime_data.manager.prompt_open(TRACKER_A) is False
    assert hass.states.get("event.kid_prompt").attributes["answered_by"] is None


async def test_an_action_without_a_name_is_ignored(hass: HomeAssistant) -> None:
    """An event whose action is not a string is not an answer."""
    add_dabo53ck(hass)
    entry = await setup_entry(hass, make_entry())

    await empty_the_house(hass)
    hass.bus.async_fire(EVENT_NOTIFICATION_ACTION, {"action": 42})
    await settle(hass)

    assert entry.runtime_data.manager.prompt_open(TRACKER_A) is True

    await unload(hass, entry)


@pytest.mark.parametrize(
    "action",
    [
        "VPT_YES_deadbeef",
        "VPT_MAYBE_abc",
        "SOMETHING_ELSE",
        "",
    ],
)
async def test_a_foreign_or_stale_answer_is_ignored(
    hass: HomeAssistant, action: str
) -> None:
    """Only an action that names an open prompt of this entry is acted on."""
    add_dabo53ck(hass)
    entry = await setup_entry(hass, make_entry())

    await empty_the_house(hass)
    await answer_from_phone(hass, action)

    manager = entry.runtime_data.manager
    assert manager.prompt_open(TRACKER_A) is True
    assert manager.is_home(TRACKER_A) is False

    await unload(hass, entry)


async def test_an_answer_after_the_prompt_is_ignored(hass: HomeAssistant) -> None:
    """The second phone to answer finds nothing left to answer."""
    calls = add_dabo53ck(hass)
    king53ck = add_king53ck(hass)
    entry = await setup_entry(
        hass,
        make_entry(persons=[PERSON_A, PERSON_B], recipients=[PERSON_A, PERSON_B]),
    )

    await empty_the_house_of_two(hass)
    prompt_id = prompt_id_of(calls[0])

    await answer_from_phone(hass, f"VPT_YES_{prompt_id}")
    # king53ck taps "no" a moment later, on the message that is already gone.
    await answer_from_phone(hass, f"VPT_NO_{prompt_id}", user_id=USER_B)

    manager = entry.runtime_data.manager
    assert manager.is_home(TRACKER_A) is True
    assert (
        hass.states.get("event.kid_prompt").attributes["event_type"] == "answered_yes"
    )
    # Both phones were cleared once, by the first answer.
    assert len(calls) == 2
    assert len(king53ck) == 2
    assert king53ck[1].data["message"] == "clear_notification"


async def test_the_service_answer_clears_the_phones(hass: HomeAssistant) -> None:
    """An answer through the action takes the message off the phones too."""
    calls = add_dabo53ck(hass)
    entry = await setup_entry(hass, make_entry())

    await empty_the_house(hass)
    prompt_id = prompt_id_of(calls[0])

    await hass.services.async_call(
        DOMAIN,
        "answer_prompt",
        {"entity_id": SWITCH_A, "answer": "no"},
        blocking=True,
    )
    await settle(hass)

    assert entry.runtime_data.manager.prompt_open(TRACKER_A) is False
    assert calls[1].data["data"]["tag"] == f"vpt_{prompt_id}"
    assert calls[1].data["message"] == "clear_notification"


async def open_prompt(hass: HomeAssistant) -> None:
    """Open the prompt of the tracker by hand and let the message go out."""
    await hass.services.async_call(
        DOMAIN, "open_prompt", {"entity_id": SWITCH_A}, blocking=True
    )
    await settle(hass)


async def test_a_prompt_opened_by_hand_is_sent_to_the_phone(
    hass: HomeAssistant,
) -> None:
    """The question reaches the phones however the prompt was opened.

    Not even for a tracker that never asks by itself: the recipients are what
    the delivery goes by, and the message is the same message.
    """
    calls = add_dabo53ck(hass)
    entry = await setup_entry(hass, make_entry(asking=False, timeout=15))

    await open_prompt(hass)

    assert len(calls) == 1
    assert calls[0].data["title"] == "Is Kid home alone?"
    assert calls[0].data["message"] == "Nobody else is home. Answer within 15 minutes."
    prompt_id = prompt_id_of(calls[0])
    assert calls[0].data["data"]["actions"] == [
        {"action": f"VPT_YES_{prompt_id}", "title": "Yes, home"},
        {"action": f"VPT_NO_{prompt_id}", "title": "No"},
    ]
    assert entry.runtime_data.manager.prompt_open(TRACKER_A) is True

    await unload(hass, entry)


@pytest.mark.parametrize(
    ("prefix", "answer", "home"),
    [("VPT_YES_", "yes", True), ("VPT_NO_", "no", False)],
)
async def test_a_prompt_opened_by_hand_is_answered_from_the_phone(
    hass: HomeAssistant, prefix: str, answer: str, home: bool
) -> None:
    """The buttons answer it like any other prompt, and clear it."""
    calls = add_dabo53ck(hass)
    entry = await setup_entry(hass, make_entry(asking=False))

    await open_prompt(hass)
    prompt_id = prompt_id_of(calls[0])

    await answer_from_phone(hass, f"{prefix}{prompt_id}")

    manager = entry.runtime_data.manager
    assert manager.prompt_open(TRACKER_A) is False
    assert manager.is_home(TRACKER_A) is home
    state = hass.states.get("event.kid_prompt")
    assert state.attributes["event_type"] == f"answered_{answer}"
    assert state.attributes["answered_by"] == PERSON_A
    assert calls[1].data == {
        "message": "clear_notification",
        "data": {"tag": f"vpt_{prompt_id}"},
    }


async def test_switching_on_takes_a_prompt_opened_by_hand_back(
    hass: HomeAssistant,
) -> None:
    """Switching the tracker on withdraws it and clears the phone."""
    calls = add_dabo53ck(hass)
    entry = await setup_entry(hass, make_entry(asking=False))

    await open_prompt(hass)

    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {"entity_id": SWITCH_A}, blocking=True
    )
    await settle(hass)

    manager = entry.runtime_data.manager
    assert manager.prompt_open(TRACKER_A) is False
    assert manager.is_home(TRACKER_A) is True
    state = hass.states.get("event.kid_prompt")
    assert state.attributes["event_type"] == "cancelled"
    assert state.attributes["reason"] == "switched_on"
    assert len(calls) == 2
    assert calls[1].data["message"] == "clear_notification"


async def test_a_withdrawn_prompt_clears_the_phone(hass: HomeAssistant) -> None:
    """Somebody coming home takes the question back."""
    calls = add_dabo53ck(hass)
    entry = await setup_entry(hass, make_entry())

    await empty_the_house(hass)
    await move_person(hass, PERSON_A, STATE_HOME, USER_A)

    assert entry.runtime_data.manager.prompt_open(TRACKER_A) is False
    assert len(calls) == 2
    assert calls[1].data["message"] == "clear_notification"


@pytest.mark.parametrize("notify_on_expiry", [False, True])
async def test_an_expired_prompt_clears_the_phone(
    hass: HomeAssistant, hass_storage: dict[str, Any], notify_on_expiry: bool
) -> None:
    """A prompt that ran out while Home Assistant was off is cleaned up.

    The tag comes from the persisted prompt ID, so the message a previous run
    left behind can still be named.
    """
    now = dt_util.utcnow()
    hass_storage[STORE_KEY] = {
        "version": STORAGE_VERSION,
        "minor_version": 1,
        "key": STORE_KEY,
        "data": {
            "trackers": {TRACKER_A: {"home": False, "since": None}},
            "prompts": {
                TRACKER_A: {
                    "prompt_id": "abc",
                    "started_at": (now - timedelta(hours=2)).isoformat(),
                    "expires_at": (now - timedelta(hours=1)).isoformat(),
                }
            },
        },
    }
    calls = add_dabo53ck(hass, STATE_NOT_HOME)

    await setup_entry(hass, make_entry(notify_on_expiry=notify_on_expiry))
    await settle(hass)

    assert calls[0].data == {
        "message": "clear_notification",
        "data": {"tag": "vpt_abc"},
    }
    if notify_on_expiry:
        assert calls[1].data["title"] == "No answer"
        assert calls[1].data["message"] == "No answer: Kid counts as not at home."
        # The notice is a message of its own, not a replacement of the
        # question, and it carries the integration's icon just like the
        # question did.
        assert calls[1].data["data"] == {
            "tag": "vpt_info_abc",
            "icon_url": NOTIFICATION_ICON,
        }
    else:
        assert len(calls) == 1


async def test_the_expiry_notice_is_not_sent_on_an_answer(
    hass: HomeAssistant,
) -> None:
    """Only an unanswered prompt produces the notice."""
    calls = add_dabo53ck(hass)
    entry = await setup_entry(hass, make_entry(notify_on_expiry=True))

    await empty_the_house(hass)
    await answer_from_phone(hass, f"VPT_NO_{prompt_id_of(calls[0])}")

    assert entry.runtime_data.manager.prompt_open(TRACKER_A) is False
    assert len(calls) == 2
    assert calls[1].data["message"] == "clear_notification"


async def test_a_failing_phone_does_not_stop_the_others(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """One phone that cannot be reached is logged, the prompt stays open."""
    add_person(hass, PERSON_A, STATE_HOME, USER_A)
    add_phone(hass, "dabo53ck's Phone", USER_A)
    add_phone(hass, "dabo53ck Tablet", USER_A)

    def boom(call: ServiceCall) -> None:
        """Fail like a phone that is not connected."""
        raise HomeAssistantError("device not connected")

    async_mock_service(hass, NOTIFY_DOMAIN, PHONE_A, raise_exception=boom)
    tablet = async_mock_service(hass, NOTIFY_DOMAIN, PHONE_A2)
    entry = await setup_entry(hass, make_entry())

    await empty_the_house(hass)

    assert len(tablet) == 1
    assert entry.runtime_data.manager.prompt_open(TRACKER_A) is True
    assert f"Could not notify {NOTIFY_DOMAIN}.{PHONE_A}" in caplog.text

    await unload(hass, entry)


async def test_unloading_stops_the_delivery(hass: HomeAssistant) -> None:
    """An unloaded entry neither sends nor listens any more."""
    calls = add_dabo53ck(hass)
    entry = await setup_entry(hass, make_entry())

    await empty_the_house(hass)
    prompt_id = prompt_id_of(calls[0])

    await unload(hass, entry)
    await answer_from_phone(hass, f"VPT_YES_{prompt_id}")

    # The open prompt was kept for the next run, and nothing was sent about it.
    assert len(calls) == 1
