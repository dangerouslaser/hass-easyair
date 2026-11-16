"""Energy sensors for Bosch EasyAir heat pumps."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import EasyAirConfigEntry
from .const import DOMAIN
from .coordinator import EasyAirCoordinator, UnitData


@dataclass(frozen=True, kw_only=True)
class EasyAirSensorDescription(SensorEntityDescription):
    value_fn: Callable[[UnitData], float | int | str | None]


ENERGY = {
    "device_class": SensorDeviceClass.ENERGY,
    "native_unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
    "suggested_display_precision": 0,
}

SENSORS: tuple[EasyAirSensorDescription, ...] = (
    # Use this one in the Energy dashboard.
    EasyAirSensorDescription(
        key="energy_total",
        translation_key="energy_total",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d: d.total,
        **ENERGY,
    ),
    EasyAirSensorDescription(
        key="energy_this_week",
        translation_key="energy_this_week",
        value_fn=lambda d: d.this_week,
        **ENERGY,
    ),
    EasyAirSensorDescription(
        key="energy_this_month",
        translation_key="energy_this_month",
        value_fn=lambda d: d.this_month,
        **ENERGY,
    ),
    EasyAirSensorDescription(
        key="energy_last_month",
        translation_key="energy_last_month",
        value_fn=lambda d: d.last_month,
        **ENERGY,
    ),
    EasyAirSensorDescription(
        key="energy_this_year",
        translation_key="energy_this_year",
        value_fn=lambda d: d.this_year,
        **ENERGY,
    ),
    EasyAirSensorDescription(
        key="service_status",
        translation_key="service_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.device.get("serviceStatus"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EasyAirConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        EasyAirSensor(coordinator, gw, desc)
        for gw in coordinator.data
        for desc in SENSORS
    )


class EasyAirSensor(CoordinatorEntity[EasyAirCoordinator], SensorEntity):
    _attr_has_entity_name = True
    entity_description: EasyAirSensorDescription

    def __init__(
        self, coordinator: EasyAirCoordinator, gateway_id: str, desc: EasyAirSensorDescription
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = desc
        self._gw = gateway_id
        self._attr_unique_id = f"{gateway_id}_{desc.key}"
        dev = coordinator.data[gateway_id].device
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, gateway_id)},
            manufacturer="Bosch",
            model=dev.get("modelName"),
            name=dev.get("ODUName") or "Bosch heat pump",
            sw_version=dev.get("idsVersion"),
            serial_number=gateway_id,
        )

    @property
    def available(self) -> bool:
        return super().available and self._gw in self.coordinator.data

    @property
    def native_value(self):
        return self.entity_description.value_fn(self.coordinator.data[self._gw])

    @property
    def extra_state_attributes(self):
        if self.entity_description.key == "energy_this_year":
            return {"monthly_kwh": self.coordinator.data[self._gw].monthly}
        return None
