"""Manual Tile credentials and validation against HA's available observations."""

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components import bluetooth
from homeassistant.const import CONF_NAME
from homeassistant.helpers import selector
from tile_identity_resolver import Tile, TileResolver

from .const import (
    CONF_ALLOW_UNSEEN,
    CONF_AUTH_KEY,
    CONF_TILE_ID,
    DOMAIN,
)
from .coordinator import latest_matching_info


def credential_schema(include_tile_id=True):
    fields = {}
    if include_tile_id:
        fields[vol.Required(CONF_NAME)] = vol.All(str, vol.Length(min=1, max=100))
        fields[vol.Required(CONF_TILE_ID)] = str
    fields[vol.Required(CONF_AUTH_KEY)] = selector.TextSelector(
        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
    )
    fields[vol.Optional(CONF_ALLOW_UNSEEN, default=False)] = bool
    return vol.Schema(fields)


class TileBLEConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Create one stable config entry for each Tile Web API ID."""

    VERSION = 1

    async def _async_validate_observation(self, tile, user_input):
        if user_input.get(CONF_ALLOW_UNSEEN, False):
            return None
        if not bluetooth.async_scanner_count(self.hass, connectable=False):
            return "no_scanners"
        resolver = await self.hass.async_add_executor_job(TileResolver, [tile])
        if latest_matching_info(self.hass, resolver) is None:
            return "not_seen"
        return None

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                tile = Tile(
                    bytes.fromhex(user_input[CONF_TILE_ID]).hex(),
                    user_input[CONF_AUTH_KEY].strip(),
                )
            except ValueError:
                errors["base"] = "invalid_credentials"
            if not user_input[CONF_NAME].strip():
                errors[CONF_NAME] = "invalid_name"
            if not errors:
                await self.async_set_unique_id(tile.tile_id)
                self._abort_if_unique_id_configured()
                if error := await self._async_validate_observation(tile, user_input):
                    errors["base"] = error
                else:
                    return self.async_create_entry(
                        title=user_input[CONF_NAME].strip(),
                        data={
                            CONF_TILE_ID: tile.tile_id,
                            CONF_AUTH_KEY: tile.auth_key,
                        },
                    )
        return self.async_show_form(
            step_id="user", data_schema=credential_schema(), errors=errors
        )

    async def async_step_reconfigure(self, user_input=None):
        entry = self._get_reconfigure_entry()
        errors = {}
        if user_input is not None:
            try:
                tile = Tile(
                    entry.data[CONF_TILE_ID], user_input[CONF_AUTH_KEY].strip()
                )
            except ValueError:
                errors["base"] = "invalid_credentials"
            if not errors:
                await self.async_set_unique_id(entry.data[CONF_TILE_ID])
                self._abort_if_unique_id_mismatch()
                if error := await self._async_validate_observation(tile, user_input):
                    errors["base"] = error
                else:
                    return self.async_update_reload_and_abort(
                        entry,
                        data_updates={CONF_AUTH_KEY: tile.auth_key},
                    )
        return self.async_show_form(
            step_id="reconfigure", data_schema=credential_schema(False), errors=errors
        )
