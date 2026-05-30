"""Sensor platform for the Zeversolar (Eversolar protocol) integration."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.components.sensor import (
    PLATFORM_SCHEMA,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.device_info import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_INVERTER_ADDRESS,
    CONF_LOG_RAW_FRAMES,
    CONF_PASSIVE,
    DEFAULT_INVERTER_ADDRESS,
    DEFAULT_NAME,
    DEFAULT_PASSIVE,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MANUFACTURER,
    MODEL,
)
from .coordinator import ZeversolarClient, ZeversolarCoordinator

_LOGGER = logging.getLogger(__name__)

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

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_HOST): cv.string,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_PASSIVE, default=DEFAULT_PASSIVE): cv.boolean,
        vol.Optional(
            CONF_INVERTER_ADDRESS, default=DEFAULT_INVERTER_ADDRESS
        ): vol.All(vol.Coerce(int), vol.Range(min=1, max=254)),
        vol.Optional(CONF_LOG_RAW_FRAMES, default=False): cv.boolean,
        vol.Optional(
            CONF_SCAN_INTERVAL,
            default=cv.time_period(DEFAULT_SCAN_INTERVAL),
        ): cv.time_period,
    }
)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the Zeversolar sensors from YAML configuration."""
    client = ZeversolarClient(
        host=config[CONF_HOST],
        port=config[CONF_PORT],
        inverter_address=config[CONF_INVERTER_ADDRESS],
        log_raw_frames=config[CONF_LOG_RAW_FRAMES],
        passive=config[CONF_PASSIVE],
    )
    coordinator = ZeversolarCoordinator(
        hass, client, int(config[CONF_SCAN_INTERVAL].total_seconds())
    )

    # Prime the coordinator. We do not raise on failure: the inverter is dark at
    # night, so entities should come up "unavailable" and recover on their own.
    await coordinator.async_refresh()

    base_id = f"{config[CONF_HOST]}_{config[CONF_PORT]}"
    async_add_entities(
        ZeversolarSensor(coordinator, description, config[CONF_NAME], base_id)
        for description in SENSOR_DESCRIPTIONS
    )


class ZeversolarSensor(CoordinatorEntity[ZeversolarCoordinator], SensorEntity):
    """A single decoded value exposed as a Home Assistant sensor."""

    _attr_has_entity_name = False

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
        self._attr_name = f"{name} {description.name}"
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
