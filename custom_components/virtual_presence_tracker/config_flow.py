"""Config flow for the Virtual Presence Tracker integration.

The single config entry holds the real persons of the household; every virtual
tracker is a config subentry of it (see docs/DESIGN.md). A tracker is
identified by its subentry ID, so its name is free to change at any time.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    SOURCE_USER,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentry,
    ConfigSubentryFlow,
    FlowType,
    SubentryFlowContext,
    SubentryFlowResult,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
)

from .const import (
    ATTR_DEVICE_TRACKERS,
    CONF_ANSWER_TIMEOUT,
    CONF_ASK_ON_DEPARTURE,
    CONF_PERSONS,
    CONF_PROMPT_DELAY,
    CONF_RESET_ON_RETURN,
    DEFAULT_ANSWER_TIMEOUT,
    DEFAULT_ASK_ON_DEPARTURE,
    DEFAULT_PROMPT_DELAY,
    DEFAULT_RESET_ON_RETURN,
    DOMAIN,
    MAX_ANSWER_TIMEOUT,
    MAX_PROMPT_DELAY,
    MIN_ANSWER_TIMEOUT,
    MIN_PROMPT_DELAY,
    PERSON_DOMAIN,
    SUBENTRY_TYPE_TRACKER,
)
from .issues import async_persons_with_virtual_tracker

TITLE = "Virtual Presence Tracker"

# The default is an empty list rather than no default, so that a form submitted
# without a selection reaches the "no_persons" check instead of failing
# voluptuous with a generic "required key not provided".
PERSONS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PERSONS, default=list): EntitySelector(
            EntitySelectorConfig(domain=PERSON_DOMAIN, multiple=True)
        )
    }
)

TRACKER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): TextSelector(),
        vol.Required(
            CONF_RESET_ON_RETURN, default=DEFAULT_RESET_ON_RETURN
        ): BooleanSelector(),
        vol.Required(
            CONF_ASK_ON_DEPARTURE, default=DEFAULT_ASK_ON_DEPARTURE
        ): BooleanSelector(),
        vol.Required(
            CONF_ANSWER_TIMEOUT, default=DEFAULT_ANSWER_TIMEOUT
        ): NumberSelector(
            NumberSelectorConfig(
                min=MIN_ANSWER_TIMEOUT,
                max=MAX_ANSWER_TIMEOUT,
                step=1,
                mode=NumberSelectorMode.BOX,
                unit_of_measurement="min",
            )
        ),
        vol.Required(CONF_PROMPT_DELAY, default=DEFAULT_PROMPT_DELAY): NumberSelector(
            NumberSelectorConfig(
                min=MIN_PROMPT_DELAY,
                max=MAX_PROMPT_DELAY,
                step=1,
                mode=NumberSelectorMode.BOX,
                unit_of_measurement="s",
            )
        ),
    }
)


@callback
def _suggested_persons(hass: HomeAssistant) -> list[str]:
    """Return the persons that Home Assistant can locate on its own.

    A person without a device tracker is exactly the person this integration
    exists for, so suggesting them as a *real* person would be wrong: once a
    virtual tracker is attached to them, switching it on would look like a real
    arrival and reset every tracker again.
    """
    return sorted(
        state.entity_id
        for state in hass.states.async_all(PERSON_DOMAIN)
        if state.attributes.get(ATTR_DEVICE_TRACKERS)
    )


@callback
def _person_error(
    hass: HomeAssistant, entry: ConfigEntry | None, persons: list[str]
) -> tuple[str, dict[str, str]] | None:
    """Return the error and its placeholders for a selection of real persons.

    A person that carries one of our own virtual trackers must not become a
    real person: switching that tracker on would look like a real arrival and
    reset every tracker. During the initial setup no tracker exists yet, so
    that check can only ever fire on reconfigure.
    """
    if not persons:
        return ("no_persons", {})
    if offenders := async_persons_with_virtual_tracker(hass, entry, persons):
        return ("person_has_virtual_tracker", {"persons": ", ".join(offenders)})
    return None


@callback
def _tracker_names(entry: ConfigEntry, skip: str | None = None) -> set[str]:
    """Return the case-folded names of the trackers of an entry."""
    return {
        subentry.title.casefold()
        for subentry in entry.get_subentries_of_type(SUBENTRY_TYPE_TRACKER)
        if subentry.subentry_id != skip
    }


class VirtualPresenceTrackerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Virtual Presence Tracker."""

    VERSION = 1

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return the subentry types this integration supports."""
        return {SUBENTRY_TYPE_TRACKER: TrackerSubentryFlowHandler}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}

        if user_input is not None:
            persons = user_input[CONF_PERSONS]
            if (error := _person_error(self.hass, None, persons)) is None:
                return self.async_create_entry(
                    title=TITLE, data={CONF_PERSONS: persons}
                )
            errors[CONF_PERSONS], placeholders = error

        suggested: dict[str, Any] = user_input or {
            CONF_PERSONS: _suggested_persons(self.hass)
        }
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(PERSONS_SCHEMA, suggested),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_on_create_entry(self, result: ConfigFlowResult) -> ConfigFlowResult:
        """Continue with the form that adds the first virtual tracker.

        An entry without a tracker does nothing, and the button that adds one
        sits on the integration's page - not on the device page the user lands
        on after the setup. Chaining the subentry flow onto the result puts the
        form in front of the user right away. The entry exists and is set up by
        the time this runs, which is why the chaining cannot happen in
        async_create_entry(): that one only accepts FlowType.CONFIG_FLOW.
        """
        subentry_result = await self.hass.config_entries.subentries.async_init(
            (result["result"].entry_id, SUBENTRY_TYPE_TRACKER),
            context=SubentryFlowContext(source=SOURCE_USER),
        )
        result["next_flow"] = (
            FlowType.CONFIG_SUBENTRIES_FLOW,
            subentry_result["flow_id"],
        )
        return result

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a change of the real persons."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}

        if user_input is not None:
            persons = user_input[CONF_PERSONS]
            if (error := _person_error(self.hass, entry, persons)) is None:
                # The update listener reloads the entry, so the manager picks
                # the new persons up.
                return self.async_update_and_abort(
                    entry, data_updates={CONF_PERSONS: persons}
                )
            errors[CONF_PERSONS], placeholders = error

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                PERSONS_SCHEMA, user_input or entry.data
            ),
            errors=errors,
            description_placeholders=placeholders,
        )


class TrackerSubentryFlowHandler(ConfigSubentryFlow):
    """Handle the subentry flow of a single virtual tracker."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Add a virtual tracker."""
        return self._async_tracker_step("user", None, user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Rename a virtual tracker or change its options."""
        return self._async_tracker_step(
            "reconfigure", self._get_reconfigure_subentry(), user_input
        )

    @callback
    def _async_tracker_step(
        self,
        step_id: str,
        subentry: ConfigSubentry | None,
        user_input: dict[str, Any] | None,
    ) -> SubentryFlowResult:
        """Show and handle the tracker form, for a new or an existing tracker."""
        entry = self._get_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            name = user_input[CONF_NAME].strip()
            # NumberSelector hands out floats; the options are whole minutes
            # and whole seconds, and that is what is stored.
            data = {
                CONF_RESET_ON_RETURN: user_input[CONF_RESET_ON_RETURN],
                CONF_ASK_ON_DEPARTURE: user_input[CONF_ASK_ON_DEPARTURE],
                CONF_ANSWER_TIMEOUT: int(user_input[CONF_ANSWER_TIMEOUT]),
                CONF_PROMPT_DELAY: int(user_input[CONF_PROMPT_DELAY]),
            }
            skip = subentry.subentry_id if subentry is not None else None
            if not name:
                errors[CONF_NAME] = "name_required"
            elif name.casefold() in _tracker_names(entry, skip):
                errors[CONF_NAME] = "name_exists"
            elif subentry is None:
                return self.async_create_entry(title=name, data=data)
            else:
                # The update listener reloads the entry; async_update_reload_
                # and_abort() refuses to run while an update listener exists.
                return self.async_update_and_abort(
                    entry, subentry, title=name, data=data
                )

        suggested: dict[str, Any] = user_input or {}
        if not suggested and subentry is not None:
            suggested = {CONF_NAME: subentry.title, **subentry.data}

        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(TRACKER_SCHEMA, suggested),
            errors=errors,
        )
