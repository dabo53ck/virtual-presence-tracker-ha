"""Tests for the clean-up of the legacy household device."""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.virtual_presence_tracker.const import DOMAIN
from homeassistant.components.binary_sensor import DOMAIN as BINARY_SENSOR_DOMAIN
from homeassistant.const import ATTR_FRIENDLY_NAME, STATE_NOT_HOME, STATE_OFF
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .conftest import ENTRY_ID, PERSON_A, TRACKER_A, make_entry, make_subentry

UNIQUE_ID = f"{ENTRY_ID}_only_virtual_home"
# The entity ID an install from before the change ended up with: the device
# name prefixed the entity name, and this one was renamed to German.
LEGACY_SENSOR = "binary_sensor.virtual_presence_tracker_nur_virtuelle_tracker_zuhause"


def add_legacy_household_device(
    hass: HomeAssistant, entry: MockConfigEntry
) -> tuple[dr.DeviceEntry, str]:
    """Register the household device and the sensor as M1f left them."""
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name="Virtual Presence Tracker",
        entry_type=dr.DeviceEntryType.SERVICE,
    )
    entity = er.async_get(hass).async_get_or_create(
        BINARY_SENSOR_DOMAIN,
        DOMAIN,
        UNIQUE_ID,
        config_entry=entry,
        device_id=device.id,
        has_entity_name=True,
        original_name="Only virtual trackers home",
        suggested_object_id="virtual_presence_tracker_nur_virtuelle_tracker_zuhause",
        translation_key="only_virtual_home",
    )
    assert entity.entity_id == LEGACY_SENSOR
    return device, entity.id


async def test_setup_keeps_the_sensor_and_drops_the_device(
    hass: HomeAssistant,
) -> None:
    """The household device goes, the sensor keeps its identity and state."""
    entry = make_entry(make_subentry(TRACKER_A, "Kid"))
    entry.add_to_hass(hass)
    device, registry_id = add_legacy_household_device(hass, entry)

    hass.states.async_set(PERSON_A, STATE_NOT_HOME)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    entity_registry = er.async_get(hass)
    entity = entity_registry.async_get(LEGACY_SENSOR)
    assert entity is not None
    assert entity.id == registry_id
    assert entity.unique_id == UNIQUE_ID
    assert entity.device_id is None
    assert (
        entity_registry.async_get_entity_id(BINARY_SENSOR_DOMAIN, DOMAIN, UNIQUE_ID)
        == LEGACY_SENSOR
    )

    # The sensor works under its old entity ID, and it is the only one.
    state = hass.states.get(LEGACY_SENSOR)
    assert state is not None
    assert state.state == STATE_OFF
    assert state.attributes[ATTR_FRIENDLY_NAME] == "Only virtual trackers home"
    assert hass.states.get("binary_sensor.only_virtual_trackers_home") is None

    device_registry = dr.async_get(hass)
    assert device_registry.async_get(device.id) is None
    assert (
        device_registry.async_get_device_by_identifier(
            (DOMAIN, entry.entry_id), entry.entry_id
        )
        is None
    )
    # The device of the tracker subentry is untouched.
    tracker_device = device_registry.async_get_device_by_identifier(
        (DOMAIN, TRACKER_A), entry.entry_id
    )
    assert tracker_device is not None
    assert tracker_device.config_subentry_id == TRACKER_A


async def test_reload_after_the_cleanup_changes_nothing(hass: HomeAssistant) -> None:
    """A second setup finds nothing to do and leaves the sensor alone."""
    entry = make_entry(make_subentry(TRACKER_A, "Kid"))
    entry.add_to_hass(hass)
    add_legacy_household_device(hass, entry)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    entity = er.async_get(hass).async_get(LEGACY_SENSOR)
    assert entity is not None
    assert entity.unique_id == UNIQUE_ID
    assert entity.device_id is None
    assert hass.states.get(LEGACY_SENSOR) is not None

    devices = dr.async_get(hass)
    assert (
        devices.async_get_device_by_identifier((DOMAIN, entry.entry_id), entry.entry_id)
        is None
    )
    assert (
        devices.async_get_device_by_identifier((DOMAIN, TRACKER_A), entry.entry_id)
        is not None
    )


async def test_fresh_install_has_no_household_device(hass: HomeAssistant) -> None:
    """Without a legacy device the sensor is created without one."""
    entry = make_entry(make_subentry(TRACKER_A, "Kid"))
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    entity = er.async_get(hass).async_get("binary_sensor.only_virtual_trackers_home")
    assert entity is not None
    assert entity.unique_id == UNIQUE_ID
    assert entity.device_id is None

    state = hass.states.get("binary_sensor.only_virtual_trackers_home")
    assert state is not None
    assert state.attributes[ATTR_FRIENDLY_NAME] == "Only virtual trackers home"

    assert (
        dr.async_get(hass).async_get_device_by_identifier(
            (DOMAIN, entry.entry_id), entry.entry_id
        )
        is None
    )
