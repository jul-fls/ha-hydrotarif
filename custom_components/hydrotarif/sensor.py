"""Price and metadata sensors for SISPEA."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import Prices
from .const import (
    CONF_COMMUNE,
    CONF_INSEE,
    CONF_LATITUDE,
    CONF_LOCATION_LABEL,
    CONF_LOCATION_SOURCE,
    CONF_LONGITUDE,
    DOMAIN,
)


@dataclass(frozen=True, kw_only=True)
class HydroTarifSensorDescription(SensorEntityDescription):
    """Sensor definition and value extraction."""

    value_fn: Callable[[Prices], str | int | float | date | datetime | None]


SENSORS: tuple[HydroTarifSensorDescription, ...] = (
    HydroTarifSensorDescription(
        key="water_price",
        translation_key="water_price",
        native_unit_of_measurement="€/m³",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.water.value if data.water else None,
    ),
    HydroTarifSensorDescription(
        key="sanitation_price",
        translation_key="sanitation_price",
        native_unit_of_measurement="€/m³",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.sanitation.value if data.sanitation else None,
    ),
    HydroTarifSensorDescription(
        key="total_price",
        translation_key="total_price",
        native_unit_of_measurement="€/m³",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.total,
    ),
    HydroTarifSensorDescription(
        key="water_tariff_date",
        translation_key="water_tariff_date",
        device_class=SensorDeviceClass.DATE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.water.tariff_date if data.water else None,
    ),
    HydroTarifSensorDescription(
        key="sanitation_tariff_date",
        translation_key="sanitation_tariff_date",
        device_class=SensorDeviceClass.DATE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.sanitation.tariff_date if data.sanitation else None,
    ),
    HydroTarifSensorDescription(
        key="last_checked",
        translation_key="last_checked",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.checked_at,
    ),
    HydroTarifSensorDescription(
        key="source_status",
        translation_key="source_status",
        device_class=SensorDeviceClass.ENUM,
        options=["complete", "partial", "no_collective_service", "missing"],
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.status,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create price and metadata sensors."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        HydroTarifSensor(coordinator, entry, description) for description in SENSORS
    )


class HydroTarifSensor(CoordinatorEntity, SensorEntity):
    """A SISPEA sensor for one commune."""

    _attr_has_entity_name = True
    entity_description: HydroTarifSensorDescription

    def __init__(self, coordinator, entry: ConfigEntry, description: HydroTarifSensorDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": f"HydroTarif - {entry.data.get(CONF_LOCATION_LABEL, entry.data[CONF_COMMUNE])}",
            "manufacturer": "SISPEA / OFB",
            "model": "Tarifs communaux",
        }

    @property
    def native_value(self):
        """Return the current value."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self):
        """Expose provenance and relevant source year."""
        data: Prices = self.coordinator.data
        attributes = {
            "commune": self._entry.data[CONF_COMMUNE],
            "code_insee": self._entry.data[CONF_INSEE],
            "location": self._entry.data.get(CONF_LOCATION_LABEL, self._entry.data[CONF_COMMUNE]),
            "location_source": self._entry.data.get(CONF_LOCATION_SOURCE, "insee"),
            "reference_consumption_m3_per_year": 120,
        }
        if CONF_LATITUDE in self._entry.data and CONF_LONGITUDE in self._entry.data:
            attributes[CONF_LATITUDE] = self._entry.data[CONF_LATITUDE]
            attributes[CONF_LONGITUDE] = self._entry.data[CONF_LONGITUDE]
        key = self.entity_description.key
        if key in ("water_price", "total_price") and data.water:
            attributes["water_data_year"] = data.water.year
            attributes["water_source_url"] = data.water.source_url
        if key in ("sanitation_price", "total_price") and data.sanitation:
            attributes["sanitation_data_year"] = data.sanitation.year
            attributes["sanitation_source_url"] = data.sanitation.source_url
        if key == "sanitation_price":
            attributes["no_collective_service"] = data.no_collective_service
        return attributes
