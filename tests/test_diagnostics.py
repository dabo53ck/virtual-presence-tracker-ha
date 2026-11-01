"""Tests for the diagnostics of a config entry.

A diagnostics file ends up attached to a public bug report, so the household
is set up here the way a real one is: trackers named after people, sources
named after devices and rooms, a zone name as a state, a phone with a name and
a Bluetooth address. None of it may show up in the download - only neutral
labels that stay the same for the same value.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from http import HTTPStatus
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.virtual_presence_tracker.const import (
    ATTR_DEVICE_TRACKERS,
    ATTR_USER_ID,
    BLUETOOTH_DOMAIN,
    CONF_ASK_LEFT_BEHIND,
    CONF_ASK_ON_DEPARTURE,
    CONF_AWAY_AFTER,
    CONF_BLE_SOURCES,
    CONF_BUTTON_AWAY_TYPES,
    CONF_BUTTON_HOME_TYPES,
    CONF_BUTTON_SOURCES,
    CONF_DEVICE_NAME,
    CONF_NOTIFY_PERSONS,
    CONF_PERSONS,
    CONF_PRESENCE_SOURCES,
    CONF_USER_ID,
    DOMAIN,
    MOBILE_APP_DOMAIN,
    NOTIFY_DOMAIN,
    OPTION_DEFAULTS,
)
from homeassistant.const import STATE_HOME, STATE_NOT_HOME, STATE_ON, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component

from .conftest import ENTRY_ID, TRACKER_A, TRACKER_B, make_subentry

MANIFEST = (
    Path(__file__).parents[1]
    / "custom_components"
    / "virtual_presence_tracker"
    / "manifest.json"
)

ALEX = "person.alex_sample"
SAM = "person.sam_sample"
USER_ALEX = "8f3c2a1b9d7e4f60a1b2c3d4e5f60718"
PHONE_NAME = "Alex's iPhone 15"
PHONE_SERVICE = "mobile_app_alex_s_iphone_15"

BUTTON = "event.playroom_button_robin"
TABLET = "binary_sensor.robin_tablet_wifi"
TAG = "device_tracker.robin_keyring"
MISSING = "binary_sensor.aunt_morgan_phone_wifi"
ADDRESS = "AA:BB:CC:11:22:33"

# Everything that must never appear in a download, lower case.
FORBIDDEN = (
    "robin",
    "morgan",
    "aunt morgan",
    "aunt_morgan",
    "alex",
    "sam",
    "sample",
    "family",
    "playroom",
    "keyring",
    "tablet",
    "wifi",
    "school",
    "sampletown",
    "iphone",
    "mobile_app_",
    "aa:bb:cc",
    USER_ALEX,
    ENTRY_ID.lower(),
    TRACKER_A.lower(),
    TRACKER_B.lower(),
)


@dataclass
class _Heard:
    """The one field of a Bluetooth service info the integration reads."""

    time: float


class FakeBluetooth:
    """Home Assistant's Bluetooth API, as far as the diagnostics use it."""

    def __init__(self) -> None:
        """Start with an empty history."""
        self.clock = 5000.0
        self.heard: dict[str, _Heard] = {}

    def MONOTONIC_TIME(self) -> float:
        """Return the manager's clock."""
        return self.clock

    def async_last_service_info(
        self, hass: HomeAssistant, address: str, connectable: bool = True
    ) -> _Heard | None:
        """Return when an address was last heard."""
        return self.heard.get(address)


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


