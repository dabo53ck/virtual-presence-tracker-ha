"""Tests for the registry clean-ups of older installs.

The household device of M1f, and the option entities that moved into the
tracker's form in M3g.
"""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.virtual_presence_tracker.const import (
    CONF_ANSWER_TIMEOUT,
    CONF_ASK_ON_DEPARTURE,
    CONF_AWAY_AFTER,
    CONF_NOTIFY_ON_EXPIRY,
    CONF_PROMPT_DELAY,
    CONF_REMIND_AFTER,
    CONF_REMINDER_TIMEOUT,
    DOMAIN,
)
from homeassistant.components.binary_sensor import DOMAIN as BINARY_SENSOR_DOMAIN
from homeassistant.const import ATTR_FRIENDLY_NAME, STATE_NOT_HOME, STATE_OFF
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .conftest import (
    ENTRY_ID,
    PERSON_A,
    TRACKER_A,
    TRACKER_B,
    make_entry,
    make_subentry,
)

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


# The six option entities M3g moved into the tracker's form, with the entity
# IDs an English install of M3f gave them.
MOVED_OPTIONS = {
    ("number", CONF_ANSWER_TIMEOUT): "prompt_answer_time",
    ("number", CONF_PROMPT_DELAY): "prompt_delay",
    ("number", CONF_REMIND_AFTER): "remind_after",
    ("number", CONF_REMINDER_TIMEOUT): "reminder_answer_time",
    ("number", CONF_AWAY_AFTER): "away_after",
    ("switch", CONF_NOTIFY_ON_EXPIRY): "notice_if_unanswered",
}


def add_moved_option_entities(
    hass: HomeAssistant, entry: MockConfigEntry, subentry_id: str, name: str
) -> list[str]:
    """Register the six option entities of one tracker as M3f left them."""
    registry = er.async_get(hass)
    entity_ids = []
    for (domain, key), suffix in MOVED_OPTIONS.items():
        entity = registry.async_get_or_create(
            domain,
            DOMAIN,
            f"{subentry_id}_{key}",
            config_entry=entry,
            config_subentry_id=subentry_id,
            suggested_object_id=f"{name}_{suffix}",
            translation_key=key,
        )
        assert entity.entity_id == f"{domain}.{name}_{suffix}"
        entity_ids.append(entity.entity_id)
    return entity_ids


async def test_setup_removes_the_option_entities_that_moved_into_the_form(
    hass: HomeAssistant,
) -> None:
    """The six entities go for every tracker; nothing else is touched."""
    entry = make_entry(
        make_subentry(TRACKER_A, "Kid"), make_subentry(TRACKER_B, "Granny")
    )
    entry.add_to_hass(hass)
    moved = add_moved_option_entities(hass, entry, TRACKER_A, "kid")
    moved += add_moved_option_entities(hass, entry, TRACKER_B, "granny")
    registry = er.async_get(hass)
    # A switch that stays, registered before the setup: it keeps its ID.
    ask = registry.async_get_or_create(
        "switch",
        DOMAIN,
        f"{TRACKER_A}_{CONF_ASK_ON_DEPARTURE}",
        config_entry=entry,
        config_subentry_id=TRACKER_A,
        suggested_object_id="kid_ask_when_empty",
    )
    # Another integration's entity that happens to carry the same unique ID.
    foreign = registry.async_get_or_create(
        "number", "other_integration", f"{TRACKER_A}_{CONF_ANSWER_TIMEOUT}"
    )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    for entity_id in moved:
        assert registry.async_get(entity_id) is None, entity_id
        assert hass.states.get(entity_id) is None, entity_id
    assert registry.async_get(ask.entity_id) is not None
    assert hass.states.get(ask.entity_id) is not None
    assert registry.async_get(foreign.entity_id) is not None


async def test_the_option_clean_up_is_harmless_on_every_setup(
    hass: HomeAssistant,
) -> None:
    """A reload after the clean-up finds nothing and changes nothing."""
    entry = make_entry(make_subentry(TRACKER_A, "Kid"))
    entry.add_to_hass(hass)
    moved = add_moved_option_entities(hass, entry, TRACKER_A, "kid")

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    before = {
        entity.entity_id
        for entity in er.async_entries_for_config_entry(registry, entry.entry_id)
    }

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    after = {
        entity.entity_id
        for entity in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    assert after == before
    assert not set(moved) & after
    assert "switch.kid_at_home" in after
