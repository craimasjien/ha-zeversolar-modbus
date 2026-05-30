"""Sensor platform for the Zeversolar (Eversolar protocol) integration."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_NAME,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DEFAULT_NAME,
    DOMAIN,
    MANUFACTURER,
    MODEL,
)
from .coordinator import ZeversolarCoordinator

# Keys must match those produced by protocol.decode_runtime().
SENSOR_DESCRIPTIONS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="power",
        name="Current Power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    SensorEntityDescription(
        key="energy_today",
        name="Energy Today",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    SensorEntityDescription(
        key="energy_total",
        name="Energy Total",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    ),
    SensorEntityDescription(
        key="pv_voltage",
        name="PV Voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        entity_registry_enabled_default=False,
    ),
    SensorEntityDescription(
        key="ac_voltage",
        name="AC Voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        entity_registry_enabled_default=False,
    ),
    SensorEntityDescription(
        key="ac_current",
        name="AC Current",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        entity_registry_enabled_default=False,
    ),
    SensorEntityDescription(
        key="pv_current",
        name="PV Current",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        entity_registry_enabled_default=False,
    ),
    SensorEntityDescription(
        key="ac_frequency",
        name="AC Frequency",
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        entity_registry_enabled_default=False,
    ),
    SensorEntityDescription(
        key="temperature",
        name="Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_registry_enabled_default=False,
    ),
    SensorEntityDescription(
        key="operating_hours",
        name="Operating Hours",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfTime.HOURS,
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Zeversolar sensors from a config entry."""
    coordinator: ZeversolarCoordinator = entry.runtime_data
    name = {**entry.data, **entry.options}.get(CONF_NAME, DEFAULT_NAME)
    async_add_entities(
        ZeversolarSensor(coordinator, description, name, entry.entry_id)
        for description in SENSOR_DESCRIPTIONS
    )


class ZeversolarSensor(CoordinatorEntity[ZeversolarCoordinator], SensorEntity):
    """A single decoded value exposed as a Home Assistant sensor."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ZeversolarCoordinator,
        description: SensorEntityDescription,
        name: str,
        base_id: str,
    ) -> None:
        """Initialise the sensor entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{DOMAIN}_{base_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, base_id)},
            name=name,
            manufacturer=MANUFACTURER,
            model=MODEL,
            serial_number=coordinator.client.serial,
        )

    @property
    def native_value(self) -> float | None:
        """Return the latest decoded value for this sensor's key."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(self.entity_description.key)

    @property
    def available(self) -> bool:
        """Available only when the last poll succeeded and produced our key."""
        return (
            super().available
            and bool(self.coordinator.data)
            and self.entity_description.key in self.coordinator.data
        )
