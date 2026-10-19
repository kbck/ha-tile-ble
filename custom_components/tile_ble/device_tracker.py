"""Expose a Bluetooth LE home/away tracker for each Tile."""

from homeassistant.components.device_tracker import BaseScannerEntity, SourceType

from .const import DOMAIN
from .entity import TileEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([TileTracker(hass.data[DOMAIN], entry)])


class TileTracker(TileEntity, BaseScannerEntity):
    """Track a Tile by resolved identity, rather than Bluetooth address."""

    _attr_name = None
    _attr_source_type = SourceType.BLUETOOTH_LE

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "tracker")

    @property
    def is_connected(self):
        return self._state.present

    @property
    def extra_state_attributes(self):
        info = self._state.last_info
        return {
            "current_address": info.address if info else None,
            "source": info.source if info else None,
        }
