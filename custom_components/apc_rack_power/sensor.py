"""Sensors for APC Rack Power."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfApparentPower,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util.unit_conversion import TemperatureConverter

from . import ApcConfigEntry
from .const import (
    APC_BATTERY_STATUS,
    APC_OUTPUT_STATUS,
    APC_TEST_RESULT,
    BATTERY_STATUS_OPTIONS,
    CALIBRATION_RESULT,
    DEVICE_PDU,
    DEVICE_UPS,
    LEGACY_LOAD_STATE,
    LOAD_STATE,
    NPS_TYPE,
    RFC_BATTERY_STATUS,
    RFC_OUTPUT_SOURCE,
    RFC_TEST_RESULT,
    TEST_RESULT_OPTIONS,
    TRANSFER_CAUSE,
)
from .coordinator import ApcCoordinator, ApcSnapshot
from .device_profile import extract_model_number, kind_matches, parse_apc_date
from .entity import ApcEntity, add_entities_when_found

PARALLEL_UPDATES = 0

ValueFn = Callable[[ApcSnapshot], Any]


@dataclass(frozen=True, kw_only=True)
class ApcSensorDescription(SensorEntityDescription):
    """Describes one APC sensor."""

    value_fn: ValueFn
    exists_fn: ValueFn | None = None
    attrs_fn: Callable[[ApcSnapshot], dict[str, Any] | None] | None = None
    kind: str | None = None


def _metric(key: str) -> ValueFn:
    return lambda d: d.metric(key)


def _enum(key: str, mapping: dict[int, str]) -> ValueFn:
    return lambda d: mapping.get(d.metric(key))


def _date(key: str) -> ValueFn:
    return lambda d: parse_apc_date(d.metric(key))


def _first(*fns: ValueFn) -> ValueFn:
    def _value(d: ApcSnapshot) -> Any:
        for fn in fns:
            if (value := fn(d)) is not None:
                return value
        return None

    return _value


def _uptime(d: ApcSnapshot) -> int | None:
    ticks = d.metric("sys_uptime_ticks")
    return int(ticks / 100) if isinstance(ticks, (int, float)) else None


def _efficiency(d: ApcSnapshot) -> float | None:
    raw = d.metric("ups_efficiency_raw")
    return round(raw / 10, 1) if isinstance(raw, (int, float)) and raw >= 0 else None


def _pdu_power(d: ApcSnapshot) -> float | None:
    power = d.metric("pdu_power")
    if power is not None:
        return power
    phases = [row.get("power") for row in d.tables.get("phase_rpdu2", {}).values()]
    phases = [value for value in phases if isinstance(value, (int, float))]
    return sum(phases) if phases else None


def _pdu_load_percent(d: ApcSnapshot) -> float | None:
    power = _pdu_power(d)
    rating = d.metric("pdu_power_rating")
    if isinstance(power, (int, float)) and isinstance(rating, (int, float)) and rating > 0:
        return round(power / rating * 100, 1)
    return None


def _pdu_power_factor(d: ApcSnapshot) -> float | None:
    value = d.metric("pdu_device_power_factor")
    if value is not None:
        return value
    return d.tables.get("phase_rpdu2", {}).get("1", {}).get("power_factor")


def _discovery_attrs(d: ApcSnapshot) -> dict[str, Any]:
    return {"controls": [{"uid": c.uid, "table": c.table_key, "name": c.name, "index": c.index} for c in d.controls]}


def _s(
    key: str,
    value_fn: ValueFn | None = None,
    *,
    kind: str | None = None,
    unit: str | None = None,
    device_class: SensorDeviceClass | None = None,
    state_class: SensorStateClass | None = None,
    category: EntityCategory | None = None,
    enabled: bool = True,
    options: list[str] | None = None,
    translation_key: str | None = None,
    exists_fn: ValueFn | None = None,
    attrs_fn: Callable[[ApcSnapshot], dict[str, Any] | None] | None = None,
    precision: int | None = None,
) -> ApcSensorDescription:
    return ApcSensorDescription(
        key=key,
        translation_key=translation_key or key,
        value_fn=value_fn or _metric(key),
        exists_fn=exists_fn,
        attrs_fn=attrs_fn,
        kind=kind,
        native_unit_of_measurement=unit,
        device_class=device_class,
        state_class=state_class,
        entity_category=category,
        entity_registry_enabled_default=enabled,
        options=options,
        suggested_display_precision=precision,
    )


_MEAS = SensorStateClass.MEASUREMENT
_DIAG = EntityCategory.DIAGNOSTIC
_ENUM = SensorDeviceClass.ENUM

SENSORS: tuple[ApcSensorDescription, ...] = (
    # Network card / system
    _s("sys_name", category=_DIAG),
    _s("sys_descr", category=_DIAG),
    _s("apc_model_number", lambda d: extract_model_number(d.metrics), category=_DIAG),
    _s(
        "sys_uptime_ticks",
        _uptime,
        unit=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        category=_DIAG,
    ),
    # UPS identification
    _s("ups_ident_model", kind=DEVICE_UPS, category=_DIAG),
    _s("ups_sku", kind=DEVICE_UPS, category=_DIAG),
    _s("ups_ident_name", kind=DEVICE_UPS, category=_DIAG),
    # UPS battery
    _s(
        "ups_battery_status",
        _first(_enum("rfc_battery_status", RFC_BATTERY_STATUS), _enum("apc_battery_status", APC_BATTERY_STATUS)),
        kind=DEVICE_UPS,
        device_class=_ENUM,
        options=BATTERY_STATUS_OPTIONS,
    ),
    _s(
        "ups_charge_remaining",
        kind=DEVICE_UPS,
        unit=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=_MEAS,
    ),
    _s(
        "ups_minutes_remaining",
        kind=DEVICE_UPS,
        unit=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=_MEAS,
    ),
    _s(
        "ups_seconds_on_battery",
        kind=DEVICE_UPS,
        unit=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        state_class=_MEAS,
    ),
    _s(
        "ups_battery_voltage",
        kind=DEVICE_UPS,
        unit=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=_MEAS,
    ),
    _s(
        "ups_battery_current",
        kind=DEVICE_UPS,
        unit=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=_MEAS,
    ),
    _s(
        "ups_battery_temp",
        kind=DEVICE_UPS,
        unit=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=_MEAS,
    ),
    _s(
        "ups_battery_last_replaced",
        _date("ups_battery_last_replaced"),
        kind=DEVICE_UPS,
        device_class=SensorDeviceClass.DATE,
    ),
    _s("ups_battery_replace_by", _date("ups_battery_replace_by"), kind=DEVICE_UPS, device_class=SensorDeviceClass.DATE),
    _s("ups_battery_packs", kind=DEVICE_UPS, state_class=_MEAS, category=_DIAG),
    _s("ups_battery_bad_packs", kind=DEVICE_UPS, state_class=_MEAS),
    _s("ups_external_battery_model", kind=DEVICE_UPS, category=_DIAG),
    # UPS input
    _s(
        "ups_input_voltage",
        kind=DEVICE_UPS,
        unit=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=_MEAS,
    ),
    _s(
        "ups_input_frequency",
        kind=DEVICE_UPS,
        unit=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=_MEAS,
    ),
    _s("ups_input_line_bads", kind=DEVICE_UPS, state_class=SensorStateClass.TOTAL_INCREASING),
    _s(
        "ups_last_transfer_cause",
        _enum("ups_last_transfer_cause", TRANSFER_CAUSE),
        kind=DEVICE_UPS,
        device_class=_ENUM,
        options=list(TRANSFER_CAUSE.values()),
    ),
    # UPS output
    _s(
        "ups_output_source",
        _enum("rfc_output_source", RFC_OUTPUT_SOURCE),
        kind=DEVICE_UPS,
        device_class=_ENUM,
        options=list(RFC_OUTPUT_SOURCE.values()),
    ),
    _s(
        "ups_output_status",
        _enum("apc_output_status", APC_OUTPUT_STATUS),
        kind=DEVICE_UPS,
        device_class=_ENUM,
        options=list(APC_OUTPUT_STATUS.values()),
    ),
    _s(
        "ups_output_voltage",
        kind=DEVICE_UPS,
        unit=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=_MEAS,
    ),
    _s(
        "ups_output_frequency",
        kind=DEVICE_UPS,
        unit=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=_MEAS,
    ),
    _s(
        "ups_output_current",
        kind=DEVICE_UPS,
        unit=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=_MEAS,
    ),
    _s("ups_output_load", kind=DEVICE_UPS, unit=PERCENTAGE, state_class=_MEAS),
    _s(
        "ups_output_power",
        kind=DEVICE_UPS,
        unit=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=_MEAS,
    ),
    _s(
        "ups_output_apparent_power",
        kind=DEVICE_UPS,
        unit=UnitOfApparentPower.VOLT_AMPERE,
        device_class=SensorDeviceClass.APPARENT_POWER,
        state_class=_MEAS,
    ),
    _s(
        "ups_output_energy",
        kind=DEVICE_UPS,
        unit=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    _s(
        "ups_efficiency",
        _efficiency,
        kind=DEVICE_UPS,
        unit=PERCENTAGE,
        state_class=_MEAS,
        enabled=False,
        exists_fn=lambda d: d.metrics.get("ups_efficiency_raw") is not None,
    ),
    # UPS alarms and tests
    _s("ups_alarms_present", kind=DEVICE_UPS, state_class=_MEAS),
    _s(
        "ups_test_result",
        _first(_enum("rfc_test_result", RFC_TEST_RESULT), _enum("apc_test_result", APC_TEST_RESULT)),
        kind=DEVICE_UPS,
        device_class=_ENUM,
        options=TEST_RESULT_OPTIONS,
    ),
    _s("ups_last_self_test", _date("ups_last_self_test"), kind=DEVICE_UPS, device_class=SensorDeviceClass.DATE),
    _s(
        "ups_calibration_result",
        _enum("ups_calibration_result", CALIBRATION_RESULT),
        kind=DEVICE_UPS,
        device_class=_ENUM,
        options=list(CALIBRATION_RESULT.values()),
        category=_DIAG,
    ),
    _s(
        "ups_last_calibration",
        _date("ups_last_calibration"),
        kind=DEVICE_UPS,
        device_class=SensorDeviceClass.DATE,
        category=_DIAG,
    ),
    # Rack PDU
    _s("pdu_device_num_outlets", kind=DEVICE_PDU, category=_DIAG),
    _s(
        "pdu_load_watts",
        _pdu_power,
        kind=DEVICE_PDU,
        unit=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=_MEAS,
    ),
    _s(
        "pdu_apparent_power",
        kind=DEVICE_PDU,
        unit=UnitOfApparentPower.VOLT_AMPERE,
        device_class=SensorDeviceClass.APPARENT_POWER,
        state_class=_MEAS,
    ),
    _s(
        "pdu_device_load_percent",
        _pdu_load_percent,
        kind=DEVICE_PDU,
        unit=PERCENTAGE,
        state_class=_MEAS,
        attrs_fn=lambda d: {"power_rating_w": d.metric("pdu_power_rating")},
    ),
    _s(
        "pdu_load_state",
        _enum("pdu_load_state", LOAD_STATE),
        kind=DEVICE_PDU,
        device_class=_ENUM,
        options=list(LOAD_STATE.values()),
    ),
    _s(
        "pdu_energy_kwh",
        kind=DEVICE_PDU,
        unit=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    _s(
        "pdu_peak_power_kw",
        kind=DEVICE_PDU,
        unit=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        category=_DIAG,
    ),
    _s(
        "pdu_power_factor",
        _pdu_power_factor,
        kind=DEVICE_PDU,
        device_class=SensorDeviceClass.POWER_FACTOR,
        state_class=_MEAS,
    ),
    _s("pdu_name", kind=DEVICE_PDU, category=_DIAG),
    _s("pdu_location", kind=DEVICE_PDU, category=_DIAG),
    _s("pdu_contact", kind=DEVICE_PDU, category=_DIAG),
    _s("pdu_model_number", kind=DEVICE_PDU, category=_DIAG),
    _s("pdu_serial_number", kind=DEVICE_PDU, category=_DIAG),
    _s("pdu_firmware_rpdu", kind=DEVICE_PDU, category=_DIAG),
    _s("pdu_firmware_bootmon", kind=DEVICE_PDU, category=_DIAG),
    _s("pdu_bank_count", kind=DEVICE_PDU, category=_DIAG),
    _s(
        "pdu_nps_status",
        _enum("pdu_nps_type", NPS_TYPE),
        kind=DEVICE_PDU,
        device_class=_ENUM,
        options=list(NPS_TYPE.values()),
        category=_DIAG,
    ),
    # Discovery overview
    _s(
        "discovery",
        lambda d: len(d.controls),
        translation_key="discovered_controls",
        category=_DIAG,
        attrs_fn=_discovery_attrs,
        exists_fn=lambda d: True,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ApcConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up APC sensors."""
    coordinator = entry.runtime_data

    def _build(d: ApcSnapshot) -> Iterator[tuple[str, Callable[[], Entity]]]:
        for description in SENSORS:
            if not kind_matches(d.device_kind, description.kind):
                continue
            exists = description.exists_fn or description.value_fn
            if exists(d) is None or exists(d) is False:
                continue
            yield description.key, lambda description=description: ApcSensor(coordinator, description)
        for metric in coordinator.custom_metrics:
            if d.metrics.get(metric.key) is not None:
                yield metric.key, lambda key=metric.key: ApcCustomMetricSensor(coordinator, key)
        for description, placeholders in _dynamic_descriptions(d):
            yield (
                description.key,
                lambda description=description, placeholders=placeholders: ApcSensor(
                    coordinator, description, placeholders
                ),
            )

    add_entities_when_found(coordinator, async_add_entities, _build)


