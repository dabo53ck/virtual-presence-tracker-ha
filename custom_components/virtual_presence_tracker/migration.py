"""Registry clean-up for installs that predate a change of the entities.

Two clean-ups, both harmless on every setup and reload.

Up to and including M1f the "only virtual trackers home" sensor carried a
household device `(DOMAIN, entry_id)`. A config entry that has subentries and
owns a device outside of them makes the frontend show a "Devices that do not
belong to a sub-entry" section on the integration page, so the rule now is:
every device belongs to a tracker subentry, entry-level entities have none.

`async_remove_legacy_household_device` drops that leftover device on an
existing install. It can be deleted once no installation from before that
change is left.

Up to M3f every timing of a tracker and its expiry notice had an entity of its
own. Since M3g they are set in the tracker's form, and
`async_remove_moved_option_entities` drops their registry entries, which Home
Assistant would otherwise show as `unavailable` for good.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .const import DOMAIN, REMOVED_OPTION_ENTITIES, SUBENTRY_TYPE_TRACKER


@callback
def async_remove_legacy_household_device(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Remove the household device of this entry, keeping its entities.

    Only the device with the identifiers of the config entry itself is
    touched, never a tracker subentry device. Doing nothing when the device is
    already gone makes this safe on every setup and reload.
    """
    device_registry = dr.async_get(hass)
    device = device_registry.async_get_device_by_identifier(
        (DOMAIN, entry.entry_id), entry.entry_id
    )
    if device is None:
        return

    # Detach the entities first. Removing a device deletes every entity of the
    # device that belongs to the same config entry and subentry, which would
    # take the entity ID of the sensor with it - and with the entity ID its
    # history and every automation that names it.
    entity_registry = er.async_get(hass)
    entities = er.async_entries_for_device(
        entity_registry, device.id, include_disabled_entities=True
    )
    if any(entity.config_entry_id != entry.entry_id for entity in entities):
        # Something else owns an entity on this device. Leave both alone.
        return
    for entity in entities:
        entity_registry.async_update_entity(entity.entity_id, device_id=None)

    device_registry.async_remove_device(device.id)


@callback
def async_remove_moved_option_entities(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove the option entities that moved into the tracker's form (M3g).

    Looked up by their exact unique ID - `<subentry_id>_<option key>` on the
    platform of this integration - for every tracker of this entry, never by
    name. Nothing found means nothing to do, which is the case on every setup
    after the first one and on every install from M3g on.
    """
    entity_registry = er.async_get(hass)
    for subentry in entry.get_subentries_of_type(SUBENTRY_TYPE_TRACKER):
        for domain, key in REMOVED_OPTION_ENTITIES:
            entity_id = entity_registry.async_get_entity_id(
                domain, DOMAIN, f"{subentry.subentry_id}_{key}"
            )
            if entity_id is not None:
                entity_registry.async_remove(entity_id)
