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

# Tracker states are persisted per config entry in
# .storage/<STORAGE_KEY_PREFIX>.<entry_id>.
STORAGE_KEY_PREFIX: Final = DOMAIN
STORAGE_VERSION: Final = 1
STORAGE_SAVE_DELAY: Final = 5
