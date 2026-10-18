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
from homeassistant.const import CONF_NAME, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import SectionConfig, section
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from . import ble
from .const import (
    ATTR_DEVICE_TRACKERS,
    BINARY_SENSOR_DOMAIN,
    BUTTON_KEYS,
    CONF_ANSWER_TIMEOUT,
    CONF_ASK_LEFT_BEHIND,
    CONF_ASK_ON_DEPARTURE,
    CONF_AWAY_AFTER,
    CONF_BLE_SOURCES,
    CONF_BUTTON_AWAY_TYPES,
    CONF_BUTTON_HOME_TYPES,
    CONF_BUTTON_SOURCES,
    CONF_CREATE_PERSON,
    CONF_LEFT_BEHIND_OVERRIDE_DND,
    CONF_NOTIFY_ON_EXPIRY,
    CONF_NOTIFY_PERSONS,
    CONF_OVERRIDE_DND,
    CONF_PERSONS,
    CONF_PRESENCE_SOURCES,
    CONF_PROMPT_DELAY,
    CONF_REMIND_AFTER,
    CONF_REMINDER_TIMEOUT,
    CONF_RESET_ON_RETURN,
    DEFAULT_ANSWER_TIMEOUT,
    DEFAULT_ASK_LEFT_BEHIND,
    DEFAULT_AWAY_AFTER,
    DEFAULT_CREATE_PERSON,
    DEFAULT_LEFT_BEHIND_OVERRIDE_DND,
    DEFAULT_NOTIFY_ON_EXPIRY,
    DEFAULT_OVERRIDE_DND,
    DEFAULT_PROMPT_DELAY,
    DEFAULT_REMINDER_TIMEOUT,
    DEFAULT_RESET_ON_RETURN,
    DEVICE_TRACKER_DOMAIN,
    DOMAIN,
    EVENT_DOMAIN,
    FORM_OPTION_SECTIONS,
    MAX_ANSWER_TIMEOUT,
    MAX_AWAY_AFTER,
    MAX_PROMPT_DELAY,
    MAX_REMIND_AFTER,
    MAX_REMINDER_TIMEOUT,
    MIN_ANSWER_TIMEOUT,
    MIN_AWAY_AFTER,
    MIN_PROMPT_DELAY,
    MIN_REMIND_AFTER,
    MIN_REMINDER_TIMEOUT,
    NEW_TRACKER_ASK_ON_DEPARTURE,
    NEW_TRACKER_REMIND_AFTER,
    OPTION_DEFAULTS,
    PERSON_DOMAIN,
    SECTION_SOURCES,
    SUBENTRY_TYPE_TRACKER,
    SUGGESTED_BUTTON_AWAY_TYPE,
    SUGGESTED_BUTTON_HOME_TYPE,
)
from .issues import async_persons_with_virtual_tracker
from .manager import async_own_event_entities
from .presence import async_own_presence_entities

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


# What a new tracker is written with: every option spelled out, so that the
# switches on the tracker's device page have something to show from the start
# - and a new tracker asks and reminds (the default of a *missing* key stays
# "no" and "never", which is what every tracker from before the prompt and the
# reminder relies on).
NEW_TRACKER_OPTIONS: dict[str, bool | int] = {
    CONF_RESET_ON_RETURN: DEFAULT_RESET_ON_RETURN,
    CONF_ASK_ON_DEPARTURE: NEW_TRACKER_ASK_ON_DEPARTURE,
    CONF_ANSWER_TIMEOUT: DEFAULT_ANSWER_TIMEOUT,
    CONF_PROMPT_DELAY: DEFAULT_PROMPT_DELAY,
    CONF_REMIND_AFTER: NEW_TRACKER_REMIND_AFTER,
    CONF_REMINDER_TIMEOUT: DEFAULT_REMINDER_TIMEOUT,
    CONF_NOTIFY_ON_EXPIRY: DEFAULT_NOTIFY_ON_EXPIRY,
    CONF_OVERRIDE_DND: DEFAULT_OVERRIDE_DND,
    CONF_AWAY_AFTER: DEFAULT_AWAY_AFTER,
    CONF_ASK_LEFT_BEHIND: DEFAULT_ASK_LEFT_BEHIND,
    CONF_LEFT_BEHIND_OVERRIDE_DND: DEFAULT_LEFT_BEHIND_OVERRIDE_DND,
}

