"""Return status without credentials, addresses, sources, or private IDs."""

from .const import CONF_TILE_ID, DOMAIN


async def async_get_config_entry_diagnostics(hass, entry):
    coordinator = hass.data.get(DOMAIN)
    state = coordinator.tiles.get(entry.data[CONF_TILE_ID]) if coordinator else None
    return {
        "identity_resolver": "tile-identity-resolver",
        "loaded": state is not None,
        "present": state.present if state else False,
        "seen": state.last_info is not None if state else False,
    }
