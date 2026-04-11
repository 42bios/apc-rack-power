"""Sensors for APC Rack Power integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import RUNTIME_COORDINATOR
from .const import (
    CONF_PDU_NOMINAL_WATTS,
    CONF_TEMP_SCALE,
    DEFAULT_PDU_NOMINAL_WATTS,
    DEFAULT_TEMP_SCALE,
    DOMAIN,
)
from .coordinator import ApcEnterpriseCoordinator
from .device_profile import detect_device_kind, extract_model_number, is_unavailable


@dataclass(slots=True, frozen=True)
class ApcSensorDef:
    """Entity metadata for one metric."""

    key: str
    translation_key: str
    unit: str | None = None
    device_class: SensorDeviceClass | None = None
    entity_category: EntityCategory | None = None


SENSORS: tuple[ApcSensorDef, ...] = (
    ApcSensorDef("sys_name", "sys_name"),
    ApcSensorDef("sys_descr", "sys_descr", entity_category=EntityCategory.DIAGNOSTIC),
    ApcSensorDef("apc_model_number", "apc_model_number", entity_category=EntityCategory.DIAGNOSTIC),
    ApcSensorDef(
        "sys_uptime_ticks",
        "sys_uptime_ticks",
        device_class=SensorDeviceClass.DURATION,
        unit=UnitOfTime.SECONDS,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    ApcSensorDef("ups_ident_model", "ups_ident_model", entity_category=EntityCategory.DIAGNOSTIC),
    ApcSensorDef("ups_sku", "ups_sku", entity_category=EntityCategory.DIAGNOSTIC),
    ApcSensorDef("ups_ident_name", "ups_ident_name", entity_category=EntityCategory.DIAGNOSTIC),
    ApcSensorDef("ups_battery_status", "ups_battery_status"),
    ApcSensorDef("ups_seconds_on_battery", "ups_seconds_on_battery", unit=UnitOfTime.SECONDS),
    ApcSensorDef("ups_minutes_remaining", "ups_minutes_remaining", unit=UnitOfTime.MINUTES),
    ApcSensorDef("ups_charge_remaining", "ups_charge_remaining", unit=PERCENTAGE),
    ApcSensorDef(
        "ups_battery_voltage",
        "ups_battery_voltage",
        unit=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
    ),
    ApcSensorDef(
        "ups_battery_current",
        "ups_battery_current",
        unit=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
    ),
    ApcSensorDef(
        "ups_battery_temp",
        "ups_battery_temp",
        unit=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
    ),
    ApcSensorDef("ups_input_line_bads", "ups_input_line_bads"),
    ApcSensorDef(
        "ups_input_frequency",
        "ups_input_frequency",
        unit=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
    ),
    ApcSensorDef("ups_input_voltage", "ups_input_voltage", unit=UnitOfElectricPotential.VOLT),
    ApcSensorDef("ups_output_source", "ups_output_source"),
    ApcSensorDef("ups_output_frequency", "ups_output_frequency", unit=UnitOfFrequency.HERTZ),
    ApcSensorDef("ups_output_voltage", "ups_output_voltage", unit=UnitOfElectricPotential.VOLT),
    ApcSensorDef("ups_output_current", "ups_output_current", unit=UnitOfElectricCurrent.AMPERE),
    ApcSensorDef("ups_output_load", "ups_output_load", unit=PERCENTAGE),
    ApcSensorDef("ups_alarms_present", "ups_alarms_present"),
    ApcSensorDef("ups_test_result", "ups_test_result"),
    ApcSensorDef("pdu_device_num_outlets", "pdu_device_num_outlets"),
    ApcSensorDef("pdu_device_load_percent", "pdu_device_load_percent", unit=PERCENTAGE),
    ApcSensorDef("pdu_load_watts", "pdu_load_watts", unit=UnitOfPower.WATT),
    ApcSensorDef("pdu_energy_kwh", "pdu_energy_kwh", unit=UnitOfEnergy.KILO_WATT_HOUR),
    ApcSensorDef("pdu_peak_power_kw", "pdu_peak_power_kw", unit=UnitOfPower.KILO_WATT),
    ApcSensorDef("pdu_phase_voltage", "pdu_phase_voltage", unit=UnitOfElectricPotential.VOLT),
    ApcSensorDef("pdu_phase_current", "pdu_phase_current", unit=UnitOfElectricCurrent.AMPERE),
    ApcSensorDef("pdu_phase_power_kw", "pdu_phase_power_kw", unit=UnitOfPower.KILO_WATT),
    ApcSensorDef("pdu_power_factor", "pdu_power_factor"),
    ApcSensorDef("pdu_peak_current", "pdu_peak_current", unit=UnitOfElectricCurrent.AMPERE),
    ApcSensorDef(
        "pdu_env_temperature",
        "pdu_env_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
    ),
    ApcSensorDef(
        "pdu_env_humidity",
        "pdu_env_humidity",
        unit=PERCENTAGE,
        device_class=SensorDeviceClass.HUMIDITY,
    ),
    ApcSensorDef("pdu_name", "pdu_name", entity_category=EntityCategory.DIAGNOSTIC),
    ApcSensorDef("pdu_location", "pdu_location", entity_category=EntityCategory.DIAGNOSTIC),
    ApcSensorDef("pdu_model_number", "pdu_model_number", entity_category=EntityCategory.DIAGNOSTIC),
    ApcSensorDef("pdu_serial_number", "pdu_serial_number", entity_category=EntityCategory.DIAGNOSTIC),
    ApcSensorDef("pdu_contact", "pdu_contact", entity_category=EntityCategory.DIAGNOSTIC),
    ApcSensorDef("pdu_firmware_rpdu", "pdu_firmware_rpdu", entity_category=EntityCategory.DIAGNOSTIC),
    ApcSensorDef("pdu_firmware_bootmon", "pdu_firmware_bootmon", entity_category=EntityCategory.DIAGNOSTIC),
    ApcSensorDef("pdu_nps_status", "pdu_nps_status", entity_category=EntityCategory.DIAGNOSTIC),
    ApcSensorDef("pdu_bank_count", "pdu_bank_count", entity_category=EntityCategory.DIAGNOSTIC),
)


UPS_KEYS: set[str] = {
    "ups_ident_model",
    "ups_sku",
    "ups_ident_name",
    "ups_battery_status",
    "ups_seconds_on_battery",
    "ups_minutes_remaining",
    "ups_charge_remaining",
    "ups_battery_voltage",
    "ups_battery_current",
    "ups_battery_temp",
    "ups_input_line_bads",
    "ups_input_frequency",
    "ups_input_voltage",
    "ups_output_source",
    "ups_output_frequency",
    "ups_output_voltage",
    "ups_output_current",
    "ups_output_load",
    "ups_alarms_present",
    "ups_test_result",
}

PDU_KEYS: set[str] = {
    "pdu_device_num_outlets",
    "pdu_device_load_percent",
    "pdu_load_watts",
    "pdu_energy_kwh",
    "pdu_peak_power_kw",
    "pdu_phase_voltage",
    "pdu_phase_current",
    "pdu_phase_power_kw",
    "pdu_power_factor",
    "pdu_peak_current",
    "pdu_name",
    "pdu_location",
    "pdu_model_number",
    "pdu_serial_number",
    "pdu_contact",
    "pdu_firmware_rpdu",
    "pdu_firmware_bootmon",
    "pdu_nps_status",
    "pdu_env_temperature",
    "pdu_env_humidity",
    "pdu_bank_count",
}


def _is_temp_probe_present(metrics: dict[str, Any]) -> bool:
    status = metrics.get("pdu_env_temp_status")
    # PowerNet-MIB: notPresent(1), normal(4), aboveHigh(5), ...
    if not isinstance(status, (int, float)):
        return False
    return int(status) != 1


def _is_humidity_probe_present(metrics: dict[str, Any]) -> bool:
    status = metrics.get("pdu_env_humidity_status")
    if not isinstance(status, (int, float)):
        return False
    return int(status) != 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up APC sensors."""
    coordinator: ApcEnterpriseCoordinator = hass.data[DOMAIN][entry.entry_id][RUNTIME_COORDINATOR]
    metrics = coordinator.data.metrics if coordinator.data else {}
    always_include = {"sys_name", "sys_descr", "sys_uptime_ticks"}
    device_kind = detect_device_kind(metrics)

    def _should_include(key: str) -> bool:
        if key in always_include:
            return True
        if key == "apc_model_number":
            return extract_model_number(metrics) is not None
        if device_kind == "pdu" and key in UPS_KEYS:
            return False
        if device_kind == "ups" and key in PDU_KEYS:
            return False
        if key == "pdu_load_watts":
            load_percent = metrics.get("pdu_device_load_percent")
            phase_watts = metrics.get("pdu_phase_active_power_w")
            nominal = int(
                entry.options.get(
                    CONF_PDU_NOMINAL_WATTS,
                    entry.data.get(CONF_PDU_NOMINAL_WATTS, DEFAULT_PDU_NOMINAL_WATTS),
                )
            )
            return (not is_unavailable(load_percent) and nominal > 0) or not is_unavailable(phase_watts)
        if key == "pdu_env_temperature":
            if not _is_temp_probe_present(metrics):
                return False
            return not is_unavailable(metrics.get("pdu_env_temp_c")) or not is_unavailable(
                metrics.get("pdu_env_temp_f")
            )
        if key == "pdu_env_humidity":
            return _is_humidity_probe_present(metrics) and not is_unavailable(metrics.get("pdu_env_humidity"))
        return not is_unavailable(metrics.get(key))

    entities: list[ApcMetricSensor] = [
        ApcMetricSensor(entry, coordinator, sensor_def)
        for sensor_def in SENSORS
        if _should_include(sensor_def.key)
    ]
    included_keys = {sensor_def.key for sensor_def in SENSORS if _should_include(sensor_def.key)}

    registry = er.async_get(hass)
    for sensor_def in SENSORS:
        if sensor_def.key in included_keys:
            continue
        unique_id = f"{entry.entry_id}_{sensor_def.key}"
        entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
        if entity_id:
            registry.async_remove(entity_id)

    for metric in coordinator.custom_metrics:
        if metrics.get(metric.key) is not None:
            entities.append(ApcCustomMetricSensor(entry, coordinator, metric.key))

    entities.append(ApcDiscoverySensor(entry, coordinator))
    async_add_entities(entities)


