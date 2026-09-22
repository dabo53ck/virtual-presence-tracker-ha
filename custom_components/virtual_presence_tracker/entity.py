"""Shared entity base of the Virtual Presence Tracker integration.

Every entity is a thin view on the household manager: it never polls, it is
written whenever the manager reports a change, and it holds no state of its own
(see docs/DESIGN.md).
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .manager import HouseholdManager


def tracker_device_info(subentry: ConfigSubentry) -> DeviceInfo:
    """Return the device of one virtual tracker.

    One device per tracker, named after it, so that the tracker's entities are
    grouped and a rename carries over. Every entity that has a device uses this
    - whichever platform is set up first creates it, and it has to be the same
    device either way.
    """
    return DeviceInfo(
        identifiers={(DOMAIN, subentry.subentry_id)},
        name=subentry.title,
        entry_type=DeviceEntryType.SERVICE,
    )


class VirtualPresenceEntity(Entity):
    """Base for the entities that follow the household manager."""

    _attr_should_poll = False

    def __init__(
        self, manager: HouseholdManager, subentry_id: str | None = None
    ) -> None:
        """Bind the entity to the manager.

        ``subentry_id`` selects what the entity listens to: a single virtual
        tracker, or the household as a whole when it is ``None``.
        """
        self._manager = manager
        self._subentry_id = subentry_id

    async def async_added_to_hass(self) -> None:
        """Follow the manager for as long as the entity exists."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._manager.async_add_listener(
                self._async_manager_updated, self._subentry_id
            )
        )

    @callback
    def _async_manager_updated(self) -> None:
        """Write the new state after the manager changed."""
        self.async_write_ha_state()


class VirtualTrackerEntity(VirtualPresenceEntity):
    """Base for the entities of a single virtual tracker."""

    # A tracker entity always belongs to a subentry.
    _subentry_id: str

    def __init__(self, manager: HouseholdManager, subentry: ConfigSubentry) -> None:
        """Bind the entity to the tracker of a config subentry."""
        super().__init__(manager, subentry.subentry_id)

    @property
    def _is_home(self) -> bool:
        """Return whether this entity's tracker is at home."""
        return self._manager.is_home(self._subentry_id)


class VirtualTrackerOptionEntity(VirtualTrackerEntity):
    """Base for the entities that show and write one option of a tracker.

    The option itself stays where it has always been, in the data of the
    tracker's config subentry: these entities are a live view on it and a way
    to write it, not a second place to keep it. The entity name and the icon
    come from the option key, which is also the translation key.
    """

    _attr_has_entity_name = True
    _option_key: str

    def __init__(self, manager: HouseholdManager, subentry: ConfigSubentry) -> None:
        """Initialise the entity of one option of one virtual tracker."""
        super().__init__(manager, subentry)
        self._attr_translation_key = self._option_key
        self._attr_unique_id = f"{subentry.subentry_id}_{self._option_key}"
        self._attr_device_info = tracker_device_info(subentry)

    @property
    def _option(self) -> Any:
        """Return what the tracker has stored for this option."""
        return self._manager.option(self._subentry_id, self._option_key)

    @callback
    def _async_set_option(self, value: bool | int) -> None:
        """Write this option of the tracker."""
        self._manager.async_set_option(self._subentry_id, self._option_key, value)
