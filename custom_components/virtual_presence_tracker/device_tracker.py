"""Device tracker platform of the Virtual Presence Tracker integration.

One `device_tracker` per virtual tracker. It is the entity the user assigns to
a `person` without an HA user, which is what makes `zone.home` count that
person while the tracker is switched on.
"""

from __future__ import annotations

from homeassistant.components.device_tracker import BaseScannerEntity, SourceType
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import VirtualPresenceTrackerConfigEntry
from .const import SUBENTRY_TYPE_TRACKER
from .entity import VirtualTrackerEntity
from .manager import HouseholdManager

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VirtualPresenceTrackerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one device tracker per virtual tracker."""
    manager = entry.runtime_data.manager
    for subentry in entry.get_subentries_of_type(SUBENTRY_TYPE_TRACKER):
        async_add_entities(
            [VirtualTracker(manager, subentry)],
            config_subentry_id=subentry.subentry_id,
        )


class VirtualTracker(VirtualTrackerEntity, BaseScannerEntity):
    """The device tracker of one virtual tracker.

    `BaseScannerEntity` reports `home` while it is connected and `not_home`
    otherwise, and it publishes the associated zone (`zone.home` by default) in
    `in_zones`. A connected tracker with a zone takes precedence over every
    other tracker of the same person.
    """

    # SourceType has no "virtual" member. ROUTER is the closest: a connection
    # that is either there or not, without coordinates.
    _attr_source_type = SourceType.ROUTER
    # BaseTrackerEntity categorises trackers as diagnostic. This one is the
    # entity the user assigns to a person and puts on dashboards, and it has no
    # device to be a diagnostic of, so it stays a normal entity.
    _attr_entity_category = None

    def __init__(self, manager: HouseholdManager, subentry: ConfigSubentry) -> None:
        """Initialise the tracker of one virtual tracker."""
        super().__init__(manager, subentry)
        self._attr_unique_id = f"{subentry.subentry_id}_tracker"
        # A tracker entity never has a device, so its own name is the full
        # name and the entity ID follows the title.
        self._attr_name = subentry.title

    @property
    def is_connected(self) -> bool:
        """Return whether the virtual tracker is at home."""
        return self._is_home
