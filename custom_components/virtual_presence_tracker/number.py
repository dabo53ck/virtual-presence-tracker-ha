"""Number platform of the Virtual Presence Tracker integration.

The two timings of a tracker's prompt: how long it stays open and how long it
waits before it opens. Both live in the data of the tracker's config subentry,
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
    MAX_ANSWER_TIMEOUT,
    MAX_PROMPT_DELAY,
    MIN_ANSWER_TIMEOUT,
    MIN_PROMPT_DELAY,
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
