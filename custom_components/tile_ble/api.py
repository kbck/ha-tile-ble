"""Resolver API for integrations consuming configured Tile identities.

All functions and callbacks run synchronously on HA's event loop. Subscriptions
do not replay observations; subscribe before reading the latest service info.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from homeassistant.components import bluetooth
from homeassistant.core import callback

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
    from homeassistant.core import HomeAssistant

    from .coordinator import TileCoordinator


@callback
def async_get_coordinator(hass: HomeAssistant) -> TileCoordinator | None:
    """Return the loaded resolver, or None; never start a scanner or load a Tile."""
    return hass.data.get(DOMAIN)


@callback
def async_last_service_info(
    hass: HomeAssistant, tile_id: str
) -> BluetoothServiceInfoBleak | None:
    """Return the latest currently available, unambiguous Tile observation.

    Unknown or unloaded Tiles return None. Malformed IDs raise ValueError.
    Reception does not imply that a connectable Bluetooth controller is in range.
    """
    tile_id = _normalize_tile_id(tile_id)
    coordinator = async_get_coordinator(hass)
    if coordinator is None:
        return None
    state = coordinator.tiles.get(tile_id)
    if state is None or not state.present or state.last_info is None:
        return None
    info = state.last_info
    if not bluetooth.async_address_present(hass, info.address, connectable=False):
        return None
    return info


@callback
def async_track_service_info(
    hass: HomeAssistant,
    listener: Callable[[BluetoothServiceInfoBleak], None],
    tile_id: str,
) -> Callable[[], None]:
    """Subscribe to newer resolved observations, including address rotations.

    Callbacks receive one service-info argument, without a BluetoothChange value.
    Unknown/unloaded Tiles raise KeyError; malformed IDs raise ValueError.
    Returns an idempotent unsubscribe. Source unload clears the subscription;
    consumers must subscribe again after source reload.
    """
    return _subscribe(hass, tile_id, listener, "service_info_listeners")


@callback
def async_track_unavailable(
    hass: HomeAssistant,
    listener: Callable[[BluetoothServiceInfoBleak], None],
    tile_id: str,
) -> Callable[[], None]:
    """Subscribe to loss of a resolved Tile, passing its last observation.

    Fires on disappearance, ambiguous identity, or source unload if previously
    present. Registration and cancellation follow async_track_service_info.
    """
    return _subscribe(hass, tile_id, listener, "unavailable_listeners")


def _subscribe(hass, tile_id, listener, collection):
    tile_id = _normalize_tile_id(tile_id)
    coordinator = async_get_coordinator(hass)
    if coordinator is None or tile_id not in coordinator.tiles:
        raise KeyError("Tile is not loaded")
    listeners = getattr(coordinator.tiles[tile_id], collection)
    # Separate registrations of the same callable have independent lifetimes.

    def registered(info):
        listener(info)

    listeners.add(registered)
    return lambda: listeners.discard(registered)


def _normalize_tile_id(value: str) -> str:
    """Normalize IDs supplied by API consumers without requiring a key."""
    decoded = bytes.fromhex(value)
    if len(decoded) != 8:
        raise ValueError("Tile ID must be eight bytes of hexadecimal")
    return decoded.hex()
