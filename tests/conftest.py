"""Fixtures for the Virtual Presence Tracker tests."""

from __future__ import annotations

from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.virtual_presence_tracker.const import (
    CONF_PERSONS,
    DOMAIN,
    SUBENTRY_TYPE_TRACKER,
)

ENTRY_ID = "01JVPT0000000000000000ENTRY"
TRACKER_A = "01JVPT000000000000000TRACKA"
TRACKER_B = "01JVPT000000000000000TRACKB"

PERSON_A = "person.dabo53ck"
PERSON_B = "person.king53ck"


def make_subentry(subentry_id: str, title: str, **data: Any) -> dict[str, Any]:
    """Return subentry data for one virtual tracker."""
    return {
        "data": data,
        "subentry_id": subentry_id,
        "subentry_type": SUBENTRY_TYPE_TRACKER,
        "title": title,
        "unique_id": None,
    }


def make_entry(
    *subentries: dict[str, Any], persons: list[str] | None = None
) -> MockConfigEntry:
    """Return a config entry with the given real persons and trackers."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Virtual Presence Tracker",
        entry_id=ENTRY_ID,
        data={CONF_PERSONS: persons if persons is not None else [PERSON_A]},
        subentries_data=subentries,
    )


@pytest.fixture(autouse=True)
def _auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading of the custom component in every test."""
    yield


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """A config entry with real persons and without virtual trackers."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Virtual Presence Tracker",
        data={CONF_PERSONS: [PERSON_A, PERSON_B]},
    )


@pytest.fixture
def tracker_entry() -> MockConfigEntry:
    """A config entry with one real person and two virtual trackers."""
    return make_entry(
        make_subentry(TRACKER_A, "Kid"),
        make_subentry(TRACKER_B, "Granny"),
    )
