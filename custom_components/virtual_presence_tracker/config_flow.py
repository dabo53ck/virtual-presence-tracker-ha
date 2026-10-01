"""Config flow for the Virtual Presence Tracker integration.

The single config entry holds the real persons of the household; every virtual
tracker is a config subentry of it. A tracker is identified by its subentry
ID, so its name is free to change at any time.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.event import ATTR_EVENT_TYPES
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
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .const import (
    ATTR_DEVICE_TRACKERS,
    BUTTON_KEYS,
    CONF_ANSWER_TIMEOUT,
    CONF_ASK_ON_DEPARTURE,
    CONF_BUTTON_AWAY_TYPES,
    CONF_BUTTON_HOME_TYPES,
    CONF_BUTTON_SOURCES,
    CONF_CREATE_PERSON,
    CONF_NOTIFY_ON_EXPIRY,
    CONF_NOTIFY_PERSONS,
    CONF_OVERRIDE_DND,
    CONF_PERSONS,
    CONF_PROMPT_DELAY,
    CONF_REMIND_AFTER,
    CONF_REMINDER_TIMEOUT,
    CONF_RESET_ON_RETURN,
    DEFAULT_ANSWER_TIMEOUT,
    DEFAULT_CREATE_PERSON,
    DEFAULT_NOTIFY_ON_EXPIRY,
    DEFAULT_OVERRIDE_DND,
    DEFAULT_PROMPT_DELAY,
    DEFAULT_REMINDER_TIMEOUT,
    DEFAULT_RESET_ON_RETURN,
    DOMAIN,
    EVENT_DOMAIN,
    NEW_TRACKER_ASK_ON_DEPARTURE,
    NEW_TRACKER_REMIND_AFTER,
    PERSON_DOMAIN,
    SUBENTRY_TYPE_TRACKER,
    SUGGESTED_BUTTON_AWAY_TYPE,
    SUGGESTED_BUTTON_HOME_TYPE,
)
from .issues import async_persons_with_virtual_tracker
from .manager import async_own_event_entities

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


def _tracker_schema(
    entry: ConfigEntry, subentry: ConfigSubentry | None, own_events: list[str]
) -> vol.Schema:
    """Return the form of one virtual tracker: its name and who is asked.

    Everything else a tracker can be set to has an entity of its own on the
    tracker's device page (M2f), so the form only holds what has nowhere else
    to go: the name, which is the subentry title, and the recipients, which are
    a list of persons rather than a value.

    Only the real persons of this household can be asked, so they are what the
    person selector offers. What the tracker already has stored is offered too,
    even if it is not a real person any more: the form would otherwise be
    impossible to submit unchanged, and the stale recipient is reported with an
    error of our own instead of a voluptuous failure.

    A *new* tracker is additionally offered the person it needs to be of any
    use (M2g). An existing one is not: it either has its person by now, or the
    user said no once and is not asked again.

    The button sources (M3d) come last and are optional: what their events
    mean depends on the entities chosen, so that is asked in a second step.
    The integration's own event entities (``own_events``) are not offered.
    """
    real_persons: list[str] = list(entry.data.get(CONF_PERSONS, []))
    stored: list[str] = list(
        subentry.data.get(CONF_NOTIFY_PERSONS, ()) if subentry is not None else ()
    )
    candidates = list(dict.fromkeys(real_persons + stored))
    schema: dict[Any, Any] = {
        vol.Required(CONF_NAME): TextSelector(),
        # An empty selection is a valid answer: it means that the integration
        # sends nothing at all.
        vol.Required(CONF_NOTIFY_PERSONS, default=list): EntitySelector(
            EntitySelectorConfig(
                domain=PERSON_DOMAIN, multiple=True, include_entities=candidates
            )
        ),
    }
    if subentry is None:
        schema[vol.Required(CONF_CREATE_PERSON, default=DEFAULT_CREATE_PERSON)] = (
            BooleanSelector()
        )
    selector_config = EntitySelectorConfig(domain=EVENT_DOMAIN, multiple=True)
    if own_events:
        # The questions entities of the trackers are event entities too, but
        # no buttons.
        selector_config["exclude_entities"] = own_events
    schema[vol.Optional(CONF_BUTTON_SOURCES, default=list)] = EntitySelector(
        selector_config
    )
    return vol.Schema(schema)


@callback
def _event_types(hass: HomeAssistant, entity_id: str) -> list[str] | None:
    """Return the event types an event entity offers, or None if unknown.

    Read from the state, where every event entity publishes them, and from the
    entity registry when there is no state yet - the registry keeps the
    capabilities of an entity whose integration has not been set up.
    """
    event_types: Any = None
    if (state := hass.states.get(entity_id)) is not None:
        event_types = state.attributes.get(ATTR_EVENT_TYPES)
    if (
        not event_types
        and (registry_entry := er.async_get(hass).async_get(entity_id)) is not None
    ):
        event_types = (registry_entry.capabilities or {}).get(ATTR_EVENT_TYPES)
    if not event_types or not isinstance(event_types, list | tuple):
        return None
    return [str(event_type) for event_type in event_types]


@callback
def _button_schema(
    hass: HomeAssistant, sources: list[str], stored: dict[str, Any]
) -> tuple[vol.Schema, list[str], bool]:
    """Return the form of the event types, its options and whether free entry is on.

    The options are every event type the chosen entities offer, in the order
    they offer them. An entity whose event types are not known - it has no
    state and no registry entry yet - would leave the user without anything to
    pick, so free entry is switched on then, and the types the tracker already
    has stored are offered as well, so that none of them is lost on the way.
    """
    known: list[str] = []
    unknown = False
    for entity_id in sources:
        if (event_types := _event_types(hass, entity_id)) is None:
            unknown = True
            continue
        known.extend(event_types)
    if unknown:
        known.extend(stored.get(CONF_BUTTON_HOME_TYPES, []))
        known.extend(stored.get(CONF_BUTTON_AWAY_TYPES, []))
    options = list(dict.fromkeys(known))
    selector = SelectSelector(
        SelectSelectorConfig(
            options=options,
            multiple=True,
            custom_value=unknown,
            mode=SelectSelectorMode.LIST,
        )
    )
    schema = vol.Schema(
        {
            vol.Optional(CONF_BUTTON_HOME_TYPES, default=list): selector,
            vol.Optional(CONF_BUTTON_AWAY_TYPES, default=list): selector,
        }
    )
    return schema, options, unknown


@callback
def _suggested_button_types(
    stored: dict[str, Any], options: list[str], free_entry: bool
) -> dict[str, list[str]]:
    """Return what the form of the event types comes up with.

    What the tracker has stored, as far as the chosen entities still offer it.
    A tracker without such a mapping - a new one, or one that had no button
    sources so far - gets a short press for "home" and a long press for "away"
    where the entities offer a "press" at all, and nothing otherwise.
    """
    suggested = {
        key: [
            event_type
            for event_type in stored.get(key, [])
            if free_entry or event_type in options
        ]
        for key in (CONF_BUTTON_HOME_TYPES, CONF_BUTTON_AWAY_TYPES)
    }
    if any(suggested.values()):
        return suggested
    if SUGGESTED_BUTTON_HOME_TYPE not in options:
        return suggested
    return {
        CONF_BUTTON_HOME_TYPES: [SUGGESTED_BUTTON_HOME_TYPE],
        CONF_BUTTON_AWAY_TYPES: (
            [SUGGESTED_BUTTON_AWAY_TYPE]
            if SUGGESTED_BUTTON_AWAY_TYPE in options
            else []
        ),
    }


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

    def __init__(self) -> None:
        """Start with nothing carried over from the first step."""
        super().__init__()
        # What the first step decided, while the second one asks for the event
        # types of the button sources.
        self._subentry: ConfigSubentry | None = None
        self._name = ""
        self._data: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Add a virtual tracker."""
        return await self._async_tracker_step("user", None, user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Rename a virtual tracker or change its options."""
        return await self._async_tracker_step(
            "reconfigure", self._get_reconfigure_subentry(), user_input
        )

    async def async_step_buttons(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Ask what the events of the chosen button sources mean.

        Only reached with at least one source. A type may mean "home" or
        "away" but not both, and at least one type has to mean something -
        a source that switches nothing is no source.
        """
        sources: list[str] = self._data[CONF_BUTTON_SOURCES]
        stored: dict[str, Any] = (
            dict(self._subentry.data) if self._subentry is not None else {}
        )
        schema, options, free_entry = _button_schema(self.hass, sources, stored)
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {"name": self._name}

        if user_input is not None:
            home = list(dict.fromkeys(user_input.get(CONF_BUTTON_HOME_TYPES, [])))
            away = list(dict.fromkeys(user_input.get(CONF_BUTTON_AWAY_TYPES, [])))
            if overlap := [event_type for event_type in home if event_type in away]:
                errors["base"] = "button_types_overlap"
                placeholders["types"] = ", ".join(overlap)
            elif not home and not away:
                errors["base"] = "button_types_missing"
            else:
                self._data[CONF_BUTTON_HOME_TYPES] = home
                self._data[CONF_BUTTON_AWAY_TYPES] = away
                return self._async_finish()
        placeholders.setdefault("types", "")

        return self.async_show_form(
            step_id="buttons",
            data_schema=self.add_suggested_values_to_schema(
                schema,
                user_input or _suggested_button_types(stored, options, free_entry),
            ),
            errors=errors,
            description_placeholders=placeholders,
        )

    @callback
    def _async_finish(self) -> SubentryFlowResult:
        """Store the tracker the two steps have put together."""
        if self._subentry is None:
            return self.async_create_entry(title=self._name, data=self._data)
        # The update listener decides whether the entry has to be reloaded;
        # async_update_reload_and_abort() refuses to run while an update
        # listener exists. A change of nothing but the button sources keeps
        # the entry loaded.
        return self.async_update_and_abort(
            self._get_entry(), self._subentry, title=self._name, data=self._data
        )

    async def _async_tracker_step(
        self,
        step_id: str,
        subentry: ConfigSubentry | None,
        user_input: dict[str, Any] | None,
    ) -> SubentryFlowResult:
        """Show and handle the tracker form, for a new or an existing tracker.

        With button sources chosen the flow goes on to their event types;
        without, the tracker is stored right away.
        """
        entry = self._get_entry()
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}

        if user_input is not None:
            name = user_input[CONF_NAME].strip()
            recipients = list(user_input[CONF_NOTIFY_PERSONS])
            # A new tracker is written with all of its options spelled out, so
            # that the entities of the tracker's device page have something to
            # show from the start - and a new tracker asks and reminds (the
            # code default for a *missing* key stays "no" and "never", which is
            # what every tracker from before the prompt and the reminder relies
            # on). An existing tracker keeps whatever its entities have written
            # since.
            data = (
                {
                    CONF_RESET_ON_RETURN: DEFAULT_RESET_ON_RETURN,
                    CONF_ASK_ON_DEPARTURE: NEW_TRACKER_ASK_ON_DEPARTURE,
                    CONF_ANSWER_TIMEOUT: DEFAULT_ANSWER_TIMEOUT,
                    CONF_PROMPT_DELAY: DEFAULT_PROMPT_DELAY,
                    CONF_REMIND_AFTER: NEW_TRACKER_REMIND_AFTER,
                    CONF_REMINDER_TIMEOUT: DEFAULT_REMINDER_TIMEOUT,
                    CONF_NOTIFY_PERSONS: recipients,
                    CONF_NOTIFY_ON_EXPIRY: DEFAULT_NOTIFY_ON_EXPIRY,
                    CONF_OVERRIDE_DND: DEFAULT_OVERRIDE_DND,
                }
                if subentry is None
                else {**subentry.data, CONF_NOTIFY_PERSONS: recipients}
            )
            if subentry is None and user_input.get(CONF_CREATE_PERSON):
                # Only a marker: the tracker's device tracker entity does not
                # exist until the entry has been set up with this subentry, so
                # the person itself is created afterwards (persons.py).
                data[CONF_CREATE_PERSON] = True
            skip = subentry.subentry_id if subentry is not None else None
            strangers = [
                person
                for person in recipients
                if person not in entry.data.get(CONF_PERSONS, [])
            ]
            if not name:
                errors[CONF_NAME] = "name_required"
            elif name.casefold() in _tracker_names(entry, skip):
                errors[CONF_NAME] = "name_exists"
            elif strangers:
                errors[CONF_NOTIFY_PERSONS] = "person_not_real"
                placeholders = {"persons": ", ".join(strangers)}
            else:
                self._subentry = subentry
                self._name = name
                self._data = data
                if sources := list(user_input.get(CONF_BUTTON_SOURCES, [])):
                    data[CONF_BUTTON_SOURCES] = sources
                    return await self.async_step_buttons()
                # No source left: the event types go with the last of them.
                for key in BUTTON_KEYS:
                    data.pop(key, None)
                return self._async_finish()

        suggested: dict[str, Any] = user_input or {}
        if not suggested:
            # A new tracker comes up with every real person ticked: asking
            # everybody is the answer that needs no thought, and taking
            # somebody out is one click. An existing tracker comes up with
            # what it has.
            suggested = (
                {CONF_NOTIFY_PERSONS: list(entry.data.get(CONF_PERSONS, []))}
                if subentry is None
                else {CONF_NAME: subentry.title, **subentry.data}
            )
        own_events = sorted(async_own_event_entities(self.hass))
        if CONF_BUTTON_SOURCES in suggested:
            # One of our own event entities that got stored somehow is left out
            # rather than offered: the selector would refuse it on submit.
            suggested = {
                **suggested,
                CONF_BUTTON_SOURCES: [
                    entity_id
                    for entity_id in suggested[CONF_BUTTON_SOURCES]
                    if entity_id not in own_events
                ],
            }

        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(
                _tracker_schema(entry, subentry, own_events), suggested
            ),
            errors=errors,
            description_placeholders=placeholders,
        )
