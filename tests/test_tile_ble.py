"""Resolver, subscription, and concurrency tests using real HA interfaces."""

import asyncio
import importlib
import logging
import threading
from unittest.mock import Mock, patch

import pytest
from tile_identity_resolver import Tile, TileResolver

from .common import (
    AUTH_KEY,
    DOMAIN,
    PRIVATE_A,
    PRIVATE_A_NEXT,
    PRIVATE_B,
    TILE_A,
    TILE_B,
    add_tile,
    entry,
    observe,
    service_info,
    unavailable,
)


async def test_real_library_matches_multiple_tiles_and_returns_metadata(
    component, hass, mock_platform_forwarding
):
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
            component.manager.FEED_UUID.upper(): b"\x02\xff" + PRIVATE_A_NEXT
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


async def test_rotation_and_availability_follow_ha_callbacks(component, hass):
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


async def test_debug_logs_only_counter_and_mac_changes(component, caplog, hass):
    coordinator = component.manager.TileCoordinator(hass)
    state = add_tile(coordinator, Tile(TILE_A, AUTH_KEY))
    listener = Mock()
    state.service_info_listeners.add(listener)
    caplog.set_level(logging.DEBUG, logger=component.manager.__name__)

    observe(component, coordinator, 100, service_info(PRIVATE_A, address="A"))
    observe(
        component,
        coordinator,
        110,
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
        component,
        coordinator,
        130,
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


async def test_candidate_generation_runs_in_worker_and_callbacks_run_on_loop(
    component, hass, mock_platform_forwarding
):
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


@pytest.mark.parametrize("change", ["add", "remove", "replace"])
async def test_resolver_preparation_serializes_concurrent_membership_changes(
    component, change, hass, monkeypatch, mock_platform_forwarding
):
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

    monkeypatch.setattr(hass, "async_add_executor_job", executor)
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


@pytest.mark.parametrize("cancel", [False, True])
async def test_failed_or_cancelled_preparation_leaves_loaded_resolver_untouched(
    component, cancel, hass, monkeypatch, mock_platform_forwarding
):
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

    monkeypatch.setattr(hass, "async_add_executor_job", executor)
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
