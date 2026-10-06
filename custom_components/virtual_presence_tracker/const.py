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

# How long the presence sources of a tracker (M3e) have to be absent before the
# tracker is switched off, in minutes - the guard against a missed Bluetooth
# advertisement or a Wi-Fi drop flipping the house to "empty". For a Bluetooth
# source it is also the window an advertisement counts in. A tracker without
# the key uses the default, like every other missing option.
CONF_AWAY_AFTER: Final = "away_after"
DEFAULT_AWAY_AFTER: Final = 10
MIN_AWAY_AFTER: Final = 1
MAX_AWAY_AFTER: Final = 120

# The question about a device left behind (M3f): a tracker that a presence
# source keeps on while the house is empty is asked about once, `away_after`
# after the last real person left - and switched off when nobody answers. Off
# by default, for a new tracker and for one without the key. It has a Do Not
# Disturb override of its own, separate from the prompt's: a loud prompt and a
# quiet question about a device, or the other way round, are both reasonable.
# Its answer time is the prompt's `answer_timeout`, its waiting time is
# `away_after`.
CONF_ASK_LEFT_BEHIND: Final = "ask_left_behind"
DEFAULT_ASK_LEFT_BEHIND: Final = False
CONF_LEFT_BEHIND_OVERRIDE_DND: Final = "left_behind_override_dnd"
DEFAULT_LEFT_BEHIND_OVERRIDE_DND: Final = False

# The options a tracker carries an entity for (M2f, grown in M3a), with the
# value that applies while the key is missing. They are the only keys of a
# subentry that
# may change without reloading the config entry: a reload would take the
# trackers and their persons away for a moment, which is not something a
# switch is allowed to do.
OPTION_DEFAULTS: Final[dict[str, bool | int]] = {
    CONF_ASK_ON_DEPARTURE: DEFAULT_ASK_ON_DEPARTURE,
    CONF_RESET_ON_RETURN: DEFAULT_RESET_ON_RETURN,
    CONF_NOTIFY_ON_EXPIRY: DEFAULT_NOTIFY_ON_EXPIRY,
    CONF_ANSWER_TIMEOUT: DEFAULT_ANSWER_TIMEOUT,
    CONF_PROMPT_DELAY: DEFAULT_PROMPT_DELAY,
    CONF_REMIND_AFTER: DEFAULT_REMIND_AFTER,
    CONF_REMINDER_TIMEOUT: DEFAULT_REMINDER_TIMEOUT,
    CONF_OVERRIDE_DND: DEFAULT_OVERRIDE_DND,
    CONF_AWAY_AFTER: DEFAULT_AWAY_AFTER,
    CONF_ASK_LEFT_BEHIND: DEFAULT_ASK_LEFT_BEHIND,
    CONF_LEFT_BEHIND_OVERRIDE_DND: DEFAULT_LEFT_BEHIND_OVERRIDE_DND,
}
LIVE_OPTION_KEYS: Final = frozenset(OPTION_DEFAULTS)

# The person a new tracker asks for (M2g). This is a marker in the subentry
# data, not an option: the form writes it, the integration acts on it once
# Home Assistant has started and takes it off again, and it has no entity. A
# tracker from before M2g simply does not carry it, and neither does one whose
# person has been created - which is what makes the work happen exactly once.
CONF_CREATE_PERSON: Final = "create_person"
DEFAULT_CREATE_PERSON: Final = True

# Button sources (M3d): `event` entities of any integration whose events switch
# a tracker - a set of event types that means "home" (on) and a set that means
# "away" (off); every other type is left alone. All three keys are absent from
# a tracker without button sources, which is what every tracker from before
# M3d looks like, and the form takes all three off again when the last source
# is removed. Nothing about them is vendor-specific.
CONF_BUTTON_SOURCES: Final = "button_sources"
CONF_BUTTON_HOME_TYPES: Final = "button_home_types"
CONF_BUTTON_AWAY_TYPES: Final = "button_away_types"
BUTTON_KEYS: Final = frozenset(
    {CONF_BUTTON_SOURCES, CONF_BUTTON_HOME_TYPES, CONF_BUTTON_AWAY_TYPES}
)
# What the form suggests for a source that offers them: a short press says
# "home", a long press says "away". Only suggested when "press" is offered.
SUGGESTED_BUTTON_HOME_TYPE: Final = "press"
SUGGESTED_BUTTON_AWAY_TYPE: Final = "long_press"
EVENT_DOMAIN: Final = "event"

