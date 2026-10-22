"""Focused component tests using the repository's lightweight HA-stub pattern."""

import asyncio
import base64
import importlib
import logging
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from tile_identity_resolver import Tile, TileResolver

DOMAIN = "tile_ble"
PACKAGE = f"custom_components.{DOMAIN}"
TILE_A = "0011223344556677"
TILE_B = "8899aabbccddeeff"
AUTH_KEY = base64.b64encode(bytes(range(16))).decode()
# Version-2 private IDs for the synthetic credentials above, counters 0,
# 256 (Tile A), and 8639 (Tile B). Protocol derivation is tested by the library.
PRIVATE_A = bytes.fromhex("440bf67ac7f07409")
PRIVATE_A_NEXT = bytes.fromhex("ea66f0ff867ebf9d")
PRIVATE_B = bytes.fromhex("d2b455c3635acf6f")

@pytest.fixture
def component():
    """Load the real component under minimal substitutes for HA interfaces."""
    names = (
        "homeassistant",
        "homeassistant.config_entries",
        "homeassistant.const",
        "homeassistant.core",
        "homeassistant.exceptions",
        "homeassistant.components",
        "homeassistant.components.bluetooth",
        "homeassistant.components.device_tracker",
        "homeassistant.components.sensor",
        "homeassistant.helpers.entity",
        "bluetooth_data_tools",
        "homeassistant.helpers",
        "homeassistant.helpers.device_registry",
        "homeassistant.helpers.selector",
    )
    modules = {name: ModuleType(name) for name in names}
    core = modules["homeassistant.core"]
    core.callback = lambda func: func
    modules["homeassistant.const"].Platform = SimpleNamespace(
        DEVICE_TRACKER="device_tracker", SENSOR="sensor"
    )
    modules["homeassistant.const"].CONF_NAME = "name"
    modules["homeassistant.exceptions"].ConfigEntryError = type(
        "ConfigEntryError", (Exception,), {}
    )
    bluetooth = modules["homeassistant.components.bluetooth"]
    bluetooth.async_discovered_service_info = Mock(return_value=[])
    bluetooth.async_scanner_count = Mock(return_value=1)
    bluetooth.async_register_callback = Mock(side_effect=lambda *args: Mock())
    bluetooth.MONOTONIC_TIME = Mock(return_value=100.0)
    unavailable_addresses = set()
    bluetooth.async_address_present = Mock(
        side_effect=lambda hass, address, connectable: (
            address not in unavailable_addresses
        )
    )
    bluetooth.async_get_fallback_availability_interval = Mock(return_value=None)
    bluetooth.async_set_fallback_availability_interval = Mock()
    unavailable_registrations = []
    advertisement_registrations = []

    def register_unavailable(hass, listener, address, *, connectable):
        assert connectable is False
        cancel = Mock()
        unavailable_registrations.append((listener, address, cancel))
        return cancel

    def register_advertisement(hass, listener, address):
        cancel = Mock()
        advertisement_registrations.append((listener, address, cancel))
        return cancel

    bluetooth.async_track_unavailable = Mock(side_effect=register_unavailable)
    bluetooth.async_register_advertisement_callback = Mock(
        side_effect=register_advertisement
    )
    bluetooth.async_get_learned_advertising_interval = Mock(return_value=None)
    bluetooth.BluetoothScanningMode = SimpleNamespace(PASSIVE="passive")

    class Entity:
        async def async_added_to_hass(self):
            pass

        def async_on_remove(self, cancel):
            self.cancellations.append(cancel)

    modules["homeassistant.helpers.entity"].Entity = Entity
    tracker = modules["homeassistant.components.device_tracker"]
    tracker.BaseScannerEntity = type("BaseScannerEntity", (Entity,), {})
    tracker.SourceType = SimpleNamespace(BLUETOOTH_LE="bluetooth_le")
    sensors = modules["homeassistant.components.sensor"]
    sensors.SensorEntity = type("SensorEntity", (Entity,), {})
    sensors.SensorDeviceClass = SimpleNamespace(
        SIGNAL_STRENGTH="signal_strength", DISTANCE="distance"
    )
    sensors.SensorStateClass = SimpleNamespace(MEASUREMENT="measurement")

    @dataclass(frozen=True, kw_only=True)
    class Description:
        key: str
        name: str = ""
        device_class: str | None = None
        native_unit_of_measurement: str | None = None
        state_class: str | None = None
        suggested_display_precision: int | None = None

    sensors.SensorEntityDescription = Description
    const = modules["homeassistant.const"]
    const.EntityCategory = SimpleNamespace(DIAGNOSTIC="diagnostic")
    const.SIGNAL_STRENGTH_DECIBELS_MILLIWATT = "dBm"
    const.UnitOfLength = SimpleNamespace(METERS="m")
    const.UnitOfTime = SimpleNamespace(SECONDS="s")
    modules["bluetooth_data_tools"].calculate_distance_meters = Mock(return_value=1.5)
    modules["homeassistant.helpers.device_registry"].DeviceInfo = dict
    selector = modules["homeassistant.helpers.selector"]
    selector.TextSelectorType = SimpleNamespace(PASSWORD="password")
    selector.TextSelectorConfig = dict
    selector.TextSelector = lambda config: str

    class FlowAbort(Exception):
        pass

    class Flow:
        def __init_subclass__(cls, **kwargs):
            pass

        async def async_set_unique_id(self, unique_id):
            self.unique_id = unique_id

        def _abort_if_unique_id_configured(self):
            if self.unique_id in getattr(self, "configured", set()):
                raise FlowAbort("already_configured")

        def _abort_if_unique_id_mismatch(self):
            assert self.unique_id == self.entry.unique_id

        def _get_reconfigure_entry(self):
            return self.entry

        def async_update_reload_and_abort(self, entry, data_updates):
            entry.data = {**entry.data, **data_updates}
            return {"type": "abort", "reason": "reconfigure_successful"}

        def async_show_form(self, **kwargs):
            return {"type": "form", **kwargs}

        def async_create_entry(self, **kwargs):
            return {"type": "create_entry", **kwargs}

    config_entries = modules["homeassistant.config_entries"]
    config_entries.ConfigFlow = Flow
    class ConfigEntry:
        def __class_getitem__(cls, item):
            return cls

    config_entries.ConfigEntry = ConfigEntry
    old = {
        name: value
        for name, value in sys.modules.items()
        if name == "custom_components" or name.startswith(PACKAGE)
    }
    for name in old:
        del sys.modules[name]
    root = str(Path(__file__).resolve().parents[1])
    with patch.dict(sys.modules, modules), patch.object(sys, "path", [root, *sys.path]):
        integration = importlib.import_module(PACKAGE)
        flow = importlib.import_module(f"{PACKAGE}.config_flow")
        sensor = importlib.import_module(f"{PACKAGE}.sensor")
        tracker_module = importlib.import_module(f"{PACKAGE}.device_tracker")
        diagnostics = importlib.import_module(f"{PACKAGE}.diagnostics")
        yield SimpleNamespace(
            integration=integration,
            api=importlib.import_module(f"{PACKAGE}.api"),
            flow=flow,
            sensor=sensor,
            manager=importlib.import_module(f"{PACKAGE}.coordinator"),
            tracker=tracker_module,
            diagnostics=diagnostics,
            bluetooth=bluetooth,
            unavailable_addresses=unavailable_addresses,
            unavailable_registrations=unavailable_registrations,
            advertisement_registrations=advertisement_registrations,
            FlowAbort=FlowAbort,
        )
    for name in list(sys.modules):
        if name == "custom_components" or name.startswith(PACKAGE):
            del sys.modules[name]
    sys.modules.update(old)


