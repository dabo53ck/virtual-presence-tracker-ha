"""The Virtual Presence Tracker integration.

Presence for household members without a phone. This module only wires up the
config entry lifecycle; entities, the prompt state machine and services are
added in later milestones (see docs/DESIGN.md).
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant


@dataclass
class VirtualPresenceTrackerData:
    """Runtime data of a config entry.

    Still empty: the tracker manager, timers and subscriptions live here once
    the entities and the state machine exist.
    """


type VirtualPresenceTrackerConfigEntry = ConfigEntry[VirtualPresenceTrackerData]


async def async_setup_entry(
    hass: HomeAssistant, entry: VirtualPresenceTrackerConfigEntry
) -> bool:
    """Set up Virtual Presence Tracker from a config entry."""
    entry.runtime_data = VirtualPresenceTrackerData()
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: VirtualPresenceTrackerConfigEntry
) -> bool:
    """Unload a config entry.

    No platforms are forwarded yet, so there is nothing to tear down beyond the
    runtime data, which Home Assistant drops with the entry.
    """
    return True
