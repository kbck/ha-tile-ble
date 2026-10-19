"""Track owned Tiles through Home Assistant's shared Bluetooth scanners."""

import asyncio

from homeassistant.const import Platform
from homeassistant.exceptions import ConfigEntryError
from tile_identity_resolver import Tile

from .const import (
    CONF_AUTH_KEY,
    CONF_TILE_ID,
    DOMAIN,
)
from .coordinator import TileCoordinator

PLATFORMS = [Platform.DEVICE_TRACKER, Platform.SENSOR]


async def async_setup_entry(hass, entry):
    """Prepare this Tile off-loop, then register its candidates on the HA loop."""
    try:
        tile = await hass.async_add_executor_job(
            Tile, entry.data[CONF_TILE_ID], entry.data[CONF_AUTH_KEY]
        )
    except (KeyError, ValueError):
        raise ConfigEntryError(
            "Invalid Tile credentials; reconfigure this Tile"
        ) from None

    coordinator = hass.data.get(DOMAIN)
    if coordinator is None:
        coordinator = hass.data[DOMAIN] = TileCoordinator(hass)
    added = False
    try:
        coordinator.add_tile(tile)
        added = True
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except (Exception, asyncio.CancelledError):
        if added:
            coordinator.remove_tile(tile.tile_id)
        if not coordinator.tiles:
            hass.data.pop(DOMAIN, None)
        raise
    return True


async def async_unload_entry(hass, entry):
    """Release the Tile and stop shared subscriptions after the final unload."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    coordinator = hass.data[DOMAIN]
    coordinator.remove_tile(entry.data[CONF_TILE_ID])
    if not coordinator.tiles:
        hass.data.pop(DOMAIN)
    return True
