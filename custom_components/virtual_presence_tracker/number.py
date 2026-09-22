"""Number platform of the Virtual Presence Tracker integration.

The timings of a tracker: how long its prompt stays open, how long it waits
before it opens, after how many hours at home the tracker reminds about itself
(M3a) and how long that reminder waits for its answer. All of them live in the
data of the tracker's config subentry,
where they have always lived - these entities show the stored value and write
it, without reloading the entry (see docs/DESIGN.md).
"""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import VirtualPresenceTrackerConfigEntry
from .const import (
    CONF_ANSWER_TIMEOUT,
    CONF_PROMPT_DELAY,
    CONF_REMIND_AFTER,
    CONF_REMINDER_TIMEOUT,
    MAX_ANSWER_TIMEOUT,
    MAX_PROMPT_DELAY,
    MAX_REMIND_AFTER,
    MAX_REMINDER_TIMEOUT,
    MIN_ANSWER_TIMEOUT,
    MIN_PROMPT_DELAY,
    MIN_REMIND_AFTER,
    MIN_REMINDER_TIMEOUT,
    SUBENTRY_TYPE_TRACKER,
)
from .entity import VirtualTrackerOptionEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VirtualPresenceTrackerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the timings of every virtual tracker."""
    manager = entry.runtime_data.manager
    for subentry in entry.get_subentries_of_type(SUBENTRY_TYPE_TRACKER):
        async_add_entities(
            [
                AnswerTimeoutNumber(manager, subentry),
                PromptDelayNumber(manager, subentry),
                RemindAfterNumber(manager, subentry),
                ReminderTimeoutNumber(manager, subentry),
            ],
            config_subentry_id=subentry.subentry_id,
        )


class VirtualTrackerOptionNumber(VirtualTrackerOptionEntity, NumberEntity):
    """A number that shows and writes one timing of a tracker.

    Both timings are whole units and small enough to be typed rather than
    dragged, hence the box. `NumberDeviceClass.DURATION` allows minutes and
    seconds, so the value is labelled as the duration it is.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_device_class = NumberDeviceClass.DURATION
    _attr_mode = NumberMode.BOX
    _attr_native_step = 1

    @property
    def native_value(self) -> float:
        """Return what the tracker has stored for this timing."""
        return float(self._option)

    async def async_set_native_value(self, value: float) -> None:
        """Store a new timing. The prompts that follow use it."""
        self._async_set_option(int(value))


class AnswerTimeoutNumber(VirtualTrackerOptionNumber):
    """How many minutes a prompt of this tracker stays open.

    A prompt that is already open keeps the deadline it was given: the new
    value is for the next one.
    """

    _option_key = CONF_ANSWER_TIMEOUT
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_native_min_value = MIN_ANSWER_TIMEOUT
    _attr_native_max_value = MAX_ANSWER_TIMEOUT


class PromptDelayNumber(VirtualTrackerOptionNumber):
    """How many seconds the tracker waits after the last departure before it asks."""

    _option_key = CONF_PROMPT_DELAY
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_native_min_value = MIN_PROMPT_DELAY
    _attr_native_max_value = MAX_PROMPT_DELAY


class RemindAfterNumber(VirtualTrackerOptionNumber):
    """After how many hours at home the tracker reminds about itself (M3a).

    Zero means never, which is what a tracker without the option does and what
    every tracker from before it keeps doing. Changing the value moves the
    timer at once: lowering it below the time the tracker has already been on
    asks straight away, which is the point of a safety net.
    """

    _option_key = CONF_REMIND_AFTER
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_native_min_value = MIN_REMIND_AFTER
    _attr_native_max_value = MAX_REMIND_AFTER


class ReminderTimeoutNumber(VirtualTrackerOptionNumber):
    """How many minutes a reminder of this tracker stays open.

    Deliberately not the prompt's answer time: the prompt is answered on the
    way out of the door, the reminder asks about a whole day and may well be
    answered an hour later. A reminder that is already open keeps the deadline
    it was given, as the prompt does.
    """

    _option_key = CONF_REMINDER_TIMEOUT
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_native_min_value = MIN_REMINDER_TIMEOUT
    _attr_native_max_value = MAX_REMINDER_TIMEOUT