def entry(tile_id=TILE_A, auth_key=AUTH_KEY):
    return SimpleNamespace(
        entry_id=tile_id,
        unique_id=tile_id,
        title="Keys",
        data={"tile_id": tile_id, "auth_key": auth_key},
    )


def service_info(private_id, *, time=100.0, rssi=-85, version=2, **overrides):
    fields = {
        "advertisement": SimpleNamespace(tx_power=None),
        "time": time,
        "rssi": rssi,
        "address": "rotating-address",
        "source": "scanner",
        "service_uuids": [],
        "service_data": {
            "0000feed-0000-1000-8000-00805f9b34fb": bytes([version, 0]) + private_id
        },
    }
    return SimpleNamespace(**{**fields, **overrides})


def hass_stub():
    async def executor(func, *args):
        return func(*args)

    return SimpleNamespace(
        data={},
        async_add_executor_job=AsyncMock(side_effect=executor),
        config_entries=SimpleNamespace(
            async_forward_entry_setups=AsyncMock(),
            async_unload_platforms=AsyncMock(return_value=True),
        ),
    )


def observe(component, coordinator, now, *infos):
    component.bluetooth.MONOTONIC_TIME.return_value = now
    for info in infos:
        coordinator._async_advertisement(info, None)


def add_tile(coordinator, tile):
    """Provide a complete prepared resolver for synchronous coordinator tests."""
    resolver = TileResolver((*coordinator._resolver.tiles, tile))
    return coordinator.add_tile(tile, resolver)


