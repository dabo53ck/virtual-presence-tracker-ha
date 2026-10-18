"""Switch platform of the Virtual Presence Tracker integration.

The "at home" switch of a virtual tracker is the control the user sees: a
dashboard toggle, an NFC tag or an automation flips it, and the device tracker
follows. It also carries the six question actions, as entity services: the
switch is the entity a prompt, a reminder or a question about a device left
behind is about, so targeting it is targeting the tracker.

Next to it sit the switches of the tracker's options that are switched
depending on the situation (M2f, M3c, M3f): asking when the house empties,
the reset on return, asking about a device left behind and the two Do Not
Disturb overrides. They write the subentry data the options have always lived
in, without reloading the entry. Everything that is set once - the timings and
the expiry notice - is in the tracker's form instead (M3g).
"""

from __future__ import annotations

from typing import Any, NoReturn

import voluptuous as vol

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import EntityCategory
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
    ATTR_LEFT_BEHIND_EXPIRES_AT,
    ATTR_LEFT_BEHIND_OPEN,
    ATTR_PROMPT_EXPIRES_AT,
    ATTR_PROMPT_OPEN,
    ATTR_REMINDER_EXPIRES_AT,
    ATTR_REMINDER_OPEN,
    ATTR_SINCE,
    CONF_ASK_LEFT_BEHIND,
    CONF_ASK_ON_DEPARTURE,
    CONF_LEFT_BEHIND_OVERRIDE_DND,
    CONF_OVERRIDE_DND,
    CONF_RESET_ON_RETURN,
    DOMAIN,
    PERSON_DOMAIN,
    SERVICE_ANSWER_LEFT_BEHIND,
    SERVICE_ANSWER_PROMPT,
    SERVICE_ANSWER_REMINDER,
    SERVICE_OPEN_LEFT_BEHIND,
    SERVICE_OPEN_PROMPT,
    SERVICE_OPEN_REMINDER,
    SUBENTRY_TYPE_TRACKER,
)
from .entity import (
    VirtualTrackerEntity,
    VirtualTrackerOptionEntity,
    tracker_device_info,
)
from .manager import (
    HouseholdManager,
    OpenLeftBehindResult,
    OpenPromptResult,
    OpenReminderResult,
)

PARALLEL_UPDATES = 0

ANSWER_SCHEMA = {
    vol.Required(ATTR_ANSWER): vol.In([ANSWER_YES, ANSWER_NO]),
    vol.Optional(ATTR_ANSWERED_BY): cv.entity_domain(PERSON_DOMAIN),
}