class ApcBaseSensor(CoordinatorEntity[ApcEnterpriseCoordinator], SensorEntity):
    """Base class for APC sensors."""

    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry, coordinator: ApcEnterpriseCoordinator) -> None:
        super().__init__(coordinator)
        self._entry = entry

    @property
    def device_info(self) -> dict[str, Any]:
        metrics = self.coordinator.data.metrics if self.coordinator.data else {}
        model = (
            metrics.get("ups_sku")
            or metrics.get("pdu_model_number")
            or extract_model_number(metrics)
            or metrics.get("ups_ident_model")
            or metrics.get("sys_descr")
        )
        sw_name = metrics.get("sys_name") or self._entry.title
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": self._entry.title,
            "manufacturer": "APC",
            "model": str(model) if model is not None else None,
            "sw_version": str(sw_name) if sw_name is not None else None,
        }


class ApcMetricSensor(ApcBaseSensor):
    """Sensor backed by one predefined metric key."""

    def __init__(
        self,
        entry: ConfigEntry,
        coordinator: ApcEnterpriseCoordinator,
        metric_def: ApcSensorDef,
    ) -> None:
        super().__init__(entry, coordinator)
        self.entity_description = SensorEntityDescription(
            key=metric_def.key,
            translation_key=metric_def.translation_key,
            native_unit_of_measurement=metric_def.unit,
            device_class=metric_def.device_class,
            entity_category=metric_def.entity_category,
        )
        self._attr_unique_id = f"{entry.entry_id}_{metric_def.key}"

    @property
    def native_value(self) -> Any:
        if not self.coordinator.data:
            return None
        value = self.coordinator.data.metrics.get(self.entity_description.key)
        if self.entity_description.key == "sys_uptime_ticks" and isinstance(value, (int, float)):
            return int(float(value) / 100)
        if self.entity_description.key == "sys_uptime_ticks" and isinstance(value, timedelta):
            return int(value.total_seconds())
        if self.entity_description.key == "apc_model_number":
            return extract_model_number(self.coordinator.data.metrics)
        if self.entity_description.key == "pdu_load_watts":
            metrics = self.coordinator.data.metrics
            load_percent = metrics.get("pdu_device_load_percent")
            nominal_watts = int(
                self._entry.options.get(
                    CONF_PDU_NOMINAL_WATTS,
                    self._entry.data.get(CONF_PDU_NOMINAL_WATTS, DEFAULT_PDU_NOMINAL_WATTS),
                )
            )
            if isinstance(load_percent, (int, float)) and float(load_percent) >= 0 and nominal_watts > 0:
                return round((float(load_percent) / 100.0) * nominal_watts, 1)
            phase_watts = metrics.get("pdu_phase_active_power_w")
            if isinstance(phase_watts, (int, float)) and float(phase_watts) >= 0:
                return float(phase_watts)
            return None
        if self.entity_description.key == "pdu_env_temperature":
            metrics = self.coordinator.data.metrics
            temp_scale = str(
                self._entry.options.get(
                    CONF_TEMP_SCALE,
                    self._entry.data.get(CONF_TEMP_SCALE, DEFAULT_TEMP_SCALE),
                )
            ).lower()
            if temp_scale == "fahrenheit":
                raw = metrics.get("pdu_env_temp_f")
            else:
                raw = metrics.get("pdu_env_temp_c")
            if is_unavailable(raw):
                return None
            return raw
        if self.entity_description.key == "pdu_env_humidity":
            if _is_humidity_probe_present(self.coordinator.data.metrics):
                raw = self.coordinator.data.metrics.get("pdu_env_humidity")
                if is_unavailable(raw):
                    return None
                return raw
            return None
        if is_unavailable(value):
            return None
        return value

    @property
    def native_unit_of_measurement(self) -> str | None:
        if self.entity_description.key != "pdu_env_temperature":
            return super().native_unit_of_measurement
        temp_scale = str(
            self._entry.options.get(
                CONF_TEMP_SCALE,
                self._entry.data.get(CONF_TEMP_SCALE, DEFAULT_TEMP_SCALE),
            )
        ).lower()
        if temp_scale == "fahrenheit":
            return UnitOfTemperature.FAHRENHEIT
        return UnitOfTemperature.CELSIUS


