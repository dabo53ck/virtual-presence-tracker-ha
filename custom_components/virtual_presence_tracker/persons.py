"""Create the person of a new virtual tracker (M2g).

A virtual tracker does nothing until its `device_tracker` is part of a
`person`: that is the step people forget, and the repair issue
`tracker_not_assigned` exists for exactly that. A new tracker can therefore ask
for its person to be created, and this module is where that happens - not in
the config flow, because the tracker's entity does not exist while the form is
open. The flow only leaves a marker in the subentry data; the work is done once
Home Assistant has started, and the marker is taken off afterwards whatever the
outcome, so a person the user deletes later is never created again.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.person import async_create_person, persons_with_entity
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.start import async_at_started

from .const import CONF_CREATE_PERSON, PERSON_DOMAIN, SUBENTRY_TYPE_TRACKER
from .issues import HouseholdIssues, async_tracker_entities

if TYPE_CHECKING:
    from . import VirtualPresenceTrackerConfigEntry

_LOGGER = logging.getLogger(__name__)


class TrackerPersons:
    """Create the person the trackers of a config entry asked for."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: VirtualPresenceTrackerConfigEntry,
        issues: HouseholdIssues,
    ) -> None:
        """Initialise the pending work of an entry. Call async_start()."""
        self.hass = hass
        self.entry = entry
        self._issues = issues
        self._unsub: CALLBACK_TYPE | None = None

    @callback
    def async_start(self) -> None:
        """Do the pending work once Home Assistant has started.

        The same timing as the repair issues, for the same reason: the person
        states and the storage collection behind them only exist once every
        component is set up. The tracker entities are there by now either way -
        the platforms of this entry are forwarded before this is called.
        """
        self._unsub = async_at_started(self.hass, self._async_started)

    @callback
    def async_stop(self) -> None:
        """Stop waiting for the start."""
        if self._unsub is not None:
            self._unsub()
            self._unsub = None

    async def _async_started(self, hass: HomeAssistant) -> None:
        """Work through the trackers that asked for a person."""
        pending = [
            subentry
            for subentry in self.entry.get_subentries_of_type(SUBENTRY_TYPE_TRACKER)
            if subentry.data.get(CONF_CREATE_PERSON)
        ]
        if not pending:
            return
        for subentry in pending:
            await self._async_create_person(subentry)
            self._async_clear_marker(subentry)
        # `tracker_not_assigned` is held back while a marker is pending, so the
        # issues have to look again now - whether a person was created, whether
        # one was there already or whether the attempt failed.
        self._issues.async_recheck()

    async def _async_create_person(self, subentry: ConfigSubentry) -> None:
        """Create the person of one tracker, unless there is a reason not to."""
        name = subentry.title
        entity_id = async_tracker_entities(self.hass, self.entry).get(
            subentry.subentry_id
        )
        if entity_id is None:
            _LOGGER.warning(
                "No person was created for the virtual tracker %s: it has no"
                " device tracker entity",
                name,
            )
            return
        if PERSON_DOMAIN not in self.hass.config.components:
            _LOGGER.warning(
                "No person was created for the virtual tracker %s: the person"
                " integration is not set up",
                name,
            )
            return
        if persons_with_entity(self.hass, entity_id):
            # Somebody follows this tracker already - the user was quicker, or
            # the marker outlived a restart that the person survived too.
            _LOGGER.debug(
                "%s is already part of a person, nothing to create", entity_id
            )
            return
        if (existing := self._async_person_named(name)) is not None:
            # A person of that name is almost certainly the one the tracker
            # stands for, but adopting somebody else's person is not ours to
            # decide: a second person of the same name would be worse, and
            # `tracker_not_assigned` names the two clicks it takes.
            _LOGGER.warning(
                "No person was created for the virtual tracker %s: %s already"
                " goes by that name. Assign %s to it under Settings > People",
                name,
                existing,
                entity_id,
            )
            return
        try:
            await async_create_person(self.hass, name, device_trackers=[entity_id])
        except Exception:
            _LOGGER.warning(
                "Could not create a person for the virtual tracker %s. Add one"
                " under Settings > People and assign %s to it",
                name,
                entity_id,
                exc_info=True,
            )
        else:
            _LOGGER.info("Created a person for the virtual tracker %s", name)

    @callback
    def _async_person_named(self, name: str) -> str | None:
        """Return the person that already goes by this name, if there is one."""
        wanted = name.casefold()
        return next(
            (
                state.entity_id
                for state in self.hass.states.async_all(PERSON_DOMAIN)
                if state.name.casefold() == wanted
            ),
            None,
        )

    @callback
    def _async_clear_marker(self, subentry: ConfigSubentry) -> None:
        """Take the marker off a tracker, so the work never runs twice.

        The write must not reload the config entry, which is what the reload
        fingerprint leaves this key out for (see __init__.py).
        """
        if self.entry.subentries.get(subentry.subentry_id) is not subentry:
            # The tracker was removed while the person was being created.
            return
        self.hass.config_entries.async_update_subentry(
            self.entry,
            subentry,
            data={
                key: value
                for key, value in subentry.data.items()
                if key != CONF_CREATE_PERSON
            },
        )
