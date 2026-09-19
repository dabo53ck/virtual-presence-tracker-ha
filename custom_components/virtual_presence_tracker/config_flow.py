"""Config flow for the Virtual Presence Tracker integration.

Placeholder: a single confirmation step that creates an empty entry. The real
flow (real persons to watch, notification defaults) and the subentry flow for
the individual virtual trackers replace it in the next M1 step.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN


class VirtualPresenceTrackerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Virtual Presence Tracker."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=vol.Schema({}))

        return self.async_create_entry(title="Virtual Presence Tracker", data={})
