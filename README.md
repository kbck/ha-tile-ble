# Tile BLE

Local presence tracking for Tile trackers using Home Assistant's Bluetooth
adapters and proxies. Identity matching comes from
[tile-identity-resolver](https://github.com/kbck/tile-identity-resolver); this
integration manages HA entities, address rotation, and availability.

## Installation

Requires HA Core 2026.10 or newer.

### HACS

1. Add `https://github.com/kbck/ha-tile-ble` to HACS custom repositories
   with type **Integration**.
2. Download **Tile BLE** and restart Home Assistant.

For manual installation, put `custom_components/tile_ble` in your HA configuration
directory and restart.

## Configuration

Add **Tile BLE** under **Settings > Devices & services**. Enter a name, eight-byte
Tile Web API ID in hex, and sixteen-byte auth key in hex or padded Base64.
Credential retrieval is not included.

Setup normally requires a matching observation. **Allow setup without seeing the
Tile** skips radio validation; an unseen Tile starts away. Use **Reconfigure** to
replace its key.

## Entities and Presence

Each Tile gets a stable Bluetooth LE tracker reporting home/away across address
rotations. Its `current_address` and `source` attributes expose the latest resolved
address and scanner.

Optional diagnostic sensors provide RSSI, transmit power, estimated distance,
broadcast interval, private-ID counter, FEED version, and raw flags. Enable them
in entity settings. Distance is approximate and needs usable transmit power.

Every matching observation establishes presence regardless of RSSI. HA Bluetooth
decides when the Tile disappears; this can take several minutes. All scanners
count for presence, including those unable to make connections. Apply RSSI
filters or extra departure delays in automations.

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

Install the dependencies first:

```sh
python -m pip install -r requirements-dev.txt
bash scripts/test.sh
```

This runs tests with branch coverage and Ruff. Use `bash scripts/test.sh tests`
for tests only, or `bash scripts/test.sh tests -k config` to select tests.
Run `bash scripts/hassfest.sh` for hassfest (requires Docker), or
`bash scripts/test.sh all` for all checks. The scripts use your active virtual
environment, falling back to `.venv`, `venv`, or `python3`; set `PYTHON` to
select another interpreter. Run `bash scripts/test.sh --help` for options.

Tests use the real resolver with HA stubs and dummy credentials. Radio behavior
still needs testing on HA. Protocol scope is documented in the
[resolver documentation](https://github.com/kbck/tile-identity-resolver#protocol-scope).

This integration does not ring Tiles, retrieve credentials, or provide room
positioning. Support for other models, firmware, and counter resets needs
validation. It is unofficial and not affiliated with Tile or Life360.