# The timings of the form (M3g): range and unit of each.
NUMBER_OPTIONS: dict[str, tuple[int, int, str]] = {
    CONF_ANSWER_TIMEOUT: (MIN_ANSWER_TIMEOUT, MAX_ANSWER_TIMEOUT, UnitOfTime.MINUTES),
    CONF_PROMPT_DELAY: (MIN_PROMPT_DELAY, MAX_PROMPT_DELAY, UnitOfTime.SECONDS),
    CONF_REMIND_AFTER: (MIN_REMIND_AFTER, MAX_REMIND_AFTER, UnitOfTime.HOURS),
    CONF_REMINDER_TIMEOUT: (
        MIN_REMINDER_TIMEOUT,
        MAX_REMINDER_TIMEOUT,
        UnitOfTime.MINUTES,
    ),
    CONF_AWAY_AFTER: (MIN_AWAY_AFTER, MAX_AWAY_AFTER, UnitOfTime.MINUTES),
}

SOURCE_KEYS = (CONF_BUTTON_SOURCES, CONF_PRESENCE_SOURCES, CONF_BLE_SOURCES)


def _option_selector(key: str) -> BooleanSelector | NumberSelector:
    """Return the field of one option of the form."""
    if key not in NUMBER_OPTIONS:
        return BooleanSelector()
    minimum, maximum, unit = NUMBER_OPTIONS[key]
    return NumberSelector(
        NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=1,
            mode=NumberSelectorMode.BOX,
            unit_of_measurement=unit,
        )
    )


def _option_value(key: str, value: Any) -> bool | int:
    """Return an option of the form the way it is stored.

    The number selector hands back a float; the options have always been
    stored as whole numbers.
    """
    return int(value) if key in NUMBER_OPTIONS else bool(value)


@callback
def _applied_options(subentry: ConfigSubentry | None) -> dict[str, Any]:
    """Return the values the options of the form have right now.

    For a new tracker the values it will be written with; for an existing one
    what it has stored - and for a key it does not carry, the value that
    applies while the key is missing (a tracker from before the reminder shows
    "never", which is what it does), not the one a new tracker would get.
    """
    keys = [key for keys in FORM_OPTION_SECTIONS.values() for key in keys]
    if subentry is None:
        return {key: NEW_TRACKER_OPTIONS[key] for key in keys}
    return {key: subentry.data.get(key, OPTION_DEFAULTS[key]) for key in keys}


@callback
def _has_sources(subentry: ConfigSubentry | None) -> bool:
    """Return whether an existing tracker has any button or presence source."""
    return subentry is not None and any(subentry.data.get(key) for key in SOURCE_KEYS)


