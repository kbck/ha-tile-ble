"""Synthetic Tile credentials and Bluetooth observations for tests."""

import base64

from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from pytest_homeassistant_custom_component.common import MockConfigEntry
from tile_identity_resolver import TileResolver

from custom_components.tile_ble.const import DOMAIN, FEED_UUID

TILE_A = "0011223344556677"
TILE_B = "8899aabbccddeeff"
AUTH_KEY = base64.b64encode(bytes(range(16))).decode()
PRIVATE_A = bytes.fromhex("440bf67ac7f07409")
PRIVATE_A_NEXT = bytes.fromhex("ea66f0ff867ebf9d")
PRIVATE_B = bytes.fromhex("d2b455c3635acf6f")


def entry(tile_id=TILE_A, auth_key=AUTH_KEY):
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=tile_id,
        title="Keys",
        data={"tile_id": tile_id, "auth_key": auth_key},
    )


def service_info(private_id, *, time=100.0, rssi=-85, version=2, **overrides):
    address = overrides.pop("address", "AA:BB:CC:DD:EE:01")
    power = overrides.pop("tx_power", None)
    service_data = overrides.pop(
        "service_data", {FEED_UUID: bytes([version, 0]) + private_id}
    )
    advertisement = AdvertisementData(
        local_name="Tile",
        manufacturer_data={},
        service_data=service_data,
        service_uuids=[FEED_UUID],
        tx_power=power,
        rssi=rssi,
        platform_data=(),
    )
    return BluetoothServiceInfoBleak(
        name="Tile",
        address=address,
        rssi=rssi,
        manufacturer_data={},
        service_data=service_data,
        service_uuids=[FEED_UUID],
        source="scanner",
        device=BLEDevice(address, "Tile", {}),
        advertisement=advertisement,
        connectable=False,
        time=time,
        tx_power=power,
        **overrides,
    )


def observe(component, coordinator, now, *infos):
    component.bluetooth.MONOTONIC_TIME.return_value = now
    for info in infos:
        coordinator._async_advertisement(info, None)


def add_tile(coordinator, tile):
    resolver = TileResolver((*coordinator._resolver.tiles, tile))
    return coordinator.add_tile(tile, resolver)


def unavailable(component, info, index=-1):
    component.unavailable_addresses.add(info.address)
    component.unavailable_registrations[index][0](info)
