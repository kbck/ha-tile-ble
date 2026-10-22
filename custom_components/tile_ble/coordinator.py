"""Resolve Tile identities and delegate reachability to HA Bluetooth."""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from homeassistant.components import bluetooth
from homeassistant.core import callback
from tile_identity_resolver import TileResolver

from .const import DOMAIN, FEED_UUID

_LOGGER = logging.getLogger(__name__)


def _mutation_lock(hass):
    """Keep one lock across coordinator unloads and reloads."""
    return hass.data.setdefault(f"{DOMAIN}_lock", asyncio.Lock())


async def async_add_tile(hass, tile):
    """Build a replacement resolver off-loop, then register on the HA loop."""
    async with _mutation_lock(hass):
        coordinator = hass.data.get(DOMAIN)
        tiles = coordinator._resolver.tiles if coordinator else ()
        resolver = await hass.async_add_executor_job(TileResolver, (*tiles, tile))
        if coordinator is None:
            coordinator = hass.data[DOMAIN] = TileCoordinator(hass)
        try:
            coordinator.add_tile(tile, resolver)
        except Exception:
            if not coordinator.tiles:
                hass.data.pop(DOMAIN, None)
            raise
        return coordinator


async def async_remove_tile(hass, tile_id):
    """Wait for any resolver build before removing a Tile."""
    async with _mutation_lock(hass):
        coordinator = hass.data[DOMAIN]
        coordinator.remove_tile(tile_id)
        if not coordinator.tiles:
            hass.data.pop(DOMAIN)


def resolve_info(resolver, info):
    """Pass only FEED service-data bytes to the standalone identity resolver."""
    for uuid, payload in info.service_data.items():
        if uuid.lower() == FEED_UUID:
            return resolver.resolve(payload)
    return None


def latest_matching_info(hass, resolver):
    """Find the latest matching observation HA considers currently available."""
    now = bluetooth.MONOTONIC_TIME()
    return max(
        (
            info
            for info in bluetooth.async_discovered_service_info(hass, connectable=False)
            if info.time <= now
            and bluetooth.async_address_present(hass, info.address, connectable=False)
            and resolve_info(resolver, info) is not None
        ),
        key=lambda info: info.time,
        default=None,
    )


@dataclass
class TileState:
    """Shared runtime state; authentication keys are never retained here."""

    tile_id: str
    present: bool = False
    last_info: object | None = field(default=None, repr=False)
    last_counter: int | None = None
    feed_version: int | None = None
    feed_flags: int | None = None
    listeners: set[Callable] = field(default_factory=set, repr=False)
    service_info_listeners: set[Callable] = field(default_factory=set, repr=False)
    unavailable_listeners: set[Callable] = field(default_factory=set, repr=False)
    tracking_token: object | None = field(default=None, repr=False)
    cancel_unavailable: Callable | None = field(default=None, repr=False)
    cancel_advertisements: Callable | None = field(default=None, repr=False)


