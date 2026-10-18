"""The few calls into Home Assistant's Bluetooth manager (M3e).

Bluetooth is optional: the integration has to load and work on an instance
without it. The `bluetooth` component is therefore never imported at module
level - importing it pulls in its own requirements and those of `usb` - but
only here, inside the calls, and only after the caller has made sure that the
component is loaded. A loaded component is already imported, so the import
costs nothing and does not block the event loop.
"""

from __future__ import annotations

import re
from types import ModuleType
from typing import NamedTuple

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr

from .const import BLUETOOTH_DOMAIN

# A static Bluetooth address, the form Home Assistant uses for it.
_ADDRESS = re.compile(r"^[0-9A-F]{2}(?::[0-9A-F]{2}){5}$")


class HeardDevice(NamedTuple):
    """A Bluetooth device the manager has heard, as the form offers it."""

    address: str
    name: str | None
    rssi: int | None


def _bluetooth() -> ModuleType:
    """Return Home Assistant's Bluetooth API. Only call it while it is loaded."""
    from homeassistant.components import bluetooth

    return bluetooth


@callback
def async_bluetooth_loaded(hass: HomeAssistant) -> bool:
    """Return whether Home Assistant's Bluetooth component is set up."""
    return BLUETOOTH_DOMAIN in hass.config.components


def normalize_address(value: str) -> str | None:
    """Return an address as `AA:BB:CC:DD:EE:FF`, or None if it is none.

    Upper case with colons, the way the Bluetooth manager keys its devices;
    dashes are accepted as separators too, because that is how some systems
    print an address.
    """
    address = value.strip().upper().replace("-", ":")
    return address if _ADDRESS.match(address) else None


@callback
def async_seconds_since_heard(hass: HomeAssistant, address: str) -> float | None:
    """Return how long ago an address was last heard, or None if never.

    The manager stores every advertisement in its history before it decides
    whether the payload is new, so the time of the last service info moves on
    every advertisement - a beacon that sends the same bytes over and over is
    still heard each time. That time is on the manager's monotonic clock.
    """
    bluetooth = _bluetooth()
    info = bluetooth.async_last_service_info(hass, address, connectable=False)
    if info is None:
        return None
    return max(bluetooth.MONOTONIC_TIME() - info.time, 0.0)


@callback
def async_heard_devices(hass: HomeAssistant) -> list[HeardDevice]:
    """Return every device the manager currently has an advertisement of.

    `name` is the advertised name, and None where the device advertises none:
    the manager then uses the address as the name, which says nothing new.
    """
    devices: list[HeardDevice] = []
    for info in _bluetooth().async_discovered_service_info(hass, connectable=False):
        address = normalize_address(info.address) or info.address
        name = info.name or None
        if name is not None and normalize_address(name) == address:
            name = None
        devices.append(HeardDevice(address, name, info.rssi))
    return devices


@callback
def registry_name(registry: dr.DeviceRegistry, address: str) -> str | None:
    """Return the name of the device with a Bluetooth address, if there is one.

    The name the user gave it, else the one its integration did. Only the
    device registry is read - nothing of the Bluetooth component - so this
    works on an instance without Bluetooth too. Home Assistant 2026.8 added
    `async_get_devices()`, and 2026.9 deprecated both `async_get_device()` and
    looking a device up through `devices`; the old call is only used where the
    new one does not exist yet (our floor is 2026.6).
    """
    connections = {
        (dr.CONNECTION_BLUETOOTH, address),
        (dr.CONNECTION_BLUETOOTH, address.lower()),
    }
    if (get_devices := getattr(registry, "async_get_devices", None)) is not None:
        devices = get_devices(connections=connections)
    else:
        found = registry.async_get_device(connections=connections)
        devices = [found] if found is not None else []
    for device in devices:
        if name := device.name_by_user or device.name:
            return name
    return None