# Presence sources (M3e): entities whose state says whether the person is at
# home - a `device_tracker` (present = `home`) or a `binary_sensor` (present =
# `on`) of any integration - and Bluetooth devices by address, heard through
# Home Assistant's own Bluetooth manager. A tracker counts as present while any
# of them is. Both keys are absent from a tracker without such sources, which
# is what every tracker from before M3e looks like, and the form takes a key
# off again when its last source is removed.
CONF_PRESENCE_SOURCES: Final = "presence_sources"
CONF_BLE_SOURCES: Final = "ble_sources"
PRESENCE_KEYS: Final = frozenset({CONF_PRESENCE_SOURCES, CONF_BLE_SOURCES})
DEVICE_TRACKER_DOMAIN: Final = "device_tracker"
BINARY_SENSOR_DOMAIN: Final = "binary_sensor"
# Spelled out rather than imported: the integration has to load on an instance
# without Bluetooth, so only a configured Bluetooth source ever imports it.
BLUETOOTH_DOMAIN: Final = "bluetooth"
# How often the last advertisement of a Bluetooth source is looked at, in
# seconds. Home Assistant's own unavailable tracking runs every five minutes
# and waits up to fifteen, which is far coarser than `away_after`.
BLE_POLL_INTERVAL: Final = 30

# Every key of a subentry that may change while the config entry stays loaded:
# the options an entity writes, the marker above, the button sources and the
# presence sources, whose listeners the manager moves by itself. A reload
# would take the trackers and their persons to `unavailable` for a moment, and
# none of these is allowed to do that (see the reload fingerprint in
# __init__.py).
NO_RELOAD_KEYS: Final = (
    LIVE_OPTION_KEYS | {CONF_CREATE_PERSON} | BUTTON_KEYS | PRESENCE_KEYS
)

# State attributes of the integration's own entities.
ATTR_SINCE: Final = "since"
ATTR_REAL_PERSONS_HOME: Final = "real_persons_home"
ATTR_VIRTUAL_TRACKERS_HOME: Final = "virtual_trackers_home"
ATTR_PROMPT_OPEN: Final = "prompt_open"
ATTR_PROMPT_EXPIRES_AT: Final = "prompt_expires_at"
ATTR_REMINDER_OPEN: Final = "reminder_open"
ATTR_REMINDER_EXPIRES_AT: Final = "reminder_expires_at"
ATTR_LEFT_BEHIND_OPEN: Final = "left_behind_open"
ATTR_LEFT_BEHIND_EXPIRES_AT: Final = "left_behind_expires_at"

# Public contract of the prompt. The event types of the
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

# The question about a device left behind (M3f) follows the reminder's pattern:
# a stem and the same five endings, on the same event entity, named by an ID of
# its own (`left_behind_id`) and never by either of the other two.
EVENT_LEFT_BEHIND_STARTED: Final = "left_behind_started"
EVENT_LEFT_BEHIND_ANSWERED_YES: Final = "left_behind_answered_yes"
EVENT_LEFT_BEHIND_ANSWERED_NO: Final = "left_behind_answered_no"
EVENT_LEFT_BEHIND_EXPIRED: Final = "left_behind_expired"
EVENT_LEFT_BEHIND_CANCELLED: Final = "left_behind_cancelled"
LEFT_BEHIND_EVENT_TYPES: Final = [
    EVENT_LEFT_BEHIND_STARTED,
    EVENT_LEFT_BEHIND_ANSWERED_YES,
    EVENT_LEFT_BEHIND_ANSWERED_NO,
    EVENT_LEFT_BEHIND_EXPIRED,
    EVENT_LEFT_BEHIND_CANCELLED,
]

# Everything one tracker's event entity can publish.
TRACKER_EVENT_TYPES: Final = (
    PROMPT_EVENT_TYPES + REMINDER_EVENT_TYPES + LEFT_BEHIND_EVENT_TYPES
)

