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

# Per-tracker prompt options. Off by default: a tracker that is not configured
# for it behaves exactly as it did before the prompt existed.
CONF_ASK_ON_DEPARTURE: Final = "ask_on_departure"
DEFAULT_ASK_ON_DEPARTURE: Final = False
CONF_ANSWER_TIMEOUT: Final = "answer_timeout"
DEFAULT_ANSWER_TIMEOUT: Final = 10
MIN_ANSWER_TIMEOUT: Final = 1
MAX_ANSWER_TIMEOUT: Final = 120
CONF_PROMPT_DELAY: Final = "prompt_delay"
DEFAULT_PROMPT_DELAY: Final = 0
MIN_PROMPT_DELAY: Final = 0
MAX_PROMPT_DELAY: Final = 600

# Per-tracker delivery options. Without a recipient the integration sends
# nothing at all and the prompt stays what it was before: events and an action.
CONF_NOTIFY_PERSONS: Final = "notify_persons"
CONF_NOTIFY_ON_EXPIRY: Final = "notify_on_expiry"
DEFAULT_NOTIFY_ON_EXPIRY: Final = False

# State attributes of the integration's own entities.
ATTR_SINCE: Final = "since"
ATTR_REAL_PERSONS_HOME: Final = "real_persons_home"
ATTR_VIRTUAL_TRACKERS_HOME: Final = "virtual_trackers_home"
ATTR_PROMPT_OPEN: Final = "prompt_open"
ATTR_PROMPT_EXPIRES_AT: Final = "prompt_expires_at"

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

ATTR_PROMPT_ID: Final = "prompt_id"
ATTR_TRACKER: Final = "tracker"
ATTR_EXPIRES_AT: Final = "expires_at"
ATTR_ANSWERED_BY: Final = "answered_by"
ATTR_REASON: Final = "reason"

REASON_PERSON_HOME: Final = "person_home"
REASON_SWITCHED_ON: Final = "switched_on"
REASON_OPTION_DISABLED: Final = "option_disabled"

# Built-in delivery through the Companion App (see docs/DESIGN.md). The action
# IDs and the tags are internal, but they have to stay stable: an answer or a
# clearing may name a prompt that a previous Home Assistant run started.
EVENT_NOTIFICATION_ACTION: Final = "mobile_app_notification_action"
NOTIFICATION_TAG_PREFIX: Final = "vpt_"
NOTIFICATION_INFO_TAG_PREFIX: Final = "vpt_info_"
ACTION_YES_PREFIX: Final = "VPT_YES_"
ACTION_NO_PREFIX: Final = "VPT_NO_"
CLEAR_NOTIFICATION: Final = "clear_notification"

# The picture of the prompt message: the integration's own icon, out of the
# `brand` folder next to this file. The `brands` component serves that folder
# and wants an authenticated request; both Companion Apps send the user's token
# with an image URL that starts with a slash (see docs/DESIGN.md).
NOTIFICATION_IMAGE_FILE: Final = "icon@2x.png"
NOTIFICATION_IMAGE: Final = (
    f"/api/brands/integration/{DOMAIN}/{NOTIFICATION_IMAGE_FILE}"
)

# Entity services on the switches of this integration.
SERVICE_ANSWER_PROMPT: Final = "answer_prompt"
SERVICE_OPEN_PROMPT: Final = "open_prompt"
ATTR_ANSWER: Final = "answer"
ANSWER_YES: Final = "yes"
ANSWER_NO: Final = "no"

# Tracker states are persisted per config entry in
# .storage/<STORAGE_KEY_PREFIX>.<entry_id>.
STORAGE_KEY_PREFIX: Final = DOMAIN
STORAGE_VERSION: Final = 1
STORAGE_SAVE_DELAY: Final = 5