# ------------------------------------------------------------ dynamic sensors


def _cell(table: str, index: str, column: str) -> ValueFn:
    return lambda d: d.tables.get(table, {}).get(index, {}).get(column)


def _cell_enum(table: str, index: str, column: str, mapping: dict[int, str]) -> ValueFn:
    return lambda d: mapping.get(d.tables.get(table, {}).get(index, {}).get(column))


def _threshold_attrs(
    table: str, index: str, cfg_table: str | None = None, cfg_index: str | None = None
) -> Callable[[ApcSnapshot], dict[str, Any]]:
    def _attrs(d: ApcSnapshot) -> dict[str, Any]:
        row = d.tables.get(cfg_table or table, {}).get(cfg_index or index, {})
        return {
            name: row.get(name)
            for name in ("low_load_threshold", "near_overload_threshold", "overload_threshold")
            if row.get(name) is not None
        }

    return _attrs


def _current(
    key: str, translation_key: str, value_fn: ValueFn, attrs_fn: Callable[[ApcSnapshot], dict[str, Any]] | None = None
) -> ApcSensorDescription:
    return _s(
        key,
        value_fn,
        translation_key=translation_key,
        unit=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=_MEAS,
        attrs_fn=attrs_fn,
        exists_fn=lambda d: True,
    )


