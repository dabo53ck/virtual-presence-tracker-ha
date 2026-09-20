"""The Virtual Presence Tracker integration.

Presence for household members without a phone. This module wires up the config
entry lifecycle, the household manager and the entity platforms; built-in
delivery of the prompt to a phone is a later milestone (see docs/DESIGN.md).
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .issues import HouseholdIssues
from .manager import HouseholdManager
from .migration import async_remove_legacy_household_device

PLATFORMS = [
    Platform.DEVICE_TRACKER,
    Platform.SWITCH,
    Platform.BINARY_SENSOR,
    Platform.EVENT,
]


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
    # The stored states must be there before any platform is set up, so that
    # the first state an entity writes is already the restored one.
    await manager.async_load()
    manager.async_start()
    entry.runtime_data = VirtualPresenceTrackerData(manager=manager)
    # Home Assistant notifies update listeners when the real persons change and
    # when a tracker subentry is added, changed or removed, but it never
    # reloads the entry by itself. Without the reload the manager would keep
    # watching the old persons and would not know the new trackers.
    entry.async_on_unload(entry.add_update_listener(_async_entry_updated))
    # Before the platforms: the household sensor of an older install is then
    # added to a registry entry that no longer points at a device, instead of
    # being attached to one for the moment it takes to clean up.
    async_remove_legacy_household_device(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # After the platforms, because resuming a prompt can emit an event: the
    # entity that carries it has to exist by then, or the event is lost.
    # Forwarding the platforms waits for the entities to be added.
    manager.async_resume_prompts()
    # After the platforms: the repair issues look the tracker entities up in
    # the entity registry, which only knows them once they are added. Stopping
    # on unload clears the issues of this entry, and setting the entry up again
    # raises the ones that still apply.
    issues = HouseholdIssues(hass, entry)
    issues.async_start()
    entry.async_on_unload(issues.async_stop)
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

    The platforms go first: their entities unsubscribe from the manager while
    it is still there. Stopping the manager afterwards unsubscribes it from the
    persons and flushes pending state to disk. If a platform refuses to unload,
    the entry stays loaded and the manager has to keep running.
    """
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    await entry.runtime_data.manager.async_stop()
    return True
