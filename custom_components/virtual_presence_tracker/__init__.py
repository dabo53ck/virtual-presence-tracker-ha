"""The Virtual Presence Tracker integration.

Presence for household members without a phone. This module wires up the config
entry lifecycle and the household manager; entities, the prompt state machine
and services are added in later milestones (see docs/DESIGN.md).
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .manager import HouseholdManager


@dataclass
class VirtualPresenceTrackerData:
    """Runtime data of a config entry."""

    manager: HouseholdManager


type VirtualPresenceTrackerConfigEntry = ConfigEntry[VirtualPresenceTrackerData]


async def async_setup_entry(
    hass: HomeAssistant, entry: VirtualPresenceTrackerConfigEntry
) -> bool:
    """Set up Virtual Presence Tracker from a config entry."""
    manager = HouseholdManager(hass, entry)
    # The stored states must be there before any platform is set up.
    await manager.async_load()
    manager.async_start()
    entry.runtime_data = VirtualPresenceTrackerData(manager=manager)
    # Home Assistant notifies update listeners when the real persons change and
    # when a tracker subentry is added, changed or removed, but it never
    # reloads the entry by itself. Without the reload the manager would keep
    # watching the old persons and would not know the new trackers.
    entry.async_on_unload(entry.add_update_listener(_async_entry_updated))
    return True


async def _async_entry_updated(
    hass: HomeAssistant, entry: VirtualPresenceTrackerConfigEntry
) -> None:
    """Reload the entry after its persons or trackers changed."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(
    hass: HomeAssistant, entry: VirtualPresenceTrackerConfigEntry
) -> bool:
    """Unload a config entry.

    No platforms are forwarded yet; stopping the manager unsubscribes it and
    flushes pending state to disk.
    """
    await entry.runtime_data.manager.async_stop()
    return True
