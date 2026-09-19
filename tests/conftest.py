"""Fixtures for the Virtual Presence Tracker tests."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.virtual_presence_tracker.const import DOMAIN


@pytest.fixture(autouse=True)
def _auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading of the custom component in every test."""
    yield


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """A config entry for the integration."""
    return MockConfigEntry(domain=DOMAIN, title="Virtual Presence Tracker", data={})
