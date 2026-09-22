"""Constants for the Virtual Presence Tracker integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "virtual_presence_tracker"

# Domains of the components the integration talks to. All of them are spelled
# out instead of imported: the integration works without any of them, and an
# import of homeassistant.components.<x> would make it a manifest dependency.
PERSON_DOMAIN: Final = "person"
NOTIFY_DOMAIN: Final = "notify"
MOBILE_APP_DOMAIN: Final = "mobile_app"

# State attributes of a person entity: the device trackers assigned to it and
# the Home Assistant user it belongs to, if any.
ATTR_DEVICE_TRACKERS: Final = "device_trackers"
ATTR_USER_ID: Final = "user_id"

# Keys of a mobile_app config entry: the user the phone is signed in with and
# the name the notify service of that phone is built from.
CONF_USER_ID: Final = "user_id"
CONF_DEVICE_NAME: Final = "device_name"

# Config entry data: the real persons whose presence decides whether somebody
# who is not a virtual tracker is at home.
CONF_PERSONS: Final = "persons"

# Config subentry: one per virtual tracker.
SUBENTRY_TYPE_TRACKER: Final = "tracker"
CONF_RESET_ON_RETURN: Final = "reset_on_return"
DEFAULT_RESET_ON_RETURN: Final = True

# Per-tracker prompt options. A tracker whose subentry does not carry the key
# does not ask: that is what every tracker from before the prompt existed looks
# like, and it must keep behaving as it did. A tracker added from M2f on stores
# the option explicitly and asks (NEW_TRACKER_ASK_ON_DEPARTURE).
CONF_ASK_ON_DEPARTURE: Final = "ask_on_departure"
DEFAULT_ASK_ON_DEPARTURE: Final = False
NEW_TRACKER_ASK_ON_DEPARTURE: Final = True
CONF_ANSWER_TIMEOUT: Final = "answer_timeout"
DEFAULT_ANSWER_TIMEOUT: Final = 10
MIN_ANSWER_TIMEOUT: Final = 1
MAX_ANSWER_TIMEOUT: Final = 120
CONF_PROMPT_DELAY: Final = "prompt_delay"
DEFAULT_PROMPT_DELAY: Final = 0
MIN_PROMPT_DELAY: Final = 0
MAX_PROMPT_DELAY: Final = 600

# The reminder of a tracker that has been on for too long (M3a), in hours; 0
# means "never remind". A tracker whose subentry does not carry the key stays
# silent, which is what every tracker from before the reminder looks like. The
# upper bound is a week, long enough for a guest tracker that is meant to stay
# on for the whole visit.
CONF_REMIND_AFTER: Final = "remind_after"
DEFAULT_REMIND_AFTER: Final = 0
MIN_REMIND_AFTER: Final = 0
MAX_REMIND_AFTER: Final = 168
NEW_TRACKER_REMIND_AFTER: Final = 24

# How long a reminder waits for its answer, in minutes. Its own option rather
# than the prompt's: a prompt is answered on the way out of the door and is
# worthless once the away routines have run, while a reminder is a question
# about a whole day that may well be answered an hour later. Hence a default
# of an hour and an upper bound of six, against the prompt's ten minutes and
# two hours. A tracker without the key uses the default, exactly like every
# other missing option.
CONF_REMINDER_TIMEOUT: Final = "reminder_timeout"
DEFAULT_REMINDER_TIMEOUT: Final = 60
MIN_REMINDER_TIMEOUT: Final = 1
MAX_REMINDER_TIMEOUT: Final = 360

# Per-tracker delivery options. Without a recipient the integration sends
# nothing at all and the prompt stays what it was before: events and an action.
CONF_NOTIFY_PERSONS: Final = "notify_persons"
CONF_NOTIFY_ON_EXPIRY: Final = "notify_on_expiry"
DEFAULT_NOTIFY_ON_EXPIRY: Final = False

# Whether the *prompt* is loud enough to get through a silenced phone (M3c).
# Off by default and deliberately opt-in: it bypasses Do Not Disturb and the
# mute switch, which is right for the one question that has a deadline nobody
# can repeat and wrong for everything else. It covers the prompt only - not
# the reminder, which asks about a whole day, and not the expiry notices,
# which are news rather than questions.
CONF_OVERRIDE_DND: Final = "override_dnd"
DEFAULT_OVERRIDE_DND: Final = False

# The options a tracker carries an entity for (M2f, grown in M3a), with the
# value that applies while the key is missing. They are the only keys of a
# subentry that
# may change without reloading the config entry: a reload would take the
# trackers and their persons away for a moment, which is not something a
# switch is allowed to do (see docs/DESIGN.md).
OPTION_DEFAULTS: Final[dict[str, bool | int]] = {
    CONF_ASK_ON_DEPARTURE: DEFAULT_ASK_ON_DEPARTURE,
    CONF_RESET_ON_RETURN: DEFAULT_RESET_ON_RETURN,
    CONF_NOTIFY_ON_EXPIRY: DEFAULT_NOTIFY_ON_EXPIRY,
    CONF_ANSWER_TIMEOUT: DEFAULT_ANSWER_TIMEOUT,
    CONF_PROMPT_DELAY: DEFAULT_PROMPT_DELAY,
    CONF_REMIND_AFTER: DEFAULT_REMIND_AFTER,
    CONF_REMINDER_TIMEOUT: DEFAULT_REMINDER_TIMEOUT,
    CONF_OVERRIDE_DND: DEFAULT_OVERRIDE_DND,
}
LIVE_OPTION_KEYS: Final = frozenset(OPTION_DEFAULTS)

# The person a new tracker asks for (M2g). This is a marker in the subentry
# data, not an option: the form writes it, the integration acts on it once
# Home Assistant has started and takes it off again, and it has no entity. A
# tracker from before M2g simply does not carry it, and neither does one whose
# person has been created - which is what makes the work happen exactly once.
CONF_CREATE_PERSON: Final = "create_person"
DEFAULT_CREATE_PERSON: Final = True

# Every key of a subentry that may change while the config entry stays loaded:
# the options an entity writes, plus the marker above. A reload would take the
# trackers and their persons to `unavailable` for a moment, and neither a
# switch nor a marker that has served its purpose is allowed to do that (see
# the reload fingerprint in __init__.py).
NO_RELOAD_KEYS: Final = LIVE_OPTION_KEYS | {CONF_CREATE_PERSON}

# State attributes of the integration's own entities.
ATTR_SINCE: Final = "since"
ATTR_REAL_PERSONS_HOME: Final = "real_persons_home"
ATTR_VIRTUAL_TRACKERS_HOME: Final = "virtual_trackers_home"
ATTR_PROMPT_OPEN: Final = "prompt_open"
ATTR_PROMPT_EXPIRES_AT: Final = "prompt_expires_at"
ATTR_REMINDER_OPEN: Final = "reminder_open"
ATTR_REMINDER_EXPIRES_AT: Final = "reminder_expires_at"

# Public contract of the prompt (see docs/DESIGN.md). The event types of the
# per-tracker event entity, the keys of their data and the reasons a prompt can
# be cancelled with are an API that automations are written against: they may
# grow, but they are never renamed.
EVENT_PROMPT_STARTED: Final = "prompt_started"
EVENT_ANSWERED_YES: Final = "answered_yes"
EVENT_ANSWERED_NO: Final = "answered_no"
EVENT_EXPIRED: Final = "expired"
EVENT_CANCELLED: Final = "cancelled"
PROMPT_EVENT_TYPES: Final = [
    EVENT_PROMPT_STARTED,
    EVENT_ANSWERED_YES,
    EVENT_ANSWERED_NO,
    EVENT_EXPIRED,
    EVENT_CANCELLED,
]

# The reminder (M3a) is announced by the very same event entity, with five
# event types of its own. The prompt keeps every one of its names: the contract
# grows, it never changes. A reminder is named by `reminder_id` and never by
# `prompt_id` - the two are different questions about the same tracker, and an
# automation must not be able to confuse them.
EVENT_REMINDER_STARTED: Final = "reminder_started"
EVENT_REMINDER_ANSWERED_YES: Final = "reminder_answered_yes"
EVENT_REMINDER_ANSWERED_NO: Final = "reminder_answered_no"
EVENT_REMINDER_EXPIRED: Final = "reminder_expired"
EVENT_REMINDER_CANCELLED: Final = "reminder_cancelled"
REMINDER_EVENT_TYPES: Final = [
    EVENT_REMINDER_STARTED,
    EVENT_REMINDER_ANSWERED_YES,
    EVENT_REMINDER_ANSWERED_NO,
    EVENT_REMINDER_EXPIRED,
    EVENT_REMINDER_CANCELLED,
]

# Everything one tracker's event entity can publish.
TRACKER_EVENT_TYPES: Final = PROMPT_EVENT_TYPES + REMINDER_EVENT_TYPES

ATTR_PROMPT_ID: Final = "prompt_id"
ATTR_REMINDER_ID: Final = "reminder_id"
ATTR_TRACKER: Final = "tracker"
ATTR_EXPIRES_AT: Final = "expires_at"
ATTR_ANSWERED_BY: Final = "answered_by"
ATTR_REASON: Final = "reason"

REASON_PERSON_HOME: Final = "person_home"
REASON_SWITCHED_ON: Final = "switched_on"
REASON_SWITCHED_OFF: Final = "switched_off"
REASON_OPTION_DISABLED: Final = "option_disabled"

# Built-in delivery through the Companion App (see docs/DESIGN.md). The action
# IDs and the tags are internal, but they have to stay stable: an answer or a
# clearing may name a prompt that a previous Home Assistant run started.
EVENT_NOTIFICATION_ACTION: Final = "mobile_app_notification_action"
NOTIFICATION_TAG_PREFIX: Final = "vpt_"
NOTIFICATION_INFO_TAG_PREFIX: Final = "vpt_info_"
NOTIFICATION_REMINDER_TAG_PREFIX: Final = "vpt_reminder_"
ACTION_YES_PREFIX: Final = "VPT_YES_"
ACTION_NO_PREFIX: Final = "VPT_NO_"
# The reminder buttons (M3a). Neither of these is a prefix of a prompt action
# and no prompt action is a prefix of one of these - `VPT_REMIND_YES_x` does
# not start with `VPT_YES_`, and `VPT_YES_x` does not start with
# `VPT_REMIND_YES_` - so the same startswith() test tells the four apart in
# either order. Whoever adds a sixth prefix has to keep that true.
ACTION_REMIND_YES_PREFIX: Final = "VPT_REMIND_YES_"
ACTION_REMIND_NO_PREFIX: Final = "VPT_REMIND_NO_"
CLEAR_NOTIFICATION: Final = "clear_notification"

# The icon of the prompt message: the integration's own icon, out of the
# `brand` folder next to this file. It takes the place of the Companion App's
# own icon beside the message. The `brands` component serves that folder and
# wants an authenticated request; both Companion Apps send the user's token
# with an icon URL that starts with a slash (see docs/DESIGN.md).
NOTIFICATION_ICON_FILE: Final = "icon@2x.png"
NOTIFICATION_ICON: Final = f"/api/brands/integration/{DOMAIN}/{NOTIFICATION_ICON_FILE}"

# The Android notification channel that makes a message loud enough to get
# through Do Not Disturb (M3c): the Companion App tests for this exact name and
# gives such a notification `Notification.CATEGORY_ALARM` and the alarm audio
# stream, which is the exception Do Not Disturb keeps for alarms. The iOS half
# of the same option lives in `data.push` (see docs/DESIGN.md).
NOTIFICATION_ALARM_CHANNEL: Final = "alarm_stream"

# Entity services on the switches of this integration.
SERVICE_ANSWER_PROMPT: Final = "answer_prompt"
SERVICE_OPEN_PROMPT: Final = "open_prompt"
SERVICE_ANSWER_REMINDER: Final = "answer_reminder"
SERVICE_OPEN_REMINDER: Final = "open_reminder"
ATTR_ANSWER: Final = "answer"
ANSWER_YES: Final = "yes"
ANSWER_NO: Final = "no"

# Tracker states are persisted per config entry in
# .storage/<STORAGE_KEY_PREFIX>.<entry_id>.
STORAGE_KEY_PREFIX: Final = DOMAIN
STORAGE_VERSION: Final = 1
STORAGE_SAVE_DELAY: Final = 5
