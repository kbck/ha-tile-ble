"""Test setup, entities, and unloading through Home Assistant."""

from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_HOME, STATE_NOT_HOME, STATE_UNAVAILABLE
from homeassistant.helpers import entity_registry as er

from custom_components.tile_ble.diagnostics import async_get_config_entry_diagnostics
from custom_components.tile_ble.sensor import SENSORS

from .common import (
    DOMAIN,
    PRIVATE_A,
    TILE_A,
    TILE_B,
    entry,
    observe,
    service_info,
    unavailable,
)


async def setup_entry(hass, tile_entry):
    tile_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(tile_entry.entry_id)
    await hass.async_block_till_done()
    assert tile_entry.state is ConfigEntryState.LOADED


async def test_setup_and_last_entry_unload(
    hass, component, entity_registry, device_registry
):
    a, b = entry(), entry(TILE_B)
    await setup_entry(hass, a)
    await setup_entry(hass, b)
    coordinator = a.runtime_data.coordinator
    state = a.runtime_data.state
    assert coordinator is b.runtime_data.coordinator is hass.data[DOMAIN]
    assert state is coordinator.tiles[TILE_A]
    component.bluetooth.async_register_callback.assert_called_once()
    cancel_discovery = coordinator._cancel_bluetooth
    tracker = entity_registry.async_get_entity_id(
        "device_tracker", DOMAIN, f"{TILE_A}_tracker"
    )
    assert hass.states.get(tracker).state == STATE_NOT_HOME
    device = device_registry.async_get_device_by_identifier(
        (DOMAIN, TILE_A), a.entry_id
    )
    assert device.manufacturer == "Tile"
    assert device.name == "Keys"
    for description in SENSORS:
        sensor = entity_registry.async_get_entity_id(
            "sensor", DOMAIN, f"{TILE_A}_{description.key}"
        )
        assert (
            entity_registry.async_get(sensor).disabled_by
            is er.RegistryEntryDisabler.INTEGRATION
        )

    observe(component, coordinator, 100, service_info(PRIVATE_A))
    await hass.async_block_till_done()
    assert hass.states.get(tracker).state == STATE_HOME
    cancel_unavailable = component.unavailable_registrations[-1][2]
    cancel_packets = component.advertisement_registrations[-1][2]
    assert await async_get_config_entry_diagnostics(hass, a) == {
        "identity_resolver": "tile-identity-resolver",
        "loaded": True,
        "present": True,
        "seen": True,
    }
    assert await hass.config_entries.async_unload(a.entry_id)
    await hass.async_block_till_done()
    assert a.state is ConfigEntryState.NOT_LOADED
    assert not state.listeners
    assert TILE_A not in coordinator.tiles and TILE_B in coordinator.tiles
    cancel_unavailable.assert_called_once()
    cancel_packets.assert_called_once()
    cancel_discovery.assert_not_called()
    assert not (await async_get_config_entry_diagnostics(hass, a))["loaded"]
    assert await hass.config_entries.async_unload(b.entry_id)
    await hass.async_block_till_done()
    assert DOMAIN not in hass.data
    cancel_discovery.assert_called_once()


async def test_enabled_sensors_follow_observations(hass, component, entity_registry):
    tile_entry = entry()
    tile_entry.add_to_hass(hass)
    sensor_ids = {}
    # Enable diagnostics before setup, as a user can do via the entity registry.
    for description in SENSORS:
        sensor = entity_registry.async_get_or_create(
            "sensor",
            DOMAIN,
            f"{TILE_A}_{description.key}",
            config_entry=tile_entry,
            suggested_object_id=description.key,
        )
        sensor_ids[description.key] = sensor.entity_id
    assert await hass.config_entries.async_setup(tile_entry.entry_id)
    await hass.async_block_till_done()
    coordinator = tile_entry.runtime_data.coordinator
    tracker = entity_registry.async_get_entity_id(
        "device_tracker", DOMAIN, f"{TILE_A}_tracker"
    )
    assert all(
        hass.states.get(entity_id).state == STATE_UNAVAILABLE
        for entity_id in sensor_ids.values()
    )
    observe(component, coordinator, 100, service_info(PRIVATE_A))
    await hass.async_block_till_done()
    assert hass.states.get(tracker).state == STATE_HOME
    assert hass.states.get(sensor_ids["rssi"]).state == "-85"
    assert hass.states.get(sensor_ids["feed_version"]).state == "2"
    assert hass.states.get(sensor_ids["tx_power"]).state == STATE_UNAVAILABLE
    assert hass.states.get(sensor_ids["estimated_distance"]).state == STATE_UNAVAILABLE
    component.bluetooth.async_get_learned_advertising_interval.return_value = 8
    info = service_info(PRIVATE_A, time=110, tx_power=-7)
    observe(component, coordinator, 110, info)
    await hass.async_block_till_done()
    assert hass.states.get(sensor_ids["tx_power"]).state == "-7"
    assert float(hass.states.get(sensor_ids["estimated_distance"]).state) > 0
    assert hass.states.get(sensor_ids["estimated_broadcast_interval"]).state == "8"
    assert hass.states.get(tracker).attributes["current_address"] == info.address
    assert hass.states.get(tracker).attributes["source"] == info.source
    unavailable(component, info)
    await hass.async_block_till_done()
    assert hass.states.get(tracker).state == STATE_NOT_HOME
    assert hass.states.get(sensor_ids["rssi"]).state == STATE_UNAVAILABLE
    assert hass.states.get(sensor_ids["last_counter"]).state == "0"
    assert await hass.config_entries.async_unload(tile_entry.entry_id)
    await hass.async_block_till_done()


async def test_invalid_credentials_fail_setup(hass):
    tile_entry = entry(auth_key="bad")
    tile_entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(tile_entry.entry_id)
    assert tile_entry.state is ConfigEntryState.SETUP_ERROR
    assert DOMAIN not in hass.data
    assert not (await async_get_config_entry_diagnostics(hass, tile_entry))["loaded"]


async def test_failed_platform_setup_cleans_up(hass, component):
    tile_entry = entry()
    tile_entry.add_to_hass(hass)
    with patch.object(
        hass.config_entries,
        "async_forward_entry_setups",
        side_effect=RuntimeError("setup failed"),
    ):
        assert not await hass.config_entries.async_setup(tile_entry.entry_id)
    assert tile_entry.state is ConfigEntryState.SETUP_ERROR
    assert DOMAIN not in hass.data
    assert not tile_entry.runtime_data.coordinator.tiles
    assert tile_entry.runtime_data.coordinator._cancel_bluetooth is None


async def test_failed_platform_unload_keeps_runtime_data(hass, component):
    tile_entry = entry()
    await setup_entry(hass, tile_entry)
    runtime_data = tile_entry.runtime_data
    with patch.object(
        hass.config_entries, "async_unload_platforms", return_value=False
    ):
        assert not await hass.config_entries.async_unload(tile_entry.entry_id)
    assert tile_entry.runtime_data is runtime_data
    assert TILE_A in runtime_data.coordinator.tiles
    assert (await async_get_config_entry_diagnostics(hass, tile_entry))["loaded"]
    assert tile_entry.state is ConfigEntryState.FAILED_UNLOAD