ATTR_PROMPT_ID: Final = "prompt_id"
ATTR_REMINDER_ID: Final = "reminder_id"
ATTR_LEFT_BEHIND_ID: Final = "left_behind_id"
# The presence sources that were still present when a question about a device
# left behind opened: entity IDs and Bluetooth addresses.
ATTR_SOURCES: Final = "sources"
ATTR_TRACKER: Final = "tracker"
ATTR_EXPIRES_AT: Final = "expires_at"
ATTR_ANSWERED_BY: Final = "answered_by"
ATTR_REASON: Final = "reason"

REASON_PERSON_HOME: Final = "person_home"
REASON_SWITCHED_ON: Final = "switched_on"
REASON_SWITCHED_OFF: Final = "switched_off"
REASON_OPTION_DISABLED: Final = "option_disabled"

# Built-in delivery through the Companion App. The action
# IDs and the tags are internal, but they have to stay stable: an answer or a
# clearing may name a prompt that a previous Home Assistant run started.
EVENT_NOTIFICATION_ACTION: Final = "mobile_app_notification_action"
NOTIFICATION_TAG_PREFIX: Final = "vpt_"
NOTIFICATION_REMINDER_TAG_PREFIX: Final = "vpt_reminder_"
NOTIFICATION_LEFT_BEHIND_TAG_PREFIX: Final = "vpt_left_behind_"
ACTION_YES_PREFIX: Final = "VPT_YES_"
ACTION_NO_PREFIX: Final = "VPT_NO_"
# The reminder buttons (M3a). Neither of these is a prefix of a prompt action
# and no prompt action is a prefix of one of these - `VPT_REMIND_YES_x` does
# not start with `VPT_YES_`, and `VPT_YES_x` does not start with
# `VPT_REMIND_YES_` - so the same startswith() test tells the four apart in
# either order. Whoever adds another prefix has to keep that true.
ACTION_REMIND_YES_PREFIX: Final = "VPT_REMIND_YES_"
ACTION_REMIND_NO_PREFIX: Final = "VPT_REMIND_NO_"
# The buttons of the question about a device left behind (M3f), under the same
# rule: none of the six prefixes starts with another one.
ACTION_LEFT_BEHIND_YES_PREFIX: Final = "VPT_LEFT_BEHIND_YES_"
ACTION_LEFT_BEHIND_NO_PREFIX: Final = "VPT_LEFT_BEHIND_NO_"
CLEAR_NOTIFICATION: Final = "clear_notification"

# The icon of the prompt message: the integration's own icon, out of the
# `brand` folder next to this file. It takes the place of the Companion App's
# own icon beside the message. The `brands` component serves that folder and
# wants an authenticated request; both Companion Apps send the user's token
# with an icon URL that starts with a slash.
NOTIFICATION_ICON_FILE: Final = "icon@2x.png"
NOTIFICATION_ICON: Final = f"/api/brands/integration/{DOMAIN}/{NOTIFICATION_ICON_FILE}"

# The Android notification channel that makes a message loud enough to get
# through Do Not Disturb (M3c): the Companion App tests for this exact name and
# gives such a notification `Notification.CATEGORY_ALARM` and the alarm audio
# stream, which is the exception Do Not Disturb keeps for alarms. The iOS half
# of the same option lives in `data.push`.
NOTIFICATION_ALARM_CHANNEL: Final = "alarm_stream"

# The iOS half of the same option: the name of the sound a critical alert
# plays. "default" is the system sound, and the name has to be sent - the push
# relay rejects a payload whose `aps.sound` dictionary has no non-empty `name`
# before it ever reaches the phone.
NOTIFICATION_CRITICAL_SOUND: Final = "default"

# Entity services on the switches of this integration.
SERVICE_ANSWER_PROMPT: Final = "answer_prompt"
SERVICE_OPEN_PROMPT: Final = "open_prompt"
SERVICE_ANSWER_REMINDER: Final = "answer_reminder"
SERVICE_OPEN_REMINDER: Final = "open_reminder"
SERVICE_ANSWER_LEFT_BEHIND: Final = "answer_left_behind"
SERVICE_OPEN_LEFT_BEHIND: Final = "open_left_behind"
ATTR_ANSWER: Final = "answer"
ANSWER_YES: Final = "yes"
ANSWER_NO: Final = "no"

# Tracker states are persisted per config entry in
# .storage/<STORAGE_KEY_PREFIX>.<entry_id>.
STORAGE_KEY_PREFIX: Final = DOMAIN
STORAGE_VERSION: Final = 1
STORAGE_SAVE_DELAY: Final = 5
