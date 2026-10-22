"""Return status without credentials, addresses, sources, or private IDs."""

from .models import TileConfigEntry


async def async_get_config_entry_diagnostics(hass, entry: TileConfigEntry):
    runtime_data = getattr(entry, "runtime_data", None)
    state = None
    if runtime_data is not None:
        state = runtime_data.coordinator.tiles.get(runtime_data.state.tile_id)
        if state is not runtime_data.state:
            state = None
    return {
        "identity_resolver": "tile-identity-resolver",
        "loaded": state is not None,
        "present": state.present if state else False,
        "seen": state.last_info is not None if state else False,
    }