def unavailable(component, info, index=-1):
    component.unavailable_addresses.add(info.address)
    component.unavailable_registrations[index][0](info)


def test_config_validation_offline_duplicates_and_reconfigure(component):
    async def run():
        flow = component.flow.TileBLEConfigFlow()
        flow.hass = hass_stub()
        credentials = {
            "name": " Keys ",
            "tile_id": TILE_A.upper(),
            "auth_key": AUTH_KEY,
        }
        result = await flow.async_step_user(
            {**credentials, "tile_id": "00", "auth_key": "bad"}
        )
        assert result["errors"] == {
            "base": "invalid_credentials",
        }
        assert (await flow.async_step_user(credentials))["errors"] == {
            "base": "not_seen"
        }
        component.bluetooth.async_scanner_count.return_value = 0
        assert (await flow.async_step_user(credentials))["errors"] == {
            "base": "no_scanners"
        }
        result = await flow.async_step_user({**credentials, "allow_unseen": True})
        assert result["title"] == "Keys"
        assert result["data"] == {"tile_id": TILE_A, "auth_key": AUTH_KEY}
        hex_key = bytes(range(16)).hex()
        result = await flow.async_step_user(
            {**credentials, "auth_key": hex_key, "allow_unseen": True}
        )
        assert result["data"]["auth_key"] == hex_key
        flow.configured = {TILE_A}
        with pytest.raises(component.FlowAbort, match="already_configured"):
            await flow.async_step_user({**credentials, "allow_unseen": True})
        flow.configured = set()
        component.bluetooth.async_scanner_count.return_value = 1
        pid = PRIVATE_A
        component.bluetooth.async_discovered_service_info.return_value = [
            service_info(pid, time=1)
        ]
        assert (await flow.async_step_user(credentials))["type"] == "create_entry"
        component.unavailable_addresses.add("rotating-address")
        assert (await flow.async_step_user(credentials))["errors"] == {
            "base": "not_seen"
        }
        flow.entry = entry()
        result = await flow.async_step_reconfigure(
            {"auth_key": "bad", "allow_unseen": True}
        )
        assert result["errors"] == {"base": "invalid_credentials"}
        assert flow.entry.data["auth_key"] == AUTH_KEY
        replacement = base64.b64encode(bytes(reversed(range(16)))).decode()
        assert (await flow.async_step_reconfigure({"auth_key": replacement}))[
            "errors"
        ] == {"base": "not_seen"}
        assert flow.entry.data["auth_key"] == AUTH_KEY
        result = await flow.async_step_reconfigure(
            {"auth_key": replacement, "allow_unseen": True}
        )
        assert result["type"] == "abort"
        assert flow.entry.data["auth_key"] == replacement
        assert flow.entry.unique_id == TILE_A
        assert "async_get_options_flow" not in type(flow).__dict__

    asyncio.run(run())


def test_entities_follow_ha_unavailability_and_keep_historical_diagnostics(component):
    async def run():
        coordinator = component.manager.TileCoordinator(SimpleNamespace())
        add_tile(coordinator, Tile(TILE_A, AUTH_KEY))
        tile_entry = entry()
        tile_entry.runtime_data = component.integration.TileRuntimeData(
            coordinator, coordinator.tiles[TILE_A]
        )
        tracker = component.tracker.TileTracker(tile_entry)
        sensors = {
            d.key: component.sensor.TileSensor(tile_entry, d)
            for d in component.sensor.SENSORS
        }
        entities = [tracker, *sensors.values()]
        for entity in entities:
            entity.cancellations = []
            entity.async_write_ha_state = Mock()
            await entity.async_added_to_hass()
            assert entity._attr_device_info["identifiers"] == {(DOMAIN, TILE_A)}
        assert tracker.available and not tracker.is_connected
        assert all(not sensor.available for sensor in sensors.values())
        observe(component, coordinator, 100, service_info(PRIVATE_A, rssi=-127))
        assert tracker.is_connected
        assert sensors["rssi"].native_value == -127 and sensors["rssi"].available
        assert sensors["feed_version"].native_value == 2
        assert sensors["feed_flags"].native_value == 0
        assert not sensors["estimated_distance"].available
        assert not sensors["tx_power"].available
        assert not sensors["estimated_broadcast_interval"].available
        component.bluetooth.async_get_learned_advertising_interval.return_value = 8
        newest = service_info(
            PRIVATE_A,
            time=110,
            version=2,
            advertisement=SimpleNamespace(tx_power=-7),
        )
        observe(component, coordinator, 110, newest)
        assert sensors["estimated_distance"].native_value == 1.5
        component.sensor.calculate_distance_meters.assert_called_with(-70, -85)
        assert sensors["estimated_broadcast_interval"].native_value == 8
        assert tracker.extra_state_attributes["current_address"] == newest.address
        assert tracker.extra_state_attributes["source"] == newest.source
        assert "timeout_seconds" not in tracker.extra_state_attributes
        assert "min_rssi" not in tracker.extra_state_attributes
        component.bluetooth.async_scanner_count.return_value = 0
        unavailable(component, newest)
        assert tracker.available and not tracker.is_connected
        assert not sensors["rssi"].available
        for entity in entities:
            assert entity.async_write_ha_state.call_count == 3
            entity.cancellations[0]()
        assert not coordinator.tiles[TILE_A].listeners

    asyncio.run(run())