def _load_state(
    key: str, translation_key: str, value_fn: ValueFn, mapping: dict[int, str] = LOAD_STATE
) -> ApcSensorDescription:
    return _s(
        key,
        value_fn,
        translation_key=translation_key,
        device_class=_ENUM,
        options=list(mapping.values()),
        exists_fn=lambda d: True,
    )


def _phase_sensors(d: ApcSnapshot) -> Iterator[tuple[ApcSensorDescription, dict[str, str]]]:
    rows = d.tables.get("phase_rpdu2", {})
    multi = len(rows) > 1
    for index in rows:
        legacy = index == "1"
        names = {"phase": index}
        prefix = "pdu_phase" if legacy else f"pdu_phase_{index}"
        cur_key = "pdu_phase_current" if legacy else f"{prefix}_current"
        yield (
            _current(
                cur_key,
                "phase_current" if multi else "pdu_phase_current",
                _cell("phase_rpdu2", index, "current"),
                _threshold_attrs("phase_rpdu2", index),
            ),
            names,
        )
        yield (
            _s(
                "pdu_phase_voltage" if legacy else f"{prefix}_voltage",
                _cell("phase_rpdu2", index, "voltage"),
                translation_key="phase_voltage" if multi else "pdu_phase_voltage",
                unit=UnitOfElectricPotential.VOLT,
                device_class=SensorDeviceClass.VOLTAGE,
                state_class=_MEAS,
                exists_fn=lambda d: True,
            ),
            names,
        )
        yield (
            _s(
                "pdu_phase_power_kw" if legacy else f"{prefix}_power",
                (lambda d, index=index: _w_to_kw(_cell("phase_rpdu2", index, "power")(d)))
                if legacy
                else _cell("phase_rpdu2", index, "power"),
                translation_key="phase_power" if multi else "pdu_phase_power_kw",
                unit=UnitOfPower.KILO_WATT if legacy else UnitOfPower.WATT,
                device_class=SensorDeviceClass.POWER,
                state_class=_MEAS,
                exists_fn=lambda d: True,
            ),
            names,
        )
        yield (
            _s(
                "pdu_peak_current" if legacy else f"{prefix}_peak_current",
                _cell("phase_rpdu2", index, "peak_current"),
                translation_key="phase_peak_current" if multi else "pdu_peak_current",
                unit=UnitOfElectricCurrent.AMPERE,
                device_class=SensorDeviceClass.CURRENT,
                category=_DIAG,
                exists_fn=lambda d: True,
            ),
            names,
        )
        yield (
            _load_state(
                f"{prefix}_load_state",
                "phase_load_state" if multi else "pdu_phase_load_state",
                _cell_enum("phase_rpdu2", index, "load_state", LOAD_STATE),
            ),
            names,
        )


