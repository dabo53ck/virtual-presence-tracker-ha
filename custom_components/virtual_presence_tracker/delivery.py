"""Built-in delivery of the questions through the Companion App.

A tracker whose recipients are set sends its questions - the prompt when the
house empties (M2b) and the reminder about a tracker that has been on for a
long time (M3a) - to their phones as an actionable `mobile_app` notification,
and takes the message back as soon as the question ends, whatever ended it.
Without recipients nothing is sent at all and both stay what they were: an
event entity and an action (see docs/DESIGN.md).

Nothing here imports the `mobile_app` or the `notify` component: the
integration works without either of them, and the mapping only needs the config
entries and the service registry.
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import partial
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.util import slugify

from .const import (
    ACTION_NO_PREFIX,
    ACTION_REMIND_NO_PREFIX,
    ACTION_REMIND_YES_PREFIX,
    ACTION_YES_PREFIX,
    ATTR_PROMPT_ID,
    ATTR_REMINDER_ID,
    ATTR_USER_ID,
    CLEAR_NOTIFICATION,
    CONF_ANSWER_TIMEOUT,
    CONF_DEVICE_NAME,
    CONF_NOTIFY_ON_EXPIRY,
    CONF_NOTIFY_PERSONS,
    CONF_PERSONS,
    CONF_USER_ID,
    DEFAULT_ANSWER_TIMEOUT,
    DEFAULT_NOTIFY_ON_EXPIRY,
    DOMAIN,
    EVENT_EXPIRED,
    EVENT_NOTIFICATION_ACTION,
    EVENT_PROMPT_STARTED,
    EVENT_REMINDER_EXPIRED,
    EVENT_REMINDER_STARTED,
    MOBILE_APP_DOMAIN,
    NOTIFICATION_ICON,
    NOTIFICATION_INFO_TAG_PREFIX,
    NOTIFICATION_REMINDER_TAG_PREFIX,
    NOTIFICATION_TAG_PREFIX,
    NOTIFY_DOMAIN,
    PERSON_DOMAIN,
    SUBENTRY_TYPE_TRACKER,
)
from .messages import (
    async_answer_titles,
    async_expired_message,
    async_expired_title,
    async_prompt_message,
    async_prompt_title,
    async_reminder_answer_titles,
    async_reminder_expired_message,
    async_reminder_message,
    async_reminder_title,
)

if TYPE_CHECKING:
    from . import VirtualPresenceTrackerConfigEntry
    from .manager import HouseholdManager

_LOGGER = logging.getLogger(__name__)


@callback
def async_recipients(entry: ConfigEntry, subentry_id: str) -> list[str]:
    """Return the persons a tracker asks, as far as they are still real.

    A person can lose their real-person status long after they were picked as
    a recipient. Asking them anyway would be wrong - the prompt is about a
    household they are no longer part of - so they are dropped here, quietly.
    """
    subentry = entry.subentries.get(subentry_id)
    if subentry is None:
        return []
    real_persons = entry.data.get(CONF_PERSONS, [])
    recipients = []
    for person in subentry.data.get(CONF_NOTIFY_PERSONS, ()):
        if person in real_persons:
            recipients.append(person)
        else:
            _LOGGER.debug(
                "Not asking %s about %s: not a real person any more",
                person,
                subentry.title,
            )
    return recipients


@callback
def async_notify_services(hass: HomeAssistant, person: str) -> list[str]:
    """Return the classic notify services of the phones of one person.

    The `mobile_app` config entries of a phone carry the Home Assistant user it
    is signed in with, and the person entity carries the same user: that is the
    whole mapping. A person with several phones gets several services; a person
    without a user, without a registration or without push support gets none.
    """
    state = hass.states.get(person)
    if state is None or not (user_id := state.attributes.get(ATTR_USER_ID)):
        return []

    services: dict[str, None] = {}
    for entry in hass.config_entries.async_entries(MOBILE_APP_DOMAIN):
        if entry.data.get(CONF_USER_ID) != user_id:
            continue
        if not (device_name := entry.data.get(CONF_DEVICE_NAME)):
            continue
        # How the notify component names the service of one target: the
        # integration name and the target, slugified as a whole.
        service = slugify(f"{MOBILE_APP_DOMAIN}_{device_name}")
        if hass.services.has_service(NOTIFY_DOMAIN, service):
            services[service] = None
        else:
            _LOGGER.debug("No notify service %s for %s", service, person)
    return list(services)


class PromptDelivery:
    """Send the questions of a config entry to the phones of their recipients.

    Named after the prompt it was built for (M2b); it carries the reminder of
    M3a as well, which is the same message mechanics with texts, a tag and
    button names of its own.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: VirtualPresenceTrackerConfigEntry,
        manager: HouseholdManager,
    ) -> None:
        """Initialise the delivery of an entry. Call async_start() to begin."""
        self.hass = hass
        self.entry = entry
        self._manager = manager
        self._unsubs: list[CALLBACK_TYPE] = []

    @callback
    def async_start(self) -> None:
        """Follow the questions of every tracker and the answers of the phones.

        Adding, changing or removing a tracker reloads the entry, so the
        listeners never go stale.
        """
        for subentry in self.entry.get_subentries_of_type(SUBENTRY_TYPE_TRACKER):
            self._unsubs.append(
                self._manager.async_add_prompt_listener(
                    subentry.subentry_id,
                    partial(self._async_prompt_event, subentry.subentry_id),
                )
            )
            self._unsubs.append(
                self._manager.async_add_reminder_listener(
                    subentry.subentry_id,
                    partial(self._async_reminder_event, subentry.subentry_id),
                )
            )
        self._unsubs.append(
            self.hass.bus.async_listen(
                EVENT_NOTIFICATION_ACTION, self._async_notification_action
            )
        )

    @callback
    def async_stop(self) -> None:
        """Stop listening. Messages that are on their way are cancelled."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    @callback
    def _async_services_of(self, subentry_id: str) -> list[str]:
        """Return the notify services of every phone a tracker asks on."""
        return [
            service
            for person in async_recipients(self.entry, subentry_id)
            for service in async_notify_services(self.hass, person)
        ]

    @callback
    def _async_prompt_event(
        self, subentry_id: str, event_type: str, data: dict[str, Any]
    ) -> None:
        """Send or take back the message of one prompt."""
        subentry = self.entry.subentries.get(subentry_id)
        if subentry is None:
            return
        services = self._async_services_of(subentry_id)
        if not services:
            return

        prompt_id: str = data[ATTR_PROMPT_ID]
        if event_type == EVENT_PROMPT_STARTED:
            payloads = [self._async_prompt_payload(subentry, prompt_id)]
        else:
            # Every other event ends the prompt, so the question goes away.
            payloads = [_clear_payload(NOTIFICATION_TAG_PREFIX, prompt_id)]
            if event_type == EVENT_EXPIRED and subentry.data.get(
                CONF_NOTIFY_ON_EXPIRY, DEFAULT_NOTIFY_ON_EXPIRY
            ):
                payloads.append(self._async_expired_payload(subentry, prompt_id))

        self.entry.async_create_background_task(
            self.hass,
            self._async_send(services, payloads),
            name=f"{DOMAIN} {event_type} {prompt_id}",
        )

    @callback
    def _async_reminder_event(
        self, subentry_id: str, event_type: str, data: dict[str, Any]
    ) -> None:
        """Send or take back the message of one reminder.

        The same mechanics as the prompt, the expiry notice included: the
        option is called "notice if unanswered" and says nothing about which
        of the two questions went unanswered, so a reminder that nobody
        answers reports that as well - with a text of its own, because the
        consequence is the opposite one (the tracker stays at home).
        """
        subentry = self.entry.subentries.get(subentry_id)
        if subentry is None:
            return
        services = self._async_services_of(subentry_id)
        if not services:
            return

        reminder_id: str = data[ATTR_REMINDER_ID]
        if event_type == EVENT_REMINDER_STARTED:
            payloads = [
                self._async_reminder_payload(subentry, subentry_id, reminder_id)
            ]
        else:
            # Every other event ends the reminder, so the question goes away.
            payloads = [_clear_payload(NOTIFICATION_REMINDER_TAG_PREFIX, reminder_id)]
            if event_type == EVENT_REMINDER_EXPIRED and subentry.data.get(
                CONF_NOTIFY_ON_EXPIRY, DEFAULT_NOTIFY_ON_EXPIRY
            ):
                payloads.append(
                    self._async_reminder_expired_payload(subentry, reminder_id)
                )

        self.entry.async_create_background_task(
            self.hass,
            self._async_send(services, payloads),
            name=f"{DOMAIN} {event_type} {reminder_id}",
        )

    async def _async_send(
        self, services: Iterable[str], payloads: Iterable[dict[str, Any]]
    ) -> None:
        """Call the notify services, one phone and one message at a time.

        A phone that cannot be reached must not keep the others from being
        told, and none of it may reach the state machine: the prompt is open or
        over regardless of what a notify service says.
        """
        for service in services:
            for payload in payloads:
                try:
                    await self.hass.services.async_call(
                        NOTIFY_DOMAIN, service, payload, blocking=True
                    )
                except Exception as err:  # noqa: BLE001 - a phone is not worth failing for
                    _LOGGER.warning(
                        "Could not notify %s.%s: %s", NOTIFY_DOMAIN, service, err
                    )

    @callback
    def _async_prompt_payload(
        self, subentry: ConfigSubentry, prompt_id: str
    ) -> dict[str, Any]:
        """Return the actionable notification that asks the question."""
        minutes = int(subentry.data.get(CONF_ANSWER_TIMEOUT, DEFAULT_ANSWER_TIMEOUT))
        yes, no = async_answer_titles(self.hass)
        return {
            "title": async_prompt_title(self.hass, subentry.title),
            "message": async_prompt_message(self.hass, minutes),
            "data": {
                "tag": f"{NOTIFICATION_TAG_PREFIX}{prompt_id}",
                "actions": [
                    {"action": f"{ACTION_YES_PREFIX}{prompt_id}", "title": yes},
                    {"action": f"{ACTION_NO_PREFIX}{prompt_id}", "title": no},
                ],
                # Android: a question with a deadline is worth waking the phone
                # for, and it is worthless once the deadline has passed.
                "ttl": 0,
                "priority": "high",
                "timeout": minutes * 60,
                # iOS: the same idea, in Apple's words.
                "push": {"interruption-level": "time-sensitive"},
                # Whose question this is: the icon beside the message is ours
                # instead of the Companion App's own.
                "icon_url": NOTIFICATION_ICON,
            },
        }

    @callback
    def _async_reminder_payload(
        self, subentry: ConfigSubentry, subentry_id: str, reminder_id: str
    ) -> dict[str, Any]:
        """Return the actionable notification that asks whether somebody is still in.

        The delivery hints are the prompt's, for the same reasons: a question
        with a deadline is worth waking a phone for and is worthless once the
        deadline has passed.
        """
        minutes = int(subentry.data.get(CONF_ANSWER_TIMEOUT, DEFAULT_ANSWER_TIMEOUT))
        yes, no = async_reminder_answer_titles(self.hass)
        return {
            "title": async_reminder_title(self.hass, subentry.title),
            "message": async_reminder_message(
                self.hass,
                subentry.title,
                self._manager.home_hours(subentry_id),
                minutes,
            ),
            "data": {
                "tag": f"{NOTIFICATION_REMINDER_TAG_PREFIX}{reminder_id}",
                "actions": [
                    {
                        "action": f"{ACTION_REMIND_YES_PREFIX}{reminder_id}",
                        "title": yes,
                    },
                    {"action": f"{ACTION_REMIND_NO_PREFIX}{reminder_id}", "title": no},
                ],
                "ttl": 0,
                "priority": "high",
                "timeout": minutes * 60,
                "push": {"interruption-level": "time-sensitive"},
                "icon_url": NOTIFICATION_ICON,
            },
        }

    @callback
    def _async_expired_payload(
        self, subentry: ConfigSubentry, prompt_id: str
    ) -> dict[str, Any]:
        """Return the notice that nobody answered."""
        return {
            "title": async_expired_title(self.hass),
            "message": async_expired_message(self.hass, subentry.title),
            "data": {
                "tag": f"{NOTIFICATION_INFO_TAG_PREFIX}{prompt_id}",
                "icon_url": NOTIFICATION_ICON,
            },
        }

    @callback
    def _async_reminder_expired_payload(
        self, subentry: ConfigSubentry, reminder_id: str
    ) -> dict[str, Any]:
        """Return the notice that nobody answered the reminder."""
        return {
            "title": async_expired_title(self.hass),
            "message": async_reminder_expired_message(self.hass, subentry.title),
            "data": {
                "tag": f"{NOTIFICATION_INFO_TAG_PREFIX}{reminder_id}",
                "icon_url": NOTIFICATION_ICON,
            },
        }

    @callback
    def _async_notification_action(self, event: Event[dict[str, Any]]) -> None:
        """Answer a question from a button somebody tapped on their phone.

        Only the action is taken from the event data, and only for a question
        that is open right now: whoever answers first ends it, and every later
        answer - a second phone, a stale message, a message of a tracker that
        is gone - finds nothing to answer.

        The reminder prefixes are tested first, but the order does not matter:
        none of the four is a prefix of another (see const.py), so an action
        can only ever be one of them.
        """
        action = event.data.get("action")
        if not isinstance(action, str):
            return
        if action.startswith(ACTION_REMIND_YES_PREFIX):
            self._async_answer_reminder(
                event, True, action.removeprefix(ACTION_REMIND_YES_PREFIX)
            )
        elif action.startswith(ACTION_REMIND_NO_PREFIX):
            self._async_answer_reminder(
                event, False, action.removeprefix(ACTION_REMIND_NO_PREFIX)
            )
        elif action.startswith(ACTION_YES_PREFIX):
            self._async_answer_prompt(
                event, True, action.removeprefix(ACTION_YES_PREFIX)
            )
        elif action.startswith(ACTION_NO_PREFIX):
            self._async_answer_prompt(
                event, False, action.removeprefix(ACTION_NO_PREFIX)
            )

    @callback
    def _async_answer_prompt(
        self, event: Event[dict[str, Any]], answer: bool, prompt_id: str
    ) -> None:
        """Answer the prompt a tapped button names, if it is still open."""
        subentry_id = self._manager.tracker_of_prompt(prompt_id)
        if subentry_id is None:
            _LOGGER.debug("Ignoring a prompt answer: no prompt %s waits", prompt_id)
            return
        self._manager.async_answer_prompt(
            subentry_id, answer, self._async_person_of(event)
        )

    @callback
    def _async_answer_reminder(
        self, event: Event[dict[str, Any]], answer: bool, reminder_id: str
    ) -> None:
        """Answer the reminder a tapped button names, if it is still open."""
        subentry_id = self._manager.tracker_of_reminder(reminder_id)
        if subentry_id is None:
            _LOGGER.debug(
                "Ignoring a reminder answer: no reminder %s waits", reminder_id
            )
            return
        self._manager.async_answer_reminder(
            subentry_id, answer, self._async_person_of(event)
        )

    @callback
    def _async_person_of(self, event: Event[dict[str, Any]]) -> str | None:
        """Return the person whose phone sent an action, if it can be told.

        The context of the event carries the user of the `mobile_app`
        registration - Home Assistant puts it there, the app cannot - and a
        person entity carries the same user.
        """
        if (user_id := event.context.user_id) is None:
            return None
        for state in self.hass.states.async_all(PERSON_DOMAIN):
            if state.attributes.get(ATTR_USER_ID) == user_id:
                return state.entity_id
        return None


def _clear_payload(tag_prefix: str, question_id: str) -> dict[str, Any]:
    """Return the message that takes a question off the phones."""
    return {
        "message": CLEAR_NOTIFICATION,
        "data": {"tag": f"{tag_prefix}{question_id}"},
    }