def test_real_library_matches_multiple_tiles_and_returns_metadata(component):
    async def run():
        hass = hass_stub()
        first_entry, second_entry = entry(), entry(TILE_B)
        await component.integration.async_setup_entry(hass, first_entry)
        await component.integration.async_setup_entry(hass, second_entry)
        coordinator = hass.data[DOMAIN]
        assert first_entry.runtime_data.coordinator is coordinator
        assert second_entry.runtime_data.coordinator is coordinator
        assert first_entry.runtime_data.state is coordinator.tiles[TILE_A]
        assert second_entry.runtime_data.state is coordinator.tiles[TILE_B]
        first = service_info(
            PRIVATE_A_NEXT,
            service_data={
                component.manager.FEED_UUID.upper(): b"\x02\xff"
                + PRIVATE_A_NEXT
            },
            address="A",
        )
        second = service_info(PRIVATE_B, address="B")
        observe(component, coordinator, 100, first, second)
        a, b = coordinator.tiles[TILE_A], coordinator.tiles[TILE_B]
        assert a.present and b.present
        assert (a.last_counter, a.feed_version, a.feed_flags) == (256, 2, 255)
        assert b.last_counter == 8639
        await component.integration.async_unload_entry(hass, first_entry)
        observe(component, coordinator, 100, first)
        assert TILE_A not in coordinator.tiles and b.present

    asyncio.run(run())


def test_rotation_and_availability_follow_ha_callbacks(component):
    hass = hass_stub()
    coordinator = hass.data[DOMAIN] = component.manager.TileCoordinator(hass)
    state = add_tile(coordinator, Tile(TILE_A, AUTH_KEY))
    resolved, lost = Mock(), Mock()
    cancel_resolved = component.api.async_track_service_info(hass, resolved, TILE_A)
    cancel_lost = component.api.async_track_unavailable(hass, lost, TILE_A)
    first = service_info(PRIVATE_A, address="A")
    observe(component, coordinator, 100, first)
    old_unavailable, cancel_old = (
        component.unavailable_registrations[-1][0],
        component.unavailable_registrations[-1][2],
    )
    cancel_packets = component.advertisement_registrations[-1][2]
    second = service_info(PRIVATE_A_NEXT, time=110, address="B")
    observe(component, coordinator, 110, second)
    cancel_old.assert_called_once()
    cancel_packets.assert_called_once()
    old_unavailable(first)
    assert state.present and state.last_info is second
    assert component.api.async_last_service_info(hass, TILE_A.upper()) is second
    with pytest.raises(ValueError):
        component.api.async_last_service_info(hass, "00")
    assert resolved.call_args_list == [((first,),), ((second,),)]
    lost.assert_not_called()
    unavailable(component, second)
    assert not state.present
    assert component.api.async_last_service_info(hass, TILE_A) is None
    lost.assert_called_once_with(second)
    cancel_resolved()
    cancel_lost()
    assert not state.service_info_listeners and not state.unavailable_listeners