def _w_to_kw(value: Any) -> float | None:
    return round(value / 1000, 2) if isinstance(value, (int, float)) else None


def _bank_sensors(d: ApcSnapshot) -> Iterator[tuple[ApcSensorDescription, dict[str, str]]]:
    for index, row in d.tables.get("bank_rpdu2", {}).items():
        number = str(row.get("number") or index)
        names = {"bank": number}
        yield (
            _current(
                f"pdu_bank_{index}_current",
                "bank_current",
                _cell("bank_rpdu2", index, "current"),
                _threshold_attrs("bank_rpdu2", index),
            ),
            names,
        )
        yield (
            _load_state(
                f"pdu_bank_{index}_load_state",
                "bank_load_state",
                _cell_enum("bank_rpdu2", index, "load_state", LOAD_STATE),
            ),
            names,
        )


def _legacy_load_sensors(d: ApcSnapshot) -> Iterator[tuple[ApcSensorDescription, dict[str, str]]]:
    rows = d.tables.get("load_rpdu", {})
    phases = [index for index, row in rows.items() if not row.get("bank")]
    for index, row in rows.items():
        bank = row.get("bank")
        if bank:
            names = {"bank": str(bank)}
            key, tkey, skey = f"pdu_bank_{bank}_current", "bank_current", "bank_load_state"
            state_key, attrs = f"pdu_bank_{bank}_load_state", None
        else:
            phase = str(row.get("phase") or index)
            names = {"phase": phase}
            legacy = phase == "1"
            multi = len(phases) > 1
            key = "pdu_phase_current" if legacy else f"pdu_phase_{phase}_current"
            tkey = "phase_current" if multi else "pdu_phase_current"
            skey = "phase_load_state" if multi else "pdu_phase_load_state"
            state_key = "pdu_phase_load_state" if legacy else f"pdu_phase_{phase}_load_state"
            attrs = _threshold_attrs("load_rpdu", index, "load_rpdu_cfg", phase)
        yield _current(key, tkey, _cell("load_rpdu", index, "current"), attrs), names
        yield (
            _load_state(
                state_key,
                skey,
                _cell_enum("load_rpdu", index, "legacy_load_state", LEGACY_LOAD_STATE),
                LEGACY_LOAD_STATE,
            ),
            names,
        )


