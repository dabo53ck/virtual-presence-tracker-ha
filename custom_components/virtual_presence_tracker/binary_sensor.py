"""Binary sensor platform of the Virtual Presence Tracker integration.

One sensor per config entry: "only virtual trackers home" is on when at least
one virtual tracker is at home and no configured real person is.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import VirtualPresenceTrackerConfigEntry
from .const import (
    ATTR_REAL_PERSONS_HOME,
    ATTR_VIRTUAL_TRACKERS_HOME,
    DOMAIN,
    HOUSEHOLD_DEVICE_NAME,
    SUBENTRY_TYPE_TRACKER,
)
from .entity import VirtualPresenceEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VirtualPresenceTrackerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the household sensor of a config entry."""
    async_add_entities([OnlyVirtualHomeSensor(entry)])


class OnlyVirtualHomeSensor(VirtualPresenceEntity, BinarySensorEntity):
    """Report whether the only ones at home are virtual trackers."""

    _attr_has_entity_name = True
    _attr_translation_key = "only_virtual_home"

    def __init__(self, entry: VirtualPresenceTrackerConfigEntry) -> None:
        """Initialise the sensor of the household."""
        super().__init__(entry.runtime_data.manager)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_only_virtual_home"
        # One device for the household, carrying the entities that are not
        # bound to a single tracker.
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=HOUSEHOLD_DEVICE_NAME,
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def is_on(self) -> bool | None:
        """Return whether only virtual trackers are at home.

        While no real person's state is known yet - right after a restart, for
        example - the answer is unknown rather than a guess.
        """
        if self._manager.real_home is None:
            return None
        return self._manager.only_virtual_home

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return who makes up the current state."""
        return {
            ATTR_REAL_PERSONS_HOME: self._manager.real_persons_home,
            ATTR_VIRTUAL_TRACKERS_HOME: [
                subentry.title
                for subentry in self._entry.get_subentries_of_type(
                    SUBENTRY_TYPE_TRACKER
                )
                if self._manager.is_home(subentry.subentry_id)
            ],
        }