# Why the manual opening was refused, in the words the user reads.
OPEN_PROMPT_ERRORS = {
    OpenPromptResult.TRACKER_AT_HOME: "tracker_already_home",
    OpenPromptResult.PROMPT_OPEN: "prompt_already_open",
}
OPEN_REMINDER_ERRORS = {
    OpenReminderResult.TRACKER_AWAY: "tracker_not_home",
    OpenReminderResult.REMINDER_OPEN: "reminder_already_open",
}
OPEN_LEFT_BEHIND_ERRORS = {
    OpenLeftBehindResult.TRACKER_AWAY: "tracker_not_home",
    OpenLeftBehindResult.NO_SOURCES: "no_presence_sources",
    OpenLeftBehindResult.LEFT_BEHIND_OPEN: "left_behind_already_open",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VirtualPresenceTrackerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the switches of every virtual tracker."""
    manager = entry.runtime_data.manager
    for subentry in entry.get_subentries_of_type(SUBENTRY_TYPE_TRACKER):
        async_add_entities(
            [
                VirtualTrackerSwitch(manager, subentry),
                AskOnDepartureSwitch(manager, subentry),
                ResetOnReturnSwitch(manager, subentry),
                OverrideDndSwitch(manager, subentry),
                AskLeftBehindSwitch(manager, subentry),
                LeftBehindOverrideDndSwitch(manager, subentry),
            ],
            config_subentry_id=subentry.subentry_id,
        )

    # Registering twice is a no-op, so a reload does not have to care.
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_ANSWER_PROMPT, ANSWER_SCHEMA, "async_answer_prompt"
    )
    platform.async_register_entity_service(
        SERVICE_OPEN_PROMPT, None, "async_open_prompt"
    )
    platform.async_register_entity_service(
        SERVICE_ANSWER_REMINDER, ANSWER_SCHEMA, "async_answer_reminder"
    )
    platform.async_register_entity_service(
        SERVICE_OPEN_REMINDER, None, "async_open_reminder"
    )
    platform.async_register_entity_service(
        SERVICE_ANSWER_LEFT_BEHIND, ANSWER_SCHEMA, "async_answer_left_behind"
    )
    platform.async_register_entity_service(
        SERVICE_OPEN_LEFT_BEHIND, None, "async_open_left_behind"
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
        reminder_expires_at = self._manager.reminder_expires_at(self._subentry_id)
        left_behind_expires_at = self._manager.left_behind_expires_at(self._subentry_id)
        return {
            ATTR_SINCE: since.isoformat() if since is not None else None,
            ATTR_PROMPT_OPEN: self._manager.prompt_open(self._subentry_id),
            ATTR_PROMPT_EXPIRES_AT: (
                expires_at.isoformat() if expires_at is not None else None
            ),
            ATTR_REMINDER_OPEN: self._manager.reminder_open(self._subentry_id),
            ATTR_REMINDER_EXPIRES_AT: (
                reminder_expires_at.isoformat()
                if reminder_expires_at is not None
                else None
            ),
            ATTR_LEFT_BEHIND_OPEN: self._manager.left_behind_open(self._subentry_id),
            ATTR_LEFT_BEHIND_EXPIRES_AT: (
                left_behind_expires_at.isoformat()
                if left_behind_expires_at is not None
                else None
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

    async def async_open_prompt(self) -> None:
        """Open a prompt about this tracker now, without waiting for a departure."""
        result = self._manager.async_open_prompt(self._subentry_id)
        if (translation_key := OPEN_PROMPT_ERRORS.get(result)) is not None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key=translation_key,
                translation_placeholders={"entity_id": self.entity_id},
            )

    async def async_answer_reminder(
        self, answer: str, answered_by: str | None = None
    ) -> None:
        """Answer the open reminder of this tracker."""
        if not self._manager.async_answer_reminder(
            self._subentry_id, answer == ANSWER_YES, answered_by
        ):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="no_open_reminder",
                translation_placeholders={"entity_id": self.entity_id},
            )

    async def async_open_reminder(self) -> None:
        """Ask about this tracker now, without waiting for the reminder interval."""
        result = self._manager.async_open_reminder(self._subentry_id)
        if (translation_key := OPEN_REMINDER_ERRORS.get(result)) is not None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key=translation_key,
                translation_placeholders={"entity_id": self.entity_id},
            )

    async def async_answer_left_behind(
        self, answer: str, answered_by: str | None = None
    ) -> None:
        """Answer the open question about a device left behind (M3f)."""
        if not self._manager.async_answer_left_behind(
            self._subentry_id, answer == ANSWER_YES, answered_by
        ):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="no_open_left_behind",
                translation_placeholders={"entity_id": self.entity_id},
            )

    async def async_open_left_behind(self) -> None:
        """Ask about a device left behind now, without waiting for a departure."""
        result = self._manager.async_open_left_behind(self._subentry_id)
        if (translation_key := OPEN_LEFT_BEHIND_ERRORS.get(result)) is not None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key=translation_key,
                translation_placeholders={"entity_id": self.entity_id},
            )


class VirtualTrackerOptionSwitch(VirtualTrackerOptionEntity, SwitchEntity):
    """A switch that shows and writes one boolean option of a tracker.

    The six question actions are registered for the whole `switch` platform,
    so these switches carry them too, although the questions are about the
    tracker rather than about one of its settings. Targeting a device or an
    area never lands here - Home Assistant leaves entities with a category out
    of that - but naming one of these entities by hand does, and the answer has
    to be a sentence the user can act on instead of an AttributeError.
    """

    @property
    def is_on(self) -> bool:
        """Return what the tracker has stored for this option."""
        return bool(self._option)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Switch the option on."""
        self._async_set_option(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Switch the option off."""
        self._async_set_option(False)

    async def async_answer_prompt(
        self, answer: str, answered_by: str | None = None
    ) -> None:
        """Refuse to answer a prompt: this entity is a setting, not the tracker."""
        self._raise_not_a_tracker_switch()

    async def async_open_prompt(self) -> None:
        """Refuse to open a prompt: this entity is a setting, not the tracker."""
        self._raise_not_a_tracker_switch()

    async def async_answer_reminder(
        self, answer: str, answered_by: str | None = None
    ) -> None:
        """Refuse to answer a reminder: this entity is a setting, not the tracker."""
        self._raise_not_a_tracker_switch()

    async def async_open_reminder(self) -> None:
        """Refuse to open a reminder: this entity is a setting, not the tracker."""
        self._raise_not_a_tracker_switch()

    async def async_answer_left_behind(
        self, answer: str, answered_by: str | None = None
    ) -> None:
        """Refuse to answer a question: this entity is a setting, not the tracker."""
        self._raise_not_a_tracker_switch()

    async def async_open_left_behind(self) -> None:
        """Refuse to open a question: this entity is a setting, not the tracker."""
        self._raise_not_a_tracker_switch()

    def _raise_not_a_tracker_switch(self) -> NoReturn:
        """Say which entity the question should have been aimed at."""
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="not_a_tracker_switch",
            translation_placeholders={"entity_id": self.entity_id},
        )


class AskOnDepartureSwitch(VirtualTrackerOptionSwitch):
    """Whether the tracker asks when the house empties.

    A setting like the other four switches, and therefore a configuration
    entity: it belongs with them on the tracker's device page rather than next
    to the tracker's own switch. Being a configuration entity changes nothing about
    writing it - an automation or a script flips it like any other switch.
    Switching it off while the tracker is being asked about takes the question
    back at once (the manager does that, reason ``option_disabled``).
    """

    _attr_entity_category = EntityCategory.CONFIG
    _option_key = CONF_ASK_ON_DEPARTURE


class ResetOnReturnSwitch(VirtualTrackerOptionSwitch):
    """Whether the tracker switches itself off when the house is entered."""

    _attr_entity_category = EntityCategory.CONFIG
    _option_key = CONF_RESET_ON_RETURN


class OverrideDndSwitch(VirtualTrackerOptionSwitch):
    """Whether the prompt is loud enough to get through a silenced phone (M3c).

    Off by default, because it is genuinely loud: on iOS the prompt becomes a
    critical alert, on Android it goes out on the alarm channel. It applies to
    the prompt alone - the reminder asks about a whole day and the expiry
    notices are news rather than questions, so neither is worth waking anybody
    for.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _option_key = CONF_OVERRIDE_DND


class AskLeftBehindSwitch(VirtualTrackerOptionSwitch):
    """Whether the tracker asks about a device left behind (M3f).

    Off by default. With it on, a tracker that a presence source keeps on is
    asked about `away_after` after the last real person left, and switched
    off when nobody answers. Switching it off takes an open question back
    (`option_disabled`, not for one opened by hand) and ends the lock.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _option_key = CONF_ASK_LEFT_BEHIND


class LeftBehindOverrideDndSwitch(VirtualTrackerOptionSwitch):
    """Whether the question about a device left behind gets through silence.

    The prompt's technique (M3c) for this question alone: a critical alert on
    iOS, the alarm channel on Android. Off by default, and separate from the
    prompt's switch.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _option_key = CONF_LEFT_BEHIND_OVERRIDE_DND