def _metered_outlet_sensors(d: ApcSnapshot) -> Iterator[tuple[ApcSensorDescription, dict[str, str]]]:
    for index, row in d.tables.get("outlet_metered_rpdu2", {}).items():
        names = {"outlet": str(row.get("name") or index)}
        yield (
            _s(
                f"pdu_outlet_{index}_power",
                _cell("outlet_metered_rpdu2", index, "power"),
                translation_key="outlet_power",
                unit=UnitOfPower.WATT,
                device_class=SensorDeviceClass.POWER,
                state_class=_MEAS,
                exists_fn=lambda d: True,
            ),
            names,
        )
        yield (
            _current(f"pdu_outlet_{index}_current", "outlet_current", _cell("outlet_metered_rpdu2", index, "current")),
            names,
        )
        yield (
            _s(
                f"pdu_outlet_{index}_energy",
                _cell("outlet_metered_rpdu2", index, "energy"),
                translation_key="outlet_energy",
                unit=UnitOfEnergy.KILO_WATT_HOUR,
                device_class=SensorDeviceClass.ENERGY,
                state_class=SensorStateClass.TOTAL_INCREASING,
                exists_fn=lambda d: True,
            ),
            names,
        )


def _temperature(
    key: str,
    value_fn: ValueFn,
    attrs_fn: Callable[[ApcSnapshot], dict[str, Any]] | None = None,
    translation_key: str = "probe_temperature",
) -> ApcSensorDescription:
    return _s(
        key,
        value_fn,
        translation_key=translation_key,
        unit=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=_MEAS,
        attrs_fn=attrs_fn,
        exists_fn=lambda d: True,
        precision=1,
    )


