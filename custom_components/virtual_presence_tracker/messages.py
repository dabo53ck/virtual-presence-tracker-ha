"""Texts of the built-in notifications: the prompt, the reminder and the
question about a device left behind.

The notifications are sent by the integration itself, so their texts cannot
come from `strings.json` - that file only translates what the frontend renders.
They live here instead, in English, German, French and Spanish, and the
language of the Home Assistant instance picks one.
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
        "left_behind_title": "Device left behind?",
        "left_behind_message": "Nobody else is home, but {devices} is. Is "
        "{tracker} home? If you answer No, or nobody answers within {minutes}, "
        "{tracker} is switched off and the device is ignored until it has been "
        "away for {away_after}.",
        "left_behind_message_many": "Nobody else is home, but {devices} are. Is "
        "{tracker} home? If you answer No, or nobody answers within {minutes}, "
        "{tracker} is switched off and the devices are ignored until they have "
        "been away for {away_after}.",
        "left_behind_message_generic": "Nobody else is home, but a device of "
        "{tracker} is. Is {tracker} home? If you answer No, or nobody answers "
        "within {minutes}, {tracker} is switched off and the device is ignored "
        "until it has been away for {away_after}.",
        "left_behind_and": " and ",
        "left_behind_yes": "Yes, home",
        "left_behind_no": "No, switch off",
        "left_behind_expired_message": "No answer: {tracker} has been switched "
        "off. {devices} is ignored until it has been away for {away_after}.",
        "left_behind_expired_message_many": "No answer: {tracker} has been "
        "switched off. {devices} are ignored until they have been away for "
        "{away_after}.",
        "left_behind_expired_message_generic": "No answer: {tracker} has been "
        "switched off. A device of {tracker} is ignored until it has been away "
        "for {away_after}.",
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
        "left_behind_title": "Gerät zurückgelassen?",
        "left_behind_message": "Es ist niemand sonst zu Hause, aber {devices} "
        "ist noch da. Ist {tracker} zu Hause? Bei Nein oder ohne Antwort "
        "innerhalb von {minutes} wird {tracker} ausgeschaltet und das Gerät "
        "ignoriert, bis es {away_after} lang weg war.",
        "left_behind_message_many": "Es ist niemand sonst zu Hause, aber "
        "{devices} sind noch da. Ist {tracker} zu Hause? Bei Nein oder ohne "
        "Antwort innerhalb von {minutes} wird {tracker} ausgeschaltet, und die "
        "Geräte werden ignoriert, bis sie {away_after} lang weg waren.",
        "left_behind_message_generic": "Es ist niemand sonst zu Hause, aber ein "
        "Gerät von {tracker} ist noch da. Ist {tracker} zu Hause? Bei Nein oder "
        "ohne Antwort innerhalb von {minutes} wird {tracker} ausgeschaltet und "
        "das Gerät ignoriert, bis es {away_after} lang weg war.",
        "left_behind_and": " und ",
        "left_behind_yes": "Ja, zu Hause",
        "left_behind_no": "Nein, ausschalten",
        "left_behind_expired_message": "Keine Antwort: {tracker} wurde "
        "ausgeschaltet. {devices} wird ignoriert, bis das Gerät {away_after} lang "
        "weg war.",
        "left_behind_expired_message_many": "Keine Antwort: {tracker} wurde "
        "ausgeschaltet. {devices} werden ignoriert, bis sie {away_after} lang "
        "weg waren.",
        "left_behind_expired_message_generic": "Keine Antwort: {tracker} wurde "
        "ausgeschaltet. Ein Gerät von {tracker} wird ignoriert, bis es "
        "{away_after} lang weg war.",
    },
    "fr": {
        "title": "Il n'y a que {tracker} à la maison ?",
        "message": "Personne d'autre n'est à la maison. Répondez sous "
        "{minutes} minutes.",
        "message_one_minute": "Personne d'autre n'est à la maison. Répondez sous "
        "une minute.",
        "yes": "Oui, à la maison",
        "no": "Non",
        "expired_title": "Pas de réponse",
        "expired_message": "Pas de réponse : pour Home Assistant, {tracker} "
        "n'est pas à la maison.",
        "reminder_title": "{tracker} est toujours à la maison ?",
        "reminder_message": "Pour Home Assistant, {tracker} est à la maison "
        "depuis {hours}. Répondez sous {minutes}.",
        "reminder_yes": "Oui, toujours là",
        "reminder_no": "Non, désactiver",
        "reminder_expired_message": "Pas de réponse : pour Home Assistant, "
        "{tracker} reste à la maison.",
        "hours": "{hours} heures",
        "hours_one": "1 heure",
        "minutes": "{minutes} minutes",
        "minutes_one": "1 minute",
        "group": "Présence virtuelle : {tracker}",
        "left_behind_title": "Appareil oublié ?",
        "left_behind_message": "Personne d'autre n'est à la maison, mais "
        "{devices} y est encore. {tracker} est à la maison ? En cas de Non ou "
        "sans réponse sous {minutes}, Home Assistant désactive {tracker} et "
        "ignore l'appareil jusqu'à ce qu'il soit absent depuis {away_after}.",
        "left_behind_message_many": "Personne d'autre n'est à la maison, mais "
        "{devices} y sont encore. {tracker} est à la maison ? En cas de Non ou "
        "sans réponse sous {minutes}, Home Assistant désactive {tracker} et "
        "ignore les appareils jusqu'à ce qu'ils soient absents depuis "
        "{away_after}.",
        "left_behind_message_generic": "Personne d'autre n'est à la maison, mais "
        "un appareil de {tracker} y est encore. {tracker} est à la maison ? En "
        "cas de Non ou sans réponse sous {minutes}, Home Assistant désactive "
        "{tracker} et ignore l'appareil jusqu'à ce qu'il soit absent depuis "
        "{away_after}.",
        "left_behind_and": " et ",
        "left_behind_yes": "Oui, à la maison",
        "left_behind_no": "Non, désactiver",
        "left_behind_expired_message": "Pas de réponse : Home Assistant a "
        "désactivé {tracker}. L'appareil {devices} est ignoré jusqu'à ce qu'il "
        "soit absent depuis {away_after}.",
        "left_behind_expired_message_many": "Pas de réponse : Home Assistant a "
        "désactivé {tracker}. Les appareils {devices} sont ignorés jusqu'à ce "
        "qu'ils soient absents depuis {away_after}.",
        "left_behind_expired_message_generic": "Pas de réponse : Home Assistant "
        "a désactivé {tracker}. Un appareil de {tracker} est ignoré jusqu'à ce "
        "qu'il soit absent depuis {away_after}.",
    },
    "es": {
        "title": "¿Solo está {tracker} en casa?",
        "message": "No hay nadie más en casa. Responde en {minutes} minutos.",
        "message_one_minute": "No hay nadie más en casa. Responde en un minuto.",
        "yes": "Sí, está en casa",
        "no": "No",
        "expired_title": "Sin respuesta",
        "expired_message": "Sin respuesta: {tracker} cuenta como fuera de casa.",
        "reminder_title": "¿Sigue {tracker} en casa?",
        "reminder_message": "{tracker} figura en casa desde hace {hours}. "
        "Responde en {minutes}.",
        "reminder_yes": "Sí, sigue en casa",
        "reminder_no": "No, apagar",
        "reminder_expired_message": "Sin respuesta: {tracker} sigue figurando en casa.",
        "hours": "{hours} horas",
        "hours_one": "1 hora",
        "minutes": "{minutes} minutos",
        "minutes_one": "1 minuto",
        "group": "Presencia virtual: {tracker}",
        "left_behind_title": "¿Dispositivo olvidado?",
        "left_behind_message": "No hay nadie más en casa, pero {devices} sigue "
        "allí. ¿Está {tracker} en casa? Si respondes No o nadie responde en "
        "{minutes}, {tracker} se apagará y el dispositivo se ignorará hasta que "
        "lleve {away_after} fuera.",
        "left_behind_message_many": "No hay nadie más en casa, pero {devices} "
        "siguen allí. ¿Está {tracker} en casa? Si respondes No o nadie responde "
        "en {minutes}, {tracker} se apagará y los dispositivos se ignorarán "
        "hasta que lleven {away_after} fuera.",
        "left_behind_message_generic": "No hay nadie más en casa, pero un "
        "dispositivo de {tracker} sigue allí. ¿Está {tracker} en casa? Si "
        "respondes No o nadie responde en {minutes}, {tracker} se apagará y el "
        "dispositivo se ignorará hasta que lleve {away_after} fuera.",
        "left_behind_and": " y ",
        "left_behind_yes": "Sí, está en casa",
        "left_behind_no": "No, apagar",
        "left_behind_expired_message": "Sin respuesta: {tracker} se ha apagado. "
        "El dispositivo {devices} se ignorará hasta que lleve {away_after} "
        "fuera.",
        "left_behind_expired_message_many": "Sin respuesta: {tracker} se ha "
        "apagado. Los dispositivos {devices} se ignorarán hasta que lleven "
        "{away_after} fuera.",
        "left_behind_expired_message_generic": "Sin respuesta: {tracker} se ha "
        "apagado. Un dispositivo de {tracker} se ignorará hasta que lleve "
        "{away_after} fuera.",
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


def _minutes(texts: dict[str, str], minutes: int) -> str:
    """Return a number of minutes, with one minute reading as one."""
    if minutes == 1:
        return texts["minutes_one"]
    return texts["minutes"].format(minutes=minutes)


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


@callback
def async_left_behind_title(hass: HomeAssistant) -> str:
    """Return the title of the question about a device left behind."""
    return async_texts(hass)["left_behind_title"]


def _left_behind_text(
    texts: dict[str, str], key: str, devices: list[str], **values: str
) -> str:
    """Return one text about the devices left behind, in the right number.

    The devices are named - "Xiaomi Tablet", "Tablet and Tag", "A, B and C" -
    and the text follows their number: ``key`` for one, ``key_many`` for
    several and ``key_generic``, which names none, without any.
    """
    if not devices:
        return texts[f"{key}_generic"].format(**values)
    if len(devices) == 1:
        return texts[key].format(devices=devices[0], **values)
    named = ", ".join(devices[:-1]) + texts["left_behind_and"] + devices[-1]
    return texts[f"{key}_many"].format(devices=named, **values)


@callback
def async_left_behind_message(
    hass: HomeAssistant,
    tracker: str,
    devices: list[str],
    minutes: int,
    away_after: int,
) -> str:
    """Return the message of the question about a device left behind (M3f).

    The devices are named so that whoever answers knows what is still at
    home; without a single name the message speaks of "a device of
    <tracker>". It says what "no" and no answer do - here both switch the
    tracker off - and that the device is ignored afterwards until it has been
    away for `away_after`: the lock, in the user's words.
    """
    texts = async_texts(hass)
    return _left_behind_text(
        texts,
        "left_behind_message",
        devices,
        tracker=tracker,
        minutes=_minutes(texts, minutes),
        away_after=_minutes(texts, away_after),
    )


@callback
def async_left_behind_answer_titles(hass: HomeAssistant) -> tuple[str, str]:
    """Return the titles of the yes and the no button of that question."""
    texts = async_texts(hass)
    return texts["left_behind_yes"], texts["left_behind_no"]


@callback
def async_left_behind_expired_message(
    hass: HomeAssistant, tracker: str, devices: list[str], away_after: int
) -> str:
    """Return the notice that nobody answered and the tracker was switched off.

    It names the devices the question named and, like the question, says that
    they are ignored until they have been away for `away_after`.
    """
    texts = async_texts(hass)
    return _left_behind_text(
        texts,
        "left_behind_expired_message",
        devices,
        tracker=tracker,
        away_after=_minutes(texts, away_after),
    )
