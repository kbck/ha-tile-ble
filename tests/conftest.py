"""Use HA's test instance and mock only the Bluetooth boundary."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.components import bluetooth
from pytest_homeassistant_custom_component.common import mock_component

from custom_components import tile_ble
from custom_components.tile_ble import api, coordinator


@pytest.fixture(autouse=True)
def component(hass, enable_custom_integrations, monkeypatch):
    """Supply deterministic Bluetooth observations without starting hardware."""
    mock_component(hass, "bluetooth")
    unavailable_addresses = set()
    unavailable_registrations = []
    advertisement_registrations = []

    def track_unavailable(hass, listener, address, *, connectable):
        assert connectable is False
        cancel = Mock()
        unavailable_registrations.append((listener, address, cancel))
        return cancel

    def track_advertisements(hass, listener, address):
        cancel = Mock()
        advertisement_registrations.append((listener, address, cancel))
        return cancel

    mocks = {
        "async_discovered_service_info": Mock(return_value=[]),
        "async_scanner_count": Mock(return_value=1),
        "async_register_callback": Mock(side_effect=lambda *args: Mock()),
        "MONOTONIC_TIME": Mock(return_value=100.0),
        "async_address_present": Mock(
            side_effect=lambda hass, address, connectable: (
                address not in unavailable_addresses
            )
        ),
        "async_get_fallback_availability_interval": Mock(return_value=None),
        "async_set_fallback_availability_interval": Mock(),
        "async_track_unavailable": Mock(side_effect=track_unavailable),
        "async_register_advertisement_callback": Mock(side_effect=track_advertisements),
        "async_get_learned_advertising_interval": Mock(return_value=None),
    }
    for name, value in mocks.items():
        monkeypatch.setattr(bluetooth, name, value)
    return SimpleNamespace(
        integration=tile_ble,
        manager=coordinator,
        api=api,
        bluetooth=bluetooth,
        unavailable_addresses=unavailable_addresses,
        unavailable_registrations=unavailable_registrations,
        advertisement_registrations=advertisement_registrations,
    )


@pytest.fixture
def mock_platform_forwarding(hass, monkeypatch):
    """Isolate resolver concurrency tests from platform lifecycle tests."""
    monkeypatch.setattr(hass.config_entries, "async_forward_entry_setups", AsyncMock())
    monkeypatch.setattr(
        hass.config_entries, "async_unload_platforms", AsyncMock(return_value=True)
    )
