"""Time platform of the Virtual Presence Tracker integration (M5).

The time windows of a tracker's presence sources: a start and an end for each
weekday, 14 configuration entities on the tracker's device. Only a tracker
with "Use time windows" ticked in its form has them; unticking the box removes
them again (migration.py), and the times they wrote stay in the subentry data
for the next time it is ticked.

Like the option switches they are a view on the subentry data and write it
without reloading the entry. The follower of the presence sources reads the
times where it uses them and sets the timer of the next start or end again.
"""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import VirtualPresenceTrackerConfigEntry, windows
from .const import SUBENTRY_TYPE_TRACKER, WINDOW_KEYS
from .entity import VirtualTrackerOptionEntity
from .manager import HouseholdManager

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VirtualPresenceTrackerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the window times of every tracker that uses time windows."""
    manager = entry.runtime_data.manager
    for subentry in entry.get_subentries_of_type(SUBENTRY_TYPE_TRACKER):
        if not windows.enabled(subentry.data):
            continue
        async_add_entities(
            [WindowTime(manager, subentry, key) for key in WINDOW_KEYS],
            config_subentry_id=subentry.subentry_id,
        )


class WindowTime(VirtualTrackerOptionEntity, TimeEntity):
    """The start or the end of one weekday's time window of a tracker.

    The key - `window_<day>_start` or `window_<day>_end` - is the translation
    key and the suffix of the unique ID, as for every other option entity.
    """

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, manager: HouseholdManager, subentry: ConfigSubentry, key: str
    ) -> None:
        """Initialise the entity of one window time of one virtual tracker."""
        self._option_key = key
        super().__init__(manager, subentry)

    @property
    def native_value(self) -> time:
        """Return the time the tracker has stored, midnight without one."""
        return windows.parse_time(self._option)

    async def async_set_value(self, value: time) -> None:
        """Write the time, to the second, the way it is stored."""
        self._async_set_option(value.replace(tzinfo=None).isoformat("seconds"))
