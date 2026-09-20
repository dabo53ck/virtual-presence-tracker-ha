"""Switch platform of the Virtual Presence Tracker integration.

One switch per virtual tracker. It is the control the user sees: a dashboard
toggle, an NFC tag or an automation flips it, and the device tracker follows.
It also carries the answer to the prompt, as an entity service: the switch is
the entity a prompt is about, so targeting it is targeting the tracker.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import VirtualPresenceTrackerConfigEntry
from .const import (
    ANSWER_NO,
    ANSWER_YES,
    ATTR_ANSWER,
    ATTR_ANSWERED_BY,
    ATTR_PROMPT_EXPIRES_AT,
    ATTR_PROMPT_OPEN,
    ATTR_SINCE,
    DOMAIN,
    PERSON_DOMAIN,
    SERVICE_ANSWER_PROMPT,
    SUBENTRY_TYPE_TRACKER,
)
from .entity import VirtualTrackerEntity, tracker_device_info
from .manager import HouseholdManager

PARALLEL_UPDATES = 0

ANSWER_PROMPT_SCHEMA = {
    vol.Required(ATTR_ANSWER): vol.In([ANSWER_YES, ANSWER_NO]),
    vol.Optional(ATTR_ANSWERED_BY): cv.entity_domain(PERSON_DOMAIN),
}


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

    # Registering twice is a no-op, so a reload does not have to care.
    entity_platform.async_get_current_platform().async_register_entity_service(
        SERVICE_ANSWER_PROMPT, ANSWER_PROMPT_SCHEMA, "async_answer_prompt"
    )


class VirtualTrackerSwitch(VirtualTrackerEntity, SwitchEntity):
    """The switch that sets one virtual tracker home or away."""

    _attr_has_entity_name = True
    _attr_translation_key = "at_home"

    def __init__(self, manager: HouseholdManager, subentry: ConfigSubentry) -> None:
        """Initialise the switch of one virtual tracker."""
        super().__init__(manager, subentry)
        self._attr_unique_id = f"{subentry.subentry_id}_at_home"
        self._attr_device_info = tracker_device_info(subentry)

    @property
    def is_on(self) -> bool:
        """Return whether the virtual tracker is at home."""
        return self._is_home

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return when the tracker last changed and whether it is being asked about."""
        since = self._manager.since(self._subentry_id)
        expires_at = self._manager.prompt_expires_at(self._subentry_id)
        return {
            ATTR_SINCE: since.isoformat() if since is not None else None,
            ATTR_PROMPT_OPEN: self._manager.prompt_open(self._subentry_id),
            ATTR_PROMPT_EXPIRES_AT: (
                expires_at.isoformat() if expires_at is not None else None
            ),
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Set the virtual tracker home."""
        self._manager.async_set_home(self._subentry_id, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Set the virtual tracker away."""
        self._manager.async_set_home(self._subentry_id, False)

    async def async_answer_prompt(
        self, answer: str, answered_by: str | None = None
    ) -> None:
        """Answer the open prompt of this tracker."""
        if not self._manager.async_answer_prompt(
            self._subentry_id, answer == ANSWER_YES, answered_by
        ):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="no_open_prompt",
                translation_placeholders={"entity_id": self.entity_id},
            )