def household(persons: list[str] | None = None) -> MockConfigEntry:
    """Return a household as a real user would name it."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Family Sample",
        entry_id=ENTRY_ID,
        data={CONF_PERSONS: persons or [ALEX, SAM]},
        subentries_data=(
            make_subentry(
                TRACKER_A,
                "Robin",
                **{
                    CONF_ASK_ON_DEPARTURE: True,
                    CONF_ASK_LEFT_BEHIND: True,
                    CONF_AWAY_AFTER: 10,
                    CONF_NOTIFY_PERSONS: [ALEX, SAM],
                    CONF_BUTTON_SOURCES: [BUTTON],
                    CONF_BUTTON_HOME_TYPES: ["press"],
                    CONF_BUTTON_AWAY_TYPES: ["long_press"],
                    CONF_PRESENCE_SOURCES: [TABLET, TAG],
                    CONF_BLE_SOURCES: [ADDRESS],
                },
            ),
            # A tracker from before most options existed, sharing a source.
            make_subentry(
                TRACKER_B,
                "Aunt Morgan",
                **{
                    CONF_NOTIFY_PERSONS: [SAM],
                    CONF_PRESENCE_SOURCES: [TAG, MISSING],
                },
            ),
        ),
    )


async def dump(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    bluetooth: FakeBluetooth,
) -> dict[str, Any]:
    """Set the household up, open a question of every kind and download."""
    hass.states.async_set(
        ALEX, STATE_HOME, {ATTR_DEVICE_TRACKERS: [], ATTR_USER_ID: USER_ALEX}
    )
    hass.states.async_set(SAM, STATE_NOT_HOME, {ATTR_DEVICE_TRACKERS: []})
    MockConfigEntry(
        domain=MOBILE_APP_DOMAIN,
        title=PHONE_NAME,
        data={CONF_DEVICE_NAME: PHONE_NAME, CONF_USER_ID: USER_ALEX},
    ).add_to_hass(hass)
    async_mock_service(hass, NOTIFY_DOMAIN, PHONE_SERVICE)
    hass.states.async_set(BUTTON, STATE_UNKNOWN)
    hass.states.async_set(TABLET, STATE_ON)
    # A zone name as the state of a device tracker: away, and never shown.
    hass.states.async_set(TAG, "School Sampletown")
    bluetooth.heard[ADDRESS] = _Heard(time=bluetooth.clock - 42)

    entry = household()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    manager = entry.runtime_data.manager
    manager.async_set_home(TRACKER_A, True)
    manager.async_open_reminder(TRACKER_A)
    manager.async_open_left_behind(TRACKER_A)
    manager.async_open_prompt(TRACKER_B)
    await hass.async_block_till_done()

    return await get_diagnostics_for_config_entry(hass, hass_client, entry)


async def test_nothing_personal_is_in_the_download(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    bluetooth: FakeBluetooth,
) -> None:
    """No name, entity ID, address, phone, user or entry ID is left."""
    diagnostics = await dump(hass, hass_client, bluetooth)

    text = json.dumps(diagnostics).lower()
    for forbidden in FORBIDDEN:
        assert forbidden not in text, forbidden
    # Neither the integration's own entities, which are named after a tracker.
    assert "device_tracker." not in text
    assert "person." not in text
    assert "answered_by" not in text


async def test_labels_are_the_same_for_the_same_value(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    bluetooth: FakeBluetooth,
) -> None:
    """One person, one source, one label - wherever it appears."""
    diagnostics = await dump(hass, hass_client, bluetooth)

    assert set(diagnostics["real_persons"]) == {"person_1", "person_2"}
    trackers = diagnostics["trackers"]
    assert set(trackers) == {"tracker_1", "tracker_2"}
    robin, morgan = trackers["tracker_1"], trackers["tracker_2"]

    assert robin["recipients"] == ["person_1", "person_2"]
    assert morgan["recipients"] == ["person_2"]
    assert robin["buttons"]["sources"] == {
        "button_1": {"domain": "event", "status": "unknown"}
    }
    assert robin["presence_sources"]["sources"] == {
        "source_1": {"domain": "binary_sensor", "status": "present"},
        "source_2": {"domain": "device_tracker", "status": "absent"},
    }
    # The shared tag keeps its label; the deleted sensor is a source of its own.
    assert morgan["presence_sources"]["sources"] == {
        "source_2": {"domain": "device_tracker", "status": "absent"},
        "source_3": {"domain": "binary_sensor", "status": "missing"},
    }
    assert robin["ble_sources"]["sources"] == {
        "ble_1": {
            "valid": True,
            "seconds_since_heard": 42,
            "heard_within_away_after": True,
        }
    }
    # The question about a device left behind names its sources by label too.
    assert robin["left_behind"]["sources"] == ["source_1", "ble_1"]


async def test_the_download_says_what_the_manager_knows(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    bluetooth: FakeBluetooth,
) -> None:
    """Version, persons, options, state, open questions and repair issues."""
    diagnostics = await dump(hass, hass_client, bluetooth)

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert diagnostics["version"] == manifest["version"]
    assert diagnostics["loaded"] is True
    assert diagnostics["bluetooth_loaded"] is True
    assert diagnostics["real_persons"] == {
        "person_1": {"presence": "home", "exists": True, "phones": 1},
        "person_2": {"presence": "away", "exists": True, "phones": 0},
    }
    assert diagnostics["household"] == {
        "real_persons_home": 1,
        "real_home": True,
        "only_virtual_home": False,
    }

    robin = diagnostics["trackers"]["tracker_1"]
    assert robin["options"] == {
        **OPTION_DEFAULTS,
        CONF_ASK_ON_DEPARTURE: True,
        CONF_ASK_LEFT_BEHIND: True,
        CONF_AWAY_AFTER: 10,
    }
    assert CONF_AWAY_AFTER not in robin["options_defaulted"]
    assert robin["buttons"]["home_types"] == ["press"]
    assert robin["buttons"]["away_types"] == ["long_press"]
    assert robin["state"]["home"] is True
    assert robin["state"]["source_lock"] is False
    assert robin["prompt"] is None
    assert robin["reminder"]["id"]
    assert robin["reminder"]["expires_at"]
    assert robin["left_behind"]["manual"] is True

    morgan = diagnostics["trackers"]["tracker_2"]
    assert morgan["options_defaulted"] == sorted(OPTION_DEFAULTS)
    assert morgan["state"]["home"] is False
    assert morgan["prompt"]["manual"] is True
    assert morgan["reminder"] is None
    assert morgan["left_behind"] is None

    # The translation keys of the entry's issues, and nothing of their text.
    assert "source_missing" in diagnostics["repair_issues"]
    assert diagnostics["repair_issues"] == sorted(
        issue.translation_key
        for (domain, _), issue in ir.async_get(hass).issues.items()
        if domain == DOMAIN
    )


async def test_an_entry_that_is_not_loaded_still_downloads(
    hass: HomeAssistant, hass_client: ClientSessionGenerator
) -> None:
    """Without the manager only the setup is shown."""
    entry = household()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    assert diagnostics["loaded"] is False
    assert "household" not in diagnostics
    assert "state" not in diagnostics["trackers"]["tracker_1"]
    assert diagnostics["real_persons"]["person_1"]["presence"] == "unknown"
    text = json.dumps(diagnostics).lower()
    for forbidden in FORBIDDEN:
        assert forbidden not in text, forbidden


async def test_the_whole_download_names_no_person_and_no_tracker(
    hass: HomeAssistant, hass_client: ClientSessionGenerator
) -> None:
    """Home Assistant's own `issues` block of the download is neutral too.

    It lists the ID of every issue of the domain. With an issue of every kind
    that is about a person or a tracker active, none of the IDs names one.
    """
    absent = "person.lukas_sample"
    hass.states.async_set(
        ALEX,
        STATE_HOME,
        {ATTR_DEVICE_TRACKERS: ["device_tracker.robin"], ATTR_USER_ID: USER_ALEX},
    )
    hass.states.async_set(SAM, STATE_NOT_HOME, {ATTR_DEVICE_TRACKERS: []})
    entry = household([ALEX, SAM, absent])
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert await async_setup_component(hass, "diagnostics", {})
    await hass.async_block_till_done()

    client = await hass_client()
    response = await client.get(f"/api/diagnostics/config_entry/{entry.entry_id}")
    assert response.status == HTTPStatus.OK
    payload = await response.json()

    keys = set(payload["data"]["repair_issues"])
    assert {
        "recipient_without_phone",
        "real_person_missing",
        "real_person_has_virtual_tracker",
        "tracker_not_assigned",
        "source_missing",
    } <= keys
    assert len(payload["issues"]) >= 5
    text = json.dumps({"data": payload["data"], "issues": payload["issues"]}).lower()
    for forbidden in (*FORBIDDEN[:-3], "lukas", "person.", "device_tracker."):
        assert forbidden not in text, forbidden