class TileCoordinator:
    """Share discovery and resolve service data before publishing observations."""

    def __init__(self, hass):
        self.hass = hass
        self.tiles: dict[str, TileState] = {}
        self._resolver = TileResolver()
        self._cancel_bluetooth = None

    @callback
    def add_tile(self, tile, resolver):
        """Install a prepared resolver before replaying HA's discovery cache."""
        tile_id = tile.tile_id
        if tile_id in self.tiles:
            raise ValueError("Tile is already loaded")
        self._resolver = resolver
        state = self.tiles[tile_id] = TileState(tile_id)
        try:
            # A newly configured owner can make an already resolved ID ambiguous.
            for loaded in self.tiles.values():
                if (
                    loaded.last_info is not None
                    and resolve_info(self._resolver, loaded.last_info) is None
                ):
                    self._stop_tracking(loaded)
                    self._mark_unavailable(loaded)
                    self._notify(loaded)
            if self._cancel_bluetooth is None:
                self._cancel_bluetooth = bluetooth.async_register_callback(
                    self.hass,
                    self._async_advertisement,
                    {"service_uuid": FEED_UUID, "connectable": False},
                    bluetooth.BluetoothScanningMode.PASSIVE,
                )
            self._seed_from_cache()
        except Exception:
            self.remove_tile(tile_id)
            raise
        return state

    @callback
    def remove_tile(self, tile_id):
        state = self.tiles.pop(tile_id)
        self._stop_tracking(state)
        self._mark_unavailable(state)
        self._resolver.remove(tile_id)
        state.listeners.clear()
        state.service_info_listeners.clear()
        state.unavailable_listeners.clear()
        if not self.tiles and self._cancel_bluetooth is not None:
            self._cancel_bluetooth()
            self._cancel_bluetooth = None

    @callback
    def subscribe(self, tile_id, listener):
        listeners = self.tiles[tile_id].listeners
        listeners.add(listener)
        return lambda: listeners.discard(listener)

    def _notify(self, state):
        for listener in tuple(state.listeners):
            listener()

    def _notify_consumers(self, listeners, info):
        for listener in tuple(listeners):
            try:
                listener(info)
            except Exception:
                _LOGGER.exception("Tile resolver subscriber failed")

    def _mark_unavailable(self, state):
        if state.present:
            state.present = False
            self._notify_consumers(state.unavailable_listeners, state.last_info)

    def _stop_tracking(self, state):
        state.tracking_token = None
        if state.cancel_unavailable is not None:
            state.cancel_unavailable()
            state.cancel_unavailable = None
        if state.cancel_advertisements is not None:
            state.cancel_advertisements()
            state.cancel_advertisements = None

    def _track_address(self, state, address, previous_address):
        self._stop_tracking(state)
        if previous_address is not None:
            interval = bluetooth.async_get_learned_advertising_interval(
                self.hass, previous_address
            ) or bluetooth.async_get_fallback_availability_interval(
                self.hass, previous_address
            )
            if interval:
                bluetooth.async_set_fallback_availability_interval(
                    self.hass, address, interval
                )
        token = state.tracking_token = object()

        @callback
        def unavailable(info):
            # The token also protects A -> B -> A rotations and unload/reload.
            if state.tracking_token is not token or info.address != address:
                return
            # Per-packet callbacks can be newer than HA's selected proxy history.
            # Use HA's reachability state, rather than comparing those timestamps.
            if bluetooth.async_address_present(self.hass, address, connectable=False):
                return
            if state.present:
                self._mark_unavailable(state)
                self._notify(state)

        @callback
        def advertisement(info):
            if state.tracking_token is token:
                self._observe(info)

        try:
            state.cancel_unavailable = bluetooth.async_track_unavailable(
                self.hass, unavailable, address, connectable=False
            )
            state.cancel_advertisements = (
                bluetooth.async_register_advertisement_callback(
                    self.hass, advertisement, address
                )
            )
        except Exception:
            self._stop_tracking(state)
            raise

    def _observe(self, info):
        match = resolve_info(self._resolver, info)
        if match is None:
            return
        state = self.tiles[match.tile.tile_id]
        if info.time > bluetooth.MONOTONIC_TIME():
            return
        previous = state.last_info
        if previous is not None and info.time <= previous.time:
            return
        previous_address = previous.address if previous is not None else None
        counter_changed = state.last_counter != match.counter
        state.last_info = info
        state.last_counter = match.counter
        state.feed_version = match.version
        state.feed_flags = match.flags
        if previous_address != info.address or state.tracking_token is None:
            self._track_address(state, info.address, previous_address)
        if previous_address is not None and previous_address != info.address:
            _LOGGER.debug(
                "Tile %s MAC address changed from %s to %s",
                state.tile_id,
                previous_address,
                info.address,
            )
        state.present = True
        if counter_changed:
            _LOGGER.debug(
                "Tile %s resolved advertisement: address=%s source=%s RSSI=%s counter=%s",
                state.tile_id,
                info.address,
                info.source,
                info.rssi,
                match.counter,
            )
        self._notify(state)
        self._notify_consumers(state.service_info_listeners, info)

    @callback
    def _async_advertisement(self, service_info, change):
        """Resolve new addresses, including currently available replayed packets."""
        if bluetooth.async_address_present(
            self.hass, service_info.address, connectable=False
        ):
            self._observe(service_info)

    def _seed_from_cache(self):
        """Seed entries once; HA owns expiry and repeated packets use callbacks."""
        infos = sorted(
            bluetooth.async_discovered_service_info(self.hass, connectable=False),
            key=lambda info: info.time,
        )
        for info in infos:
            self._async_advertisement(info, None)
