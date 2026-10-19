"""Diagnostics for the latest resolved Tile advertisement."""

from collections.abc import Callable
from dataclasses import dataclass

from bluetooth_data_tools import calculate_distance_meters
from homeassistant.components import bluetooth
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfLength,
    UnitOfTime,
)

from .const import DOMAIN
from .entity import TileEntity


def estimated_distance(state):
    """Use the same approximate model as HA's Private BLE integration."""
    advertisement = state.last_info.advertisement
    power = advertisement.tx_power
    if power is None or power <= -127:
        return None
    return calculate_distance_meters(power * 10, state.last_info.rssi)


def transmit_power(state):
    """Return transmit power when the adapter supplied a real value."""
    power = state.last_info.advertisement.tx_power
    return None if power is None or power <= -127 else power


def broadcast_interval(coordinator, state):
    """Report HA's learned interval for the current address, when available."""
    return bluetooth.async_get_learned_advertising_interval(
        coordinator.hass, state.last_info.address
    )


@dataclass(frozen=True, kw_only=True)
class TileSensorDescription(SensorEntityDescription):
    entity_category: EntityCategory = EntityCategory.DIAGNOSTIC
    entity_registry_enabled_default: bool = False
    value_fn: Callable


SENSORS = (
    TileSensorDescription(
        key="rssi",
        name="Signal strength",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda coordinator, state: state.last_info.rssi,
    ),
    TileSensorDescription(
        key="tx_power",
        name="Transmit power",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda coordinator, state: transmit_power(state),
    ),
    TileSensorDescription(
        key="estimated_distance",
        name="Estimated distance",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.METERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda coordinator, state: estimated_distance(state),
    ),
    TileSensorDescription(
        key="estimated_broadcast_interval",
        name="Estimated broadcast interval",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_display_precision=1,
        value_fn=broadcast_interval,
    ),
    TileSensorDescription(
        key="last_counter",
        name="Private ID counter",
        value_fn=lambda coordinator, state: state.last_counter,
    ),
    TileSensorDescription(
        key="feed_version",
        name="FEED version",
        value_fn=lambda coordinator, state: state.feed_version,
    ),
    TileSensorDescription(
        key="feed_flags",
        name="FEED flags",
        value_fn=lambda coordinator, state: state.feed_flags,
    ),
)


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        TileSensor(hass.data[DOMAIN], entry, description) for description in SENSORS
    )


class TileSensor(TileEntity, SensorEntity):
    """Expose diagnostics without exposing private IDs or auth keys."""

    def __init__(self, coordinator, entry, description):
        self.entity_description = description
        super().__init__(coordinator, entry, description.key)

    @property
    def available(self):
        state = self._state
        if state.last_info is None:
            return False
        if self.entity_description.key == "last_counter":
            return True
        return state.present and self.native_value is not None

    @property
    def native_value(self):
        if self._state.last_info is None:
            return None
        return self.entity_description.value_fn(self._coordinator, self._state)
