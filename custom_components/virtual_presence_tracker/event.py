"""Event platform of the Virtual Presence Tracker integration.

One event entity per virtual tracker. It is how the questions about that
tracker reach the outside world: an automation triggers on it, decides how to
ask - a phone notification, a TTS announcement, a dashboard button - and sends
the answer back through the `answer_prompt` / `answer_reminder` /
`answer_left_behind` action. The prompt (M2a), the reminder (M3a) and the
question about a device left behind (M3f) are published here, with event types
of their own; the types and their data are a public contract.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import VirtualPresenceTrackerConfigEntry
from .const import SUBENTRY_TYPE_TRACKER, TRACKER_EVENT_TYPES
from .entity import VirtualTrackerEntity, tracker_device_info
from .manager import HouseholdManager

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VirtualPresenceTrackerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one prompt event entity per virtual tracker."""
    manager = entry.runtime_data.manager
    for subentry in entry.get_subentries_of_type(SUBENTRY_TYPE_TRACKER):
        async_add_entities(
            [VirtualTrackerPromptEvent(manager, subentry)],
            config_subentry_id=subentry.subentry_id,
        )


class VirtualTrackerPromptEvent(VirtualTrackerEntity, EventEntity):
    """Announce what happens to the questions about one virtual tracker.

    One entity for every question about the tracker - the prompt, the
    reminder and the question about a device left behind - so that an
    automation that wants them all does not have to listen three times. The unique ID and the
    translation key stay what they were in M2a - renaming either would give
    every existing installation a new entity.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "prompt"
    _attr_event_types = TRACKER_EVENT_TYPES

    def __init__(self, manager: HouseholdManager, subentry: ConfigSubentry) -> None:
        """Initialise the prompt event entity of one virtual tracker."""
        super().__init__(manager, subentry)
        self._attr_unique_id = f"{subentry.subentry_id}_prompt"
        self._attr_device_info = tracker_device_info(subentry)

    async def async_added_to_hass(self) -> None:
        """Follow every question about this tracker while the entity exists."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._manager.async_add_prompt_listener(
                self._subentry_id, self._async_prompt_event
            )
        )
        self.async_on_remove(
            self._manager.async_add_reminder_listener(
                self._subentry_id, self._async_prompt_event
            )
        )
        self.async_on_remove(
            self._manager.async_add_left_behind_listener(
                self._subentry_id, self._async_prompt_event
            )
        )

    @callback
    def _async_prompt_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Publish one event of one of the questions."""
        self._trigger_event(event_type, data)
        self.async_write_ha_state()
