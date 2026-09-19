"""Fixtures for the Virtual Presence Tracker tests."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.virtual_presence_tracker.const import CONF_PERSONS, DOMAIN


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
        data={CONF_PERSONS: ["person.dabo53ck", "person.king53ck"]},
    )
