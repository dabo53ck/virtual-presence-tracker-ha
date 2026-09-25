"""Texts of the built-in notifications: the prompt and the reminder.

The notifications are sent by the integration itself, so their texts cannot
come from `strings.json` - that file only translates what the frontend renders.
They live here instead, in English and German, and the language of the Home
Assistant instance picks one.
"""

from __future__ import annotations

from typing import Final

from homeassistant.core import HomeAssistant, callback

DEFAULT_LANGUAGE: Final = "en"

_TEXTS: Final[dict[str, dict[str, str]]] = {
    "en": {
        "title": "Is {tracker} home alone?",
        "message": "Nobody else is home. Answer within {minutes} minutes.",
        "message_one_minute": "Nobody else is home. Answer within one minute.",
        "yes": "Yes, home alone",
        "no": "No",
        "expired_title": "No answer",
        "expired_message": "No answer: {tracker} counts as not at home.",
        "reminder_title": "Is {tracker} still home?",
        "reminder_message": "{tracker} has been marked as home for {hours}. "
        "Answer within {minutes}.",
        "reminder_yes": "Yes, still home",
        "reminder_no": "No, switch off",
        "reminder_expired_message": "No answer: {tracker} stays marked as home.",
        "hours": "{hours} hours",
        "hours_one": "1 hour",
        "minutes": "{minutes} minutes",
        "minutes_one": "1 minute",
        "group": "Virtual presence: {tracker}",
    },
    "de": {
        "title": "Ist {tracker} alleine zu Hause?",
        "message": "Es ist niemand sonst zu Hause. Antworte innerhalb von "
        "{minutes} Minuten.",
        "message_one_minute": "Es ist niemand sonst zu Hause. Antworte innerhalb "
        "von einer Minute.",
        "yes": "Ja, alleine zu Hause",
        "no": "Nein",
        "expired_title": "Keine Antwort",
        "expired_message": "Keine Antwort: {tracker} gilt als nicht zu Hause.",
        "reminder_title": "Ist {tracker} noch zu Hause?",
        "reminder_message": "{tracker} ist seit {hours} als zu Hause markiert. "
        "Antworte innerhalb von {minutes}.",
        "reminder_yes": "Ja, noch da",
        "reminder_no": "Nein, ausschalten",
        "reminder_expired_message": "Keine Antwort: {tracker} bleibt als zu Hause "
        "markiert.",
        "hours": "{hours} Stunden",
        "hours_one": "1 Stunde",
        "minutes": "{minutes} Minuten",
        "minutes_one": "1 Minute",
        "group": "Virtuelle Anwesenheit: {tracker}",
    },
}


@callback
def async_texts(hass: HomeAssistant) -> dict[str, str]:
    """Return the notification texts for the language of this instance.

    The language can carry a region (``de-CH``); the part in front of the dash
    is what selects the texts, and anything that is not translated here falls
    back to English.
    """
    language = (hass.config.language or DEFAULT_LANGUAGE).split("-")[0].lower()
    return _TEXTS.get(language, _TEXTS[DEFAULT_LANGUAGE])


@callback
def async_prompt_title(hass: HomeAssistant, tracker: str) -> str:
    """Return the title of the prompt notification."""
    return async_texts(hass)["title"].format(tracker=tracker)


@callback
def async_prompt_message(hass: HomeAssistant, minutes: int) -> str:
    """Return the message of the prompt notification."""
    texts = async_texts(hass)
    if minutes == 1:
        return texts["message_one_minute"]
    return texts["message"].format(minutes=minutes)


@callback
def async_answer_titles(hass: HomeAssistant) -> tuple[str, str]:
    """Return the titles of the yes and the no button."""
    texts = async_texts(hass)
    return texts["yes"], texts["no"]


@callback
def async_expired_title(hass: HomeAssistant) -> str:
    """Return the title of the notice about an unanswered prompt."""
    return async_texts(hass)["expired_title"]


@callback
def async_expired_message(hass: HomeAssistant, tracker: str) -> str:
    """Return the message of the notice about an unanswered prompt."""
    return async_texts(hass)["expired_message"].format(tracker=tracker)


@callback
def async_reminder_title(hass: HomeAssistant, tracker: str) -> str:
    """Return the title of the reminder notification."""
    return async_texts(hass)["reminder_title"].format(tracker=tracker)


@callback
def async_reminder_message(
    hass: HomeAssistant, tracker: str, hours: int, minutes: int
) -> str:
    """Return the message of the reminder notification.

    The two durations are built first, so that a single hour and a single
    minute read as one - "1 hour", "1 Stunde" - instead of as "1 hours".
    """
    texts = async_texts(hass)
    return texts["reminder_message"].format(
        tracker=tracker,
        hours=(
            texts["hours_one"] if hours == 1 else texts["hours"].format(hours=hours)
        ),
        minutes=(
            texts["minutes_one"]
            if minutes == 1
            else texts["minutes"].format(minutes=minutes)
        ),
    )


@callback
def async_reminder_expired_message(hass: HomeAssistant, tracker: str) -> str:
    """Return the message of the notice about an unanswered reminder.

    The title is the prompt's (`async_expired_title`): both notices say that
    nobody answered, and only the consequence differs - an unanswered prompt
    leaves the tracker away, an unanswered reminder leaves it at home.
    """
    return async_texts(hass)["reminder_expired_message"].format(tracker=tracker)


@callback
def async_reminder_answer_titles(hass: HomeAssistant) -> tuple[str, str]:
    """Return the titles of the yes and the no button of the reminder."""
    texts = async_texts(hass)
    return texts["reminder_yes"], texts["reminder_no"]


@callback
def async_group(hass: HomeAssistant, tracker: str) -> str:
    """Return the group every message about one tracker is sent in.

    Both Companion Apps stack the messages of one group together: iOS as a
    thread, Android as a bundle. One group per tracker keeps a tracker's
    questions and notices apart from those of the other trackers and from the
    rest of Home Assistant's messages. Android shows the group's name as the
    summary of the bundle, which is why it is a readable text and not an ID.
    """
    return async_texts(hass)["group"].format(tracker=tracker)
