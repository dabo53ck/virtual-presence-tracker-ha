"""The Virtual Presence Tracker integration.

Presence for household members without a phone. This module wires up the config
entry lifecycle, the household manager, the entity platforms and the built-in
delivery of the prompt to the phones of the chosen persons (see
docs/DESIGN.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback

from .const import LIVE_OPTION_KEYS
from .delivery import PromptDelivery
from .issues import HouseholdIssues
from .manager import HouseholdManager
from .migration import async_remove_legacy_household_device

PLATFORMS = [
    Platform.DEVICE_TRACKER,
    Platform.SWITCH,
    Platform.NUMBER,
    Platform.BINARY_SENSOR,
    Platform.EVENT,
]

# Everything about an entry that a reload is needed for. The five options of a
# tracker are deliberately left out of it: they have entities of their own now,
# and reloading the entry because somebody flipped a switch would take the
# device trackers and their persons to `unavailable` for a moment - long enough
# for the user's own "somebody came home" automations to fire (see
# docs/DESIGN.md).
type ReloadFingerprint = tuple[str, dict[str, Any], dict[str, Any]]


@dataclass
class VirtualPresenceTrackerData:
    """Runtime data of a config entry."""

    manager: HouseholdManager
    delivery: PromptDelivery
    issues: HouseholdIssues
    fingerprint: ReloadFingerprint


type VirtualPresenceTrackerConfigEntry = ConfigEntry[VirtualPresenceTrackerData]


@callback
def _async_reload_fingerprint(entry: ConfigEntry) -> ReloadFingerprint:
    """Return what the entry looks like to everything that needs a reload.

    The title and the data of the entry, plus every subentry with its title and
    all of its data except the options that are written by an entity. Two equal
    fingerprints therefore mean: nothing changed but those options.
    """
    return (
        entry.title,
        dict(entry.data),
        {
            subentry_id: (
                subentry.title,
                {
                    key: value
                    for key, value in subentry.data.items()
                    if key not in LIVE_OPTION_KEYS
                },
            )
            for subentry_id, subentry in entry.subentries.items()
        },
    )


async def async_setup_entry(
    hass: HomeAssistant, entry: VirtualPresenceTrackerConfigEntry
) -> bool:
    """Set up Virtual Presence Tracker from a config entry."""
    manager = HouseholdManager(hass, entry)
    # The stored states must be there before any platform is set up, so that
    # the first state an entity writes is already the restored one.
    await manager.async_load()
    manager.async_start()
    delivery = PromptDelivery(hass, entry, manager)
    issues = HouseholdIssues(hass, entry)
    entry.runtime_data = VirtualPresenceTrackerData(
        manager=manager,
        delivery=delivery,
        issues=issues,
        fingerprint=_async_reload_fingerprint(entry),
    )
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
    # Before resuming the prompts: a prompt that ends in the catch-up leaves a
    # message on the phones of a previous run, and this is what clears it.
    delivery.async_start()
    entry.async_on_unload(delivery.async_stop)
    # After the platforms, because resuming a prompt can emit an event: the
    # entity that carries it has to exist by then, or the event is lost.
    # Forwarding the platforms waits for the entities to be added.
    manager.async_resume_prompts()
    # After the platforms: the repair issues look the tracker entities up in
    # the entity registry, which only knows them once they are added. Stopping
    # on unload clears the issues of this entry, and setting the entry up again
    # raises the ones that still apply.
    issues.async_start()
    entry.async_on_unload(issues.async_stop)
    return True


async def _async_entry_updated(
    hass: HomeAssistant, entry: VirtualPresenceTrackerConfigEntry
) -> None:
    """Reload the entry after its persons or trackers changed.

    A change of nothing but the options an entity writes is the one case that
    does *not* reload: the manager reads them where it uses them, and the
    entities are told to write their new state. Anything else - the real
    persons, a renamed tracker, its recipients, a tracker that was added or
    removed - needs the manager, the delivery and the platforms to be built
    again.
    """
    data: VirtualPresenceTrackerData | None = getattr(entry, "runtime_data", None)
    if data is not None and data.fingerprint == _async_reload_fingerprint(entry):
        data.manager.async_options_changed()
        # Whether a recipient without a phone is worth reporting depends on the
        # ask option, and nothing else re-checks while the entry stays loaded.
        data.issues.async_recheck()
        return
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
