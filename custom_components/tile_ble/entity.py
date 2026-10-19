"""Common identity and subscription lifecycle for Tile entities."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import CONF_TILE_ID, DOMAIN


class TileEntity(Entity):
    """Keep device identity stable across private-ID and MAC rotations."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry, key):
        self._coordinator = coordinator
        self._state = coordinator.tiles[entry.data[CONF_TILE_ID]]
        self._attr_unique_id = f"{self._state.tile_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._state.tile_id)},
            manufacturer="Tile",
            name=entry.title,
        )

    @property
    def available(self):
        """Keep the tracker readable as away when HA loses the device."""
        return True

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(
            self._coordinator.subscribe(self._state.tile_id, self.async_write_ha_state)
        )