class ApcCustomMetricSensor(ApcBaseSensor):
    """Sensor for user-defined custom OID."""

    def __init__(self, entry: ConfigEntry, coordinator: ApcEnterpriseCoordinator, key: str) -> None:
        super().__init__(entry, coordinator)
        self._key = key
        self._attr_unique_id = f"{entry.entry_id}_custom_{key}"
        self._attr_translation_key = "custom_metric"
        self._attr_name = f"Custom {key}"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> Any:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.metrics.get(self._key)


class ApcDiscoverySensor(ApcBaseSensor):
    """Diagnostic sensor with discovered control overview."""

    def __init__(self, entry: ConfigEntry, coordinator: ApcEnterpriseCoordinator) -> None:
        super().__init__(entry, coordinator)
        self._attr_unique_id = f"{entry.entry_id}_discovery"
        self._attr_translation_key = "discovered_controls"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> Any:
        if not self.coordinator.data:
            return None
        return len(self.coordinator.data.discovered_controls)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        controls = self.coordinator.data.discovered_controls if self.coordinator.data else []
        return {
            "controls": [
                {
                    "uid": control.uid,
                    "table": control.table_key,
                    "name": control.name,
                    "index": control.index,
                    "status_oid": control.status_oid,
                    "control_oid": control.control_oid,
                }
                for control in controls
            ]
        }