def _humidity(key: str, value_fn: ValueFn, translation_key: str = "probe_humidity") -> ApcSensorDescription:
    return _s(
        key,
        value_fn,
        translation_key=translation_key,
        unit=PERCENTAGE,
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=_MEAS,
        exists_fn=lambda d: True,
    )


def _in_celsius(value: Any, fahrenheit: bool) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    if fahrenheit:
        return round(TemperatureConverter.convert(value, UnitOfTemperature.FAHRENHEIT, UnitOfTemperature.CELSIUS), 1)
    return value


def _positive(fn: ValueFn) -> ValueFn:
    def _value(d: ApcSnapshot) -> Any:
        value = fn(d)
        return value if isinstance(value, (int, float)) and value >= 0 else None

    return _value


def _env_sensors(d: ApcSnapshot) -> Iterator[tuple[ApcSensorDescription, dict[str, str]]]:
    # Sensor port of rPDU2 (AP9335T/TH)
    for index, row in d.tables.get("env_rpdu2", {}).items():
        if row.get("type") not in (1, 2):
            continue
        names = {"name": str(row.get("name") or f"Sensor {index}")}
        legacy = index == "1"
        yield (
            _temperature(
                "pdu_env_temperature" if legacy else f"env_rpdu2_{index}_temperature",
                _cell("env_rpdu2", index, "temperature"),
                translation_key="pdu_env_temperature" if legacy else "probe_temperature",
            ),
            names,
        )
        if row.get("type") == 2:
            yield (
                _humidity(
                    "pdu_env_humidity" if legacy else f"env_rpdu2_{index}_humidity",
                    _positive(_cell("env_rpdu2", index, "humidity")),
                    translation_key="pdu_env_humidity" if legacy else "probe_humidity",
                ),
                names,
            )

    # Universal I/O ports of NMC2/NMC3
    for index, row in d.tables.get("env_uio", {}).items():
        if row.get("comm_status") != 2:
            continue
        names = {"name": str(row.get("name") or f"Port {index}")}
        uid = index.replace(".", "_")

        def _uio_attrs(d: ApcSnapshot, index: str = index) -> dict[str, Any]:
            row = d.tables.get("env_uio", {}).get(index, {})
            return {"location": row.get("location"), "alarm_status": row.get("alarm_status")}

        yield _temperature(f"env_uio_{uid}_temperature", _cell("env_uio", index, "temperature"), _uio_attrs), names
        if isinstance(row.get("humidity"), (int, float)) and row["humidity"] >= 0:
            yield _humidity(f"env_uio_{uid}_humidity", _positive(_cell("env_uio", index, "humidity"))), names

    # Integrated environmental monitor (older cards)
    for index, row in d.tables.get("env_iem", {}).items():
        if row.get("status") != 2:
            continue
        names = {"name": str(row.get("name") or f"Probe {index}")}

        def _iem_temp(d: ApcSnapshot, index: str = index) -> float | None:
            row = d.tables.get("env_iem", {}).get(index, {})
            return _in_celsius(row.get("temperature"), row.get("units") == 2)

        yield _temperature(f"env_iem_{index}_temperature", _iem_temp), names
        if isinstance(row.get("humidity"), (int, float)) and row["humidity"] > 0:
            yield _humidity(f"env_iem_{index}_humidity", _positive(_cell("env_iem", index, "humidity"))), names

    # Modular environmental manager sensors
    for index, row in d.tables.get("env_mem", {}).items():
        if row.get("comm_status") != 2:
            continue
        names = {"name": str(row.get("name") or f"Sensor {index}")}
        uid = index.replace(".", "_")

        def _mem_temp(d: ApcSnapshot, index: str = index) -> float | None:
            row = d.tables.get("env_mem", {}).get(index, {})
            return _in_celsius(row.get("temperature"), d.metric("mem_temp_units") == 2)

        yield _temperature(f"env_mem_{uid}_temperature", _mem_temp), names
        if isinstance(row.get("humidity"), (int, float)) and row["humidity"] > 0:
            yield _humidity(f"env_mem_{uid}_humidity", _positive(_cell("env_mem", index, "humidity"))), names


