"""Constants for the Virtual Presence Tracker integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "virtual_presence_tracker"

# Domain of the entities the real persons are picked from. Spelled out instead
# of imported, so the integration does not depend on the person component.
PERSON_DOMAIN: Final = "person"

# State attribute of a person entity listing the device trackers assigned to it.
ATTR_DEVICE_TRACKERS: Final = "device_trackers"

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

# Entity service on the switches of this integration.
SERVICE_ANSWER_PROMPT: Final = "answer_prompt"
ATTR_ANSWER: Final = "answer"
ANSWER_YES: Final = "yes"
ANSWER_NO: Final = "no"

# Tracker states are persisted per config entry in
# .storage/<STORAGE_KEY_PREFIX>.<entry_id>.
STORAGE_KEY_PREFIX: Final = DOMAIN
STORAGE_VERSION: Final = 1
STORAGE_SAVE_DELAY: Final = 5
