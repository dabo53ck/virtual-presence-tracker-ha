"""Shared entity base of the Virtual Presence Tracker integration.

Every entity is a thin view on the household manager: it never polls, it is
written whenever the manager reports a change, and it holds no state of its own
(see docs/DESIGN.md).
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import callback
from homeassistant.helpers.entity import Entity

from .manager import HouseholdManager


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