def _dynamic_descriptions(d: ApcSnapshot) -> Iterator[tuple[ApcSensorDescription, dict[str, str]]]:
    if kind_matches(d.device_kind, DEVICE_PDU):
        yield from _phase_sensors(d)
        yield from _bank_sensors(d)
        yield from _legacy_load_sensors(d)
        yield from _metered_outlet_sensors(d)
    yield from _env_sensors(d)


# ------------------------------------------------------------------- entities


class ApcSensor(ApcEntity, SensorEntity):
    """A sensor described by an ApcSensorDescription."""

    entity_description: ApcSensorDescription

    def __init__(
        self,
        coordinator: ApcCoordinator,
        description: ApcSensorDescription,
        placeholders: dict[str, str] | None = None,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description
        if placeholders:
            self._attr_translation_placeholders = placeholders

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.snapshot)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.snapshot)


class ApcCustomMetricSensor(ApcEntity, SensorEntity):
    """Sensor for a user-defined OID."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: ApcCoordinator, key: str) -> None:
        super().__init__(coordinator, key)
        self._key = key
        self._attr_translation_key = "custom_metric"
        self._attr_translation_placeholders = {"key": key.removeprefix("custom_")}

    @property
    def native_value(self) -> Any:
        return self.snapshot.metrics.get(self._key)
