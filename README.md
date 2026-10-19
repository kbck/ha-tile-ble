# Tile BLE

Local presence tracking for Tile trackers using Home Assistant's Bluetooth
adapters and proxies. Identity matching comes from
[tile-identity-resolver](https://github.com/kbck/tile-identity-resolver); this
integration manages HA entities, address rotation, and availability.

## Installation

Requires HA Core 2026.10 or newer for the Bluetooth
`async_register_advertisement_callback` API, which delivers repeated advertisements
even when their contents have not changed.
The normal manifest requires `tile-identity-resolver==0.1.0` from PyPI.

### HACS

1. Add `https://github.com/kbck/ha-tile-ble` to HACS custom repositories
   with type **Integration**.
2. Download **Tile BLE** and restart Home Assistant.

For manual installation, put `custom_components/tile_ble` in your HA configuration
directory and restart.

## Configuration

Add **Tile BLE** under **Settings > Devices & services**. Enter a name, eight-byte
Tile Web API ID in hex, and sixteen-byte auth key in hex or padded Base64.
Credential retrieval is not included. These are Tile credentials, not a Bluetooth IRK.

Setup normally requires a matching observation. **Allow setup without seeing the
Tile** skips radio validation; an unseen Tile starts away. Use **Reconfigure** to
replace its key.

## Entities and Presence

Each Tile gets a stable Bluetooth LE tracker reporting home/away across address
rotations. Its `current_address` and `source` attributes expose the latest resolved
address and scanner.

MAC address changes are logged at DEBUG level with the Tile ID and old and new
addresses. The first observation does not log an address change.
Accepted resolved advertisements are also logged at DEBUG level with the Tile
ID, MAC address, scanner source, RSSI, and FEED counter. Auth keys, raw payloads,
and private IDs are omitted.

Optional diagnostic sensors provide RSSI, transmit power, estimated distance,
broadcast interval, private-ID counter, FEED version, and raw flags. Enable them
in entity settings. Distance is approximate and needs usable transmit power.

Every matching observation establishes presence regardless of RSSI. HA Bluetooth
decides when the Tile disappears; this can take several minutes. All scanners
count for presence, including those unable to make connections. Apply RSSI
filters or extra departure delays in automations.

Unsupported, ambiguous, and out-of-order observations do not establish presence.

Keys are stored in config entries and held by the resolver at runtime. Entity
attributes and downloaded diagnostics omit keys and private IDs.

## API for Other Integrations

Import from `custom_components.tile_ble.api`:

- `async_last_service_info(hass, tile_id)`: latest available, unambiguous
  observation, or `None`.
- `async_track_service_info(hass, listener, tile_id)`: subscribe to observations.
- `async_track_unavailable(hass, listener, tile_id)`: subscribe to disappearance,
  ambiguity, or source unload.
- `async_get_coordinator(hass)`: loaded coordinator or `None`.

Callbacks receive one `BluetoothServiceInfoBleak` argument and run on HA's event
loop. Subscriptions return an unsubscribe callable. Subscribe before looking up
the latest observation; registration does not replay data. Register cancellation
with `entry.async_on_unload` and resubscribe after the source entry reloads.

Invalid Tile IDs raise `ValueError`; subscriptions to unknown or unloaded Tiles
raise `KeyError`. Unavailability callbacks receive the last observation and only
fire for a previously present Tile. Listener exceptions are logged.

For connections, resolve the latest observation and pass its address to HA's
`bluetooth.async_ble_device_from_address(..., connectable=True)`. Presence does
not guarantee connection availability. Authentication belongs to the consumer.

## Development

Install the local library first while it is unpublished:

```sh
python -m pip install ../tile-identity-resolver
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m ruff check custom_components tests
```

Tests use the real resolver with HA stubs and dummy credentials. Radio behavior
still needs testing on HA. Protocol scope is documented in the
[resolver documentation](https://github.com/kbck/tile-identity-resolver#protocol-scope).

This integration does not ring Tiles, retrieve credentials, or provide room
positioning. Support for other models, firmware, and counter resets needs
validation. It is unofficial and not affiliated with Tile or Life360.
