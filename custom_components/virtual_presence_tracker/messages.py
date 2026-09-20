"""Texts of the built-in prompt notification.

The notification is sent by the integration itself, so its texts cannot come
from `strings.json` - that file only translates what the frontend renders. They
live here instead, in English and German, and the language of the Home
Assistant instance picks one (see docs/DESIGN.md).
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
        "yes": "Yes, home",
        "no": "No",
        "expired_title": "No answer",
        "expired_message": "No answer: {tracker} counts as not at home.",
    },
    "de": {
        "title": "Ist {tracker} alleine zu Hause?",
        "message": "Es ist niemand sonst zu Hause. Antworte innerhalb von "
        "{minutes} Minuten.",
        "message_one_minute": "Es ist niemand sonst zu Hause. Antworte innerhalb "
        "von einer Minute.",
        "yes": "Ja, ist da",
        "no": "Nein",
        "expired_title": "Keine Antwort",
        "expired_message": "Keine Antwort: {tracker} gilt als nicht zu Hause.",
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