def _tracker_schema(
    entry: ConfigEntry,
    subentry: ConfigSubentry | None,
    own_events: list[str],
    own_presence: list[str],
    ble_options: list[SelectOptionDict] | None,
    sources_expanded: bool,
) -> vol.Schema:
    """Return the form of one virtual tracker.

    At the top, always visible: the name, who is asked and - for a *new*
    tracker only - the offer to create the person it needs (M2g). An existing
    one either has its person by now, or the user said no once and is not
    asked again.

    Only the real persons of this household can be asked, so they are what the
    person selector offers. What the tracker already has stored is offered too,
    even if it is not a real person any more: the form would otherwise be
    impossible to submit unchanged, and the stale recipient is reported with an
    error of our own instead of a voluptuous failure.

    Then three collapsible sections (M3g) with what is set once: the timings
    of the questions and the expiry notice, the reminder, and the optional
    sources - buttons (M3d), whose meaning is asked in a second step, presence
    sources (M3e) and, only while Bluetooth is set up (``ble_options`` is not
    None), Bluetooth devices, plus "Away after". The integration's own event
    entities (``own_events``) and its own device trackers and sensor
    (``own_presence``) are not offered. What is switched depending on the
    situation is a switch on the tracker's device page instead.

    Two rules of Home Assistant's sections shape this. A section key never
    gets a default: the frontend would take that empty default as the
    section's data and drop the defaults and suggestions of the fields inside.
    And an error of a field inside a section has to be reported under the
    section's key, the only place the frontend shows it.
    """
    real_persons: list[str] = list(entry.data.get(CONF_PERSONS, []))
    stored: list[str] = list(
        subentry.data.get(CONF_NOTIFY_PERSONS, ()) if subentry is not None else ()
    )
    candidates = list(dict.fromkeys(real_persons + stored))
    applied = _applied_options(subentry)
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
    for section_key, keys in FORM_OPTION_SECTIONS.items():
        if section_key == SECTION_SOURCES:
            continue
        schema[vol.Optional(section_key)] = section(
            vol.Schema(
                {
                    vol.Required(key, default=applied[key]): _option_selector(key)
                    for key in keys
                }
            ),
            SectionConfig(collapsed=True),
        )

    sources: dict[Any, Any] = {}
    selector_config = EntitySelectorConfig(domain=EVENT_DOMAIN, multiple=True)
    if own_events:
        # The questions entities of the trackers are event entities too, but
        # no buttons.
        selector_config["exclude_entities"] = own_events
    sources[vol.Optional(CONF_BUTTON_SOURCES, default=list)] = EntitySelector(
        selector_config
    )
    presence_config = EntitySelectorConfig(
        domain=[DEVICE_TRACKER_DOMAIN, BINARY_SENSOR_DOMAIN], multiple=True
    )
    if own_presence:
        # A virtual tracker following a virtual tracker - or the household
        # sensor, which follows all of them - would be a loop.
        presence_config["exclude_entities"] = own_presence
    sources[vol.Optional(CONF_PRESENCE_SOURCES, default=list)] = EntitySelector(
        presence_config
    )
    if ble_options is not None:
        sources[vol.Optional(CONF_BLE_SOURCES, default=list)] = SelectSelector(
            SelectSelectorConfig(
                options=ble_options,
                multiple=True,
                # A device out of range right now is not in the list, so its
                # address can be typed in.
                custom_value=True,
                mode=SelectSelectorMode.DROPDOWN,
            )
        )
    for key in FORM_OPTION_SECTIONS[SECTION_SOURCES]:
        sources[vol.Required(key, default=applied[key])] = _option_selector(key)
    schema[vol.Optional(SECTION_SOURCES)] = section(
        vol.Schema(sources), SectionConfig(collapsed=not sources_expanded)
    )
    return vol.Schema(schema)