def test_debug_logs_only_counter_and_mac_changes(component, caplog):
    coordinator = component.manager.TileCoordinator(hass_stub())
    state = add_tile(coordinator, Tile(TILE_A, AUTH_KEY))
    listener = Mock()
    state.service_info_listeners.add(listener)
    caplog.set_level(logging.DEBUG, logger=component.manager.__name__)

    observe(component, coordinator, 100, service_info(PRIVATE_A, address="A"))
    observe(
        component, coordinator, 110,
        service_info(PRIVATE_A, time=110, address="A", rssi=-70),
        service_info(PRIVATE_A, time=105, address="stale"),
        service_info(PRIVATE_A, time=120, address="future"),
        service_info(PRIVATE_B, time=110, address="unknown"),
    )
    first_message = (
        f"Tile {TILE_A} resolved advertisement: "
        "address=A source=scanner RSSI=-85 counter=0"
    )
    assert caplog.messages == [first_message]
    assert state.last_info.time == 110
    assert state.last_info.rssi == -70
    assert listener.call_count == 2

    second = service_info(PRIVATE_A_NEXT, time=120, address="B")
    observe(component, coordinator, 120, second)
    unavailable(component, second)
    observe(
        component, coordinator, 130,
        service_info(PRIVATE_A_NEXT, time=130, address="A"),
    )
    assert caplog.messages == [
        first_message,
        f"Tile {TILE_A} MAC address changed from A to B",
        f"Tile {TILE_A} resolved advertisement: "
        "address=B source=scanner RSSI=-85 counter=256",
        f"Tile {TILE_A} MAC address changed from B to A",
    ]
    assert all(record.levelno == logging.DEBUG for record in caplog.records)


def test_setup_unload_and_failed_setup_cleanup(component):
    async def run():
        hass = hass_stub()
        a, b = entry(), entry(TILE_B)
        assert await component.integration.async_setup_entry(hass, a)
        assert await component.integration.async_setup_entry(hass, b)
        coordinator = hass.data[DOMAIN]
        hass.config_entries.async_forward_entry_setups.assert_any_await(
            a, component.integration.PLATFORMS
        )
        component.bluetooth.async_register_callback.assert_called_once()
        cancel_discovery = coordinator._cancel_bluetooth
        observe(component, coordinator, 100, service_info(PRIVATE_A))
        cancel_unavailable = component.unavailable_registrations[-1][2]
        cancel_packets = component.advertisement_registrations[-1][2]
        assert await component.integration.async_unload_entry(hass, a)
        assert TILE_A not in coordinator.tiles and TILE_B in coordinator.tiles
        cancel_unavailable.assert_called_once()
        cancel_packets.assert_called_once()
        cancel_discovery.assert_not_called()
        assert await component.integration.async_unload_entry(hass, b)
        assert DOMAIN not in hass.data
        cancel_discovery.assert_called_once()

        hass.config_entries.async_forward_entry_setups.side_effect = RuntimeError(
            "setup failed"
        )
        with pytest.raises(RuntimeError, match="setup failed"):
            await component.integration.async_setup_entry(hass, a)
        assert DOMAIN not in hass.data
        with pytest.raises(component.integration.ConfigEntryError):
            await component.integration.async_setup_entry(hass, entry(auth_key="bad"))
        assert DOMAIN not in hass.data

    asyncio.run(run())


def test_platforms_and_diagnostics_use_entry_runtime_data(component):
    async def run():
        hass = hass_stub()
        tile_entry = entry()
        trackers, sensors = [], []

        async def forward(entry, platforms):
            # Runtime data must be ready before HA sets up either platform.
            assert entry.runtime_data.state.tile_id == TILE_A
            # Platforms and diagnostics must not look up the shared registry.
            platform_hass = SimpleNamespace(data={})
            await component.tracker.async_setup_entry(
                platform_hass, entry, trackers.extend
            )
            await component.sensor.async_setup_entry(
                platform_hass, entry, sensors.extend
            )

        hass.config_entries.async_forward_entry_setups.side_effect = forward
        assert await component.integration.async_setup_entry(hass, tile_entry)
        assert len(trackers) == 1
        assert len(sensors) == len(component.sensor.SENSORS)
        state = tile_entry.runtime_data.state
        assert all(entity._state is state for entity in [*trackers, *sensors])
        observe(component, hass.data[DOMAIN], 100, service_info(PRIVATE_A))
        diagnostics = component.diagnostics.async_get_config_entry_diagnostics
        assert await diagnostics(SimpleNamespace(data={}), tile_entry) == {
            "identity_resolver": "tile-identity-resolver",
            "loaded": True,
            "present": True,
            "seen": True,
        }
        hass.config_entries.async_unload_platforms.return_value = False
        assert not await component.integration.async_unload_entry(hass, tile_entry)
        assert tile_entry.runtime_data.state is state
        assert (await diagnostics(hass, tile_entry))["loaded"]
        hass.config_entries.async_unload_platforms.return_value = True
        assert await component.integration.async_unload_entry(hass, tile_entry)
        assert not (await diagnostics(hass, tile_entry))["loaded"]
        assert not (await diagnostics(hass, entry()))["loaded"]

    asyncio.run(run())


