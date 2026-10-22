"""Track owned Tiles through Home Assistant's shared Bluetooth scanners."""

import asyncio

from homeassistant.const import Platform
from homeassistant.exceptions import ConfigEntryError
from tile_identity_resolver import Tile

from .const import (
    CONF_AUTH_KEY,
    CONF_TILE_ID,
)
from .coordinator import async_add_tile, async_remove_tile
from .models import TileConfigEntry, TileRuntimeData

PLATFORMS = [Platform.DEVICE_TRACKER, Platform.SENSOR]


async def async_setup_entry(hass, entry: TileConfigEntry):
    """Prepare the resolver off-loop, then register on the HA loop."""
    try:
        tile = await hass.async_add_executor_job(
            Tile, entry.data[CONF_TILE_ID], entry.data[CONF_AUTH_KEY]
        )
    except (KeyError, ValueError):
        raise ConfigEntryError(
            "Invalid Tile credentials; reconfigure this Tile"
        ) from None

    coordinator = await async_add_tile(hass, tile)
    entry.runtime_data = TileRuntimeData(coordinator, coordinator.tiles[tile.tile_id])
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except (Exception, asyncio.CancelledError):
        await async_remove_tile(hass, tile.tile_id)
        raise
    return True


async def async_unload_entry(hass, entry: TileConfigEntry):
    """Release the Tile and stop shared subscriptions after the final unload."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    await async_remove_tile(hass, entry.data[CONF_TILE_ID])
    return True
