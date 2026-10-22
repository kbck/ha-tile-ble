"""Exercise configuration through HA's real flow manager."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from .common import AUTH_KEY, DOMAIN, PRIVATE_A, TILE_A, entry, service_info

CREDENTIALS = {"name": " Keys ", "tile_id": TILE_A.upper(), "auth_key": AUTH_KEY}


@pytest.fixture(autouse=True)
def mock_entry_setup():
    """Flow tests exercise validation and persistence, not platform setup."""
    with patch(
        "custom_components.tile_ble.async_setup_entry", new=AsyncMock(return_value=True)
    ):
        yield


async def start_user_flow(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert not result["errors"]
    return result


@pytest.mark.parametrize("key", [AUTH_KEY, bytes(range(16)).hex()])
async def test_user_flow(hass, component, key):
    component.bluetooth.async_discovered_service_info.return_value = [
        service_info(PRIVATE_A)
    ]
    result = await start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**CREDENTIALS, "auth_key": key}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Keys"
    assert result["data"] == {"tile_id": TILE_A, "auth_key": key}
    assert result["result"].unique_id == TILE_A
    await hass.async_block_till_done()


@pytest.mark.parametrize(
    "error", ["invalid_name", "invalid_credentials", "no_scanners", "not_seen"]
)
async def test_user_flow_error_recovery(hass, component, error):
    result = await start_user_flow(hass)
    invalid = dict(CREDENTIALS)
    if error == "invalid_name":
        invalid["name"] = "   "
    elif error == "invalid_credentials":
        invalid["tile_id"] = "not hex"
    elif error == "no_scanners":
        component.bluetooth.async_scanner_count.return_value = 0
    result = await hass.config_entries.flow.async_configure(result["flow_id"], invalid)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"name" if error == "invalid_name" else "base": error}
    component.bluetooth.async_scanner_count.return_value = 1
    component.bluetooth.async_discovered_service_info.return_value = [
        service_info(PRIVATE_A)
    ]
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], CREDENTIALS
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == TILE_A
    assert result["data"] == {"tile_id": TILE_A, "auth_key": AUTH_KEY}
    await hass.async_block_till_done()


async def test_user_flow_allow_unseen(hass, component):
    component.bluetooth.async_scanner_count.return_value = 0
    result = await start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**CREDENTIALS, "allow_unseen": True}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == TILE_A
    component.bluetooth.async_discovered_service_info.assert_not_called()
    await hass.async_block_till_done()


async def test_user_flow_duplicate(hass):
    tile_entry = entry()
    tile_entry.add_to_hass(hass)
    result = await start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**CREDENTIALS, "allow_unseen": True}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


@pytest.mark.parametrize("error", ["invalid_credentials", "no_scanners", "not_seen"])
async def test_reconfigure_error_recovery(hass, component, error):
    tile_entry = entry()
    tile_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": tile_entry.entry_id,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    assert not result["errors"]
    if error == "no_scanners":
        component.bluetooth.async_scanner_count.return_value = 0
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"auth_key": "bad" if error == "invalid_credentials" else AUTH_KEY},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}
    assert tile_entry.data == {"tile_id": TILE_A, "auth_key": AUTH_KEY}
    component.bluetooth.async_scanner_count.return_value = 1
    component.bluetooth.async_discovered_service_info.return_value = [
        service_info(PRIVATE_A)
    ]
    hex_key = bytes(range(16)).hex()
    with patch.object(hass.config_entries, "async_reload", return_value=True) as reload:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"auth_key": hex_key}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert tile_entry.data == {"tile_id": TILE_A, "auth_key": hex_key}
    assert tile_entry.unique_id == TILE_A
    reload.assert_awaited_once_with(tile_entry.entry_id)


async def test_reconfigure_allow_unseen(hass, component):
    tile_entry = entry()
    tile_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": tile_entry.entry_id,
        },
    )
    replacement = bytes(reversed(range(16))).hex()
    with patch.object(hass.config_entries, "async_reload", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"auth_key": replacement, "allow_unseen": True}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert tile_entry.unique_id == TILE_A
    assert tile_entry.data["auth_key"] == replacement
    component.bluetooth.async_discovered_service_info.assert_not_called()
