"""Switch platform of the Virtual Presence Tracker integration.

One switch per virtual tracker. It is the control the user sees: a dashboard
toggle, an NFC tag or an automation flips it, and the device tracker follows.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import VirtualPresenceTrackerConfigEntry
from .const import ATTR_SINCE, DOMAIN, SUBENTRY_TYPE_TRACKER
from .entity import VirtualTrackerEntity
from .manager import HouseholdManager

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VirtualPresenceTrackerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one switch per virtual tracker."""
    manager = entry.runtime_data.manager
    for subentry in entry.get_subentries_of_type(SUBENTRY_TYPE_TRACKER):
        async_add_entities(
            [VirtualTrackerSwitch(manager, subentry)],
            config_subentry_id=subentry.subentry_id,
        )


class VirtualTrackerSwitch(VirtualTrackerEntity, SwitchEntity):
    """The switch that sets one virtual tracker home or away."""

    _attr_has_entity_name = True
    _attr_translation_key = "at_home"

    def __init__(self, manager: HouseholdManager, subentry: ConfigSubentry) -> None:
        """Initialise the switch of one virtual tracker."""
        super().__init__(manager, subentry)
        self._attr_unique_id = f"{subentry.subentry_id}_at_home"
        # One device per tracker, named after it, so that the tracker's
        # entities are grouped and a rename carries over.
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, subentry.subentry_id)},
            name=subentry.title,
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def is_on(self) -> bool:
        """Return whether the virtual tracker is at home."""
        return self._is_home

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return when the tracker last changed, if it ever did."""
        since = self._manager.since(self._subentry_id)
        return {ATTR_SINCE: since.isoformat() if since is not None else None}

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Set the virtual tracker home."""
        self._manager.async_set_home(self._subentry_id, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Set the virtual tracker away."""
        self._manager.async_set_home(self._subentry_id, False)