@callback
def _ble_options(hass: HomeAssistant, stored: list[str]) -> list[SelectOptionDict]:
    """Return the Bluetooth devices the form offers, strongest signal first.

    Every device Home Assistant hears right now, named after the device of
    that Bluetooth address in the device registry where there is one, else
    after what it advertises, else just by its address. The addresses the
    tracker already has follow, so that a device out of range stays selected.
    """
    registry = dr.async_get(hass)
    options: dict[str, SelectOptionDict] = {}

    def add(address: str, name: str | None) -> None:
        """Offer one address, once."""
        if address in options:
            return
        name = ble.registry_name(registry, address) or name
        label = f"{name} ({address})" if name else address
        options[address] = SelectOptionDict(value=address, label=label)

    heard = sorted(
        ble.async_heard_devices(hass),
        key=lambda device: device.rssi if device.rssi is not None else -1000,
        reverse=True,
    )
    for device in heard:
        add(device.address, device.name)
    for raw in stored:
        add(ble.normalize_address(raw) or raw, None)
    return list(options.values())


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

        The options are stored flat in the subentry data, under the keys they
        have always had; only the form groups them into sections. A section
        that was not sent at all leaves its values as they are. With button
        sources chosen the flow goes on to their event types; without, the
        tracker is stored right away.
        """
        entry = self._get_entry()
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}

        if user_input is not None:
            name = user_input[CONF_NAME].strip()
            recipients = list(user_input[CONF_NOTIFY_PERSONS])
            # A new tracker is written with all of its options spelled out; an
            # existing one keeps whatever its switches have written since.
            data: dict[str, Any] = (
                {**NEW_TRACKER_OPTIONS, CONF_NOTIFY_PERSONS: recipients}
                if subentry is None
                else {**subentry.data, CONF_NOTIFY_PERSONS: recipients}
            )
            for section_key, keys in FORM_OPTION_SECTIONS.items():
                values = user_input.get(section_key) or {}
                for key in keys:
                    if key in values:
                        data[key] = _option_value(key, values[key])
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
            sources: dict[str, Any] | None = user_input.get(SECTION_SOURCES)
            addresses: list[str] = []
            invalid: list[str] = []
            for raw in (sources or {}).get(CONF_BLE_SOURCES, []):
                if (address := ble.normalize_address(raw)) is None:
                    invalid.append(raw)
                else:
                    addresses.append(address)
            if not name:
                errors[CONF_NAME] = "name_required"
            elif name.casefold() in _tracker_names(entry, skip):
                errors[CONF_NAME] = "name_exists"
            elif strangers:
                errors[CONF_NOTIFY_PERSONS] = "person_not_real"
                placeholders = {"persons": ", ".join(strangers)}
            elif invalid:
                # Under the section's key: the frontend shows no error of a
                # field inside a section, only one of the section itself.
                errors[SECTION_SOURCES] = "invalid_ble_address"
                placeholders = {"addresses": ", ".join(invalid)}
            else:
                self._subentry = subentry
                self._name = name
                self._data = data
                if sources is None:
                    # The sources were not sent: they stay as they are,
                    # button event types included.
                    return self._async_finish()
                # A tracker without presence sources carries neither key, and
                # the Bluetooth field is only there while Bluetooth is set up -
                # without it, the stored addresses are kept as they are.
                if presence := list(sources.get(CONF_PRESENCE_SOURCES, [])):
                    data[CONF_PRESENCE_SOURCES] = presence
                else:
                    data.pop(CONF_PRESENCE_SOURCES, None)
                if CONF_BLE_SOURCES in sources:
                    if addresses:
                        data[CONF_BLE_SOURCES] = list(dict.fromkeys(addresses))
                    else:
                        data.pop(CONF_BLE_SOURCES, None)
                if buttons := list(sources.get(CONF_BUTTON_SOURCES, [])):
                    data[CONF_BUTTON_SOURCES] = buttons
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
            # what it has, nested the way the form's sections are.
            suggested = (
                {CONF_NOTIFY_PERSONS: list(entry.data.get(CONF_PERSONS, []))}
                if subentry is None
                else _stored_suggestions(subentry)
            )
        own_events = sorted(async_own_event_entities(self.hass))
        own_presence = sorted(async_own_presence_entities(self.hass))
        if (sources_suggested := suggested.get(SECTION_SOURCES)) is not None:
            # One of our own event entities, device trackers or the sensor
            # that got stored somehow is left out rather than offered: the
            # selector would refuse it on submit.
            sources_suggested = dict(sources_suggested)
            for key, own in (
                (CONF_BUTTON_SOURCES, own_events),
                (CONF_PRESENCE_SOURCES, own_presence),
            ):
                if key in sources_suggested:
                    sources_suggested[key] = [
                        entity_id
                        for entity_id in sources_suggested[key]
                        if entity_id not in own
                    ]
            suggested = {**suggested, SECTION_SOURCES: sources_suggested}
        ble_options = (
            _ble_options(
                self.hass,
                list(subentry.data.get(CONF_BLE_SOURCES, []))
                if subentry is not None
                else [],
            )
            if ble.async_bluetooth_loaded(self.hass)
            else None
        )
        # The sources are open where they matter: for a tracker that has some,
        # and when the form comes back with an error inside them.
        sources_expanded = _has_sources(subentry) or SECTION_SOURCES in errors

        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(
                _tracker_schema(
                    entry,
                    subentry,
                    own_events,
                    own_presence,
                    ble_options,
                    sources_expanded,
                ),
                suggested,
            ),
            errors=errors,
            description_placeholders=placeholders,
        )


@callback
def _stored_suggestions(subentry: ConfigSubentry) -> dict[str, Any]:
    """Return what an existing tracker's form comes up with, section by section."""
    applied = _applied_options(subentry)
    suggested: dict[str, Any] = {CONF_NAME: subentry.title}
    if CONF_NOTIFY_PERSONS in subentry.data:
        suggested[CONF_NOTIFY_PERSONS] = list(subentry.data[CONF_NOTIFY_PERSONS])
    for section_key, keys in FORM_OPTION_SECTIONS.items():
        suggested[section_key] = {key: applied[key] for key in keys}
    for key in SOURCE_KEYS:
        if key in subentry.data:
            suggested[SECTION_SOURCES][key] = list(subentry.data[key])
    return suggested