def test_candidate_generation_runs_in_worker_and_callbacks_run_on_loop(component):
    async def run():
        hass = hass_stub()
        hass.async_add_executor_job.side_effect = asyncio.to_thread
        loop_thread = threading.get_ident()
        resolver_module = importlib.import_module("tile_identity_resolver.resolver")
        generate = resolver_module._generate_private_ids
        worker_threads = []

        def generate_in_worker(tile):
            worker_threads.append(threading.get_ident())
            assert threading.get_ident() != loop_thread
            return generate(tile)

        def register_on_loop(*args):
            assert threading.get_ident() == loop_thread
            return Mock()

        component.bluetooth.async_register_callback.side_effect = register_on_loop
        with patch.object(resolver_module, "_generate_private_ids", generate_in_worker):
            assert await component.integration.async_setup_entry(hass, entry())
        assert worker_threads
        observe(component, hass.data[DOMAIN], 100, service_info(PRIVATE_A))
        assert hass.data[DOMAIN].tiles[TILE_A].present

    asyncio.run(run())


@pytest.mark.parametrize("change", ["add", "remove", "replace"])
def test_resolver_preparation_serializes_concurrent_membership_changes(
    component, change
):
    async def run():
        hass = hass_stub()
        await component.integration.async_setup_entry(hass, entry())
        started, release = asyncio.Event(), asyncio.Event()
        builds = 0

        async def executor(func, *args):
            nonlocal builds
            if func is TileResolver:
                builds += 1
                if builds == 1:
                    started.set()
                    await release.wait()
            return await asyncio.to_thread(func, *args)

        hass.async_add_executor_job.side_effect = executor
        pending = asyncio.create_task(
            component.integration.async_setup_entry(hass, entry(TILE_B))
        )
        await started.wait()
        third_id = "1122334455667788"

        async def change_membership():
            if change == "add":
                await component.integration.async_setup_entry(hass, entry(third_id))
            else:
                await component.integration.async_unload_entry(hass, entry())
                if change == "replace":
                    await component.integration.async_setup_entry(hass, entry(third_id))

        changing = asyncio.create_task(change_membership())
        await asyncio.sleep(0)
        assert not changing.done()
        # Observations continue using the active resolver during preparation.
        observe(component, hass.data[DOMAIN], 100, service_info(PRIVATE_A))
        assert hass.data[DOMAIN].tiles[TILE_A].present
        release.set()
        assert await pending
        await changing
        coordinator = hass.data[DOMAIN]
        expected = {TILE_A, TILE_B, third_id} if change == "add" else {TILE_B}
        if change == "replace":
            expected.add(third_id)
        assert set(coordinator.tiles) == expected
        assert {tile.tile_id for tile in coordinator._resolver.tiles} == expected
        assert builds == (1 if change == "remove" else 2)
        observe(component, coordinator, 100, service_info(PRIVATE_B))
        assert coordinator.tiles[TILE_B].present

    asyncio.run(run())


@pytest.mark.parametrize("cancel", [False, True])
def test_failed_or_cancelled_preparation_leaves_loaded_resolver_untouched(
    component, cancel
):
    async def run():
        hass = hass_stub()
        await component.integration.async_setup_entry(hass, entry())
        coordinator = hass.data[DOMAIN]
        resolver = coordinator._resolver
        started = asyncio.Event()

        async def executor(func, *args):
            if func is TileResolver:
                started.set()
                if cancel:
                    await asyncio.Event().wait()
                raise RuntimeError("preparation failed")
            return func(*args)

        hass.async_add_executor_job.side_effect = executor
        pending = asyncio.create_task(
            component.integration.async_setup_entry(hass, entry(TILE_B))
        )
        await started.wait()
        if cancel:
            pending.cancel()
        with pytest.raises(asyncio.CancelledError if cancel else RuntimeError):
            await pending
        assert hass.data[DOMAIN] is coordinator
        assert coordinator._resolver is resolver
        assert set(coordinator.tiles) == {TILE_A}
        observe(component, coordinator, 100, service_info(PRIVATE_A))
        assert coordinator.tiles[TILE_A].present

    asyncio.run(run())
