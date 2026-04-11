"""Constants for APC Rack Power integration."""

from __future__ import annotations

from dataclasses import dataclass

DOMAIN = "apc_rack_power"

CONF_COMMUNITY = "community"
CONF_WRITE_COMMUNITY = "write_community"
CONF_PORT = "port"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_TIMEOUT = "timeout"
CONF_RETRIES = "retries"
CONF_NAME = "name"
CONF_CUSTOM_OIDS = "custom_oids"
CONF_PDU_NOMINAL_WATTS = "pdu_nominal_watts"
CONF_TEMP_SCALE = "temperature_scale"

DEFAULT_NAME = "APC Device"
DEFAULT_PORT = 161
DEFAULT_SCAN_INTERVAL = 30
DEFAULT_TIMEOUT = 3
DEFAULT_RETRIES = 1
DEFAULT_COMMUNITY = "apc"
DEFAULT_PDU_NOMINAL_WATTS = 0
DEFAULT_TEMP_SCALE = "celsius"

PLATFORMS: list[str] = ["sensor", "switch"]

SERVICE_SET_OID = "set_oid"
SERVICE_CONTROL_ACTION = "control_action"

ON_VALUES = {1}
OFF_VALUES = {2}


@dataclass(slots=True, frozen=True)
class MetricDef:
    """Definition of a polled SNMP metric."""

    key: str
    oid: str
    fallback_oids: tuple[str, ...] = ()
    scale: float = 1.0
    precision: int | None = None


@dataclass(slots=True, frozen=True)
class ControlTableDef:
    """Definition of a control table for switch creation."""

    key: str
    label: str
    name_oid: str
    status_oid: str
    control_oid: str
    on_value: int = 1
    off_value: int = 2
    cycle_value: int | None = 3


BASE_METRICS: tuple[MetricDef, ...] = (
    MetricDef("sys_descr", ".1.3.6.1.2.1.1.1.0"),
    MetricDef("sys_name", ".1.3.6.1.2.1.1.5.0"),
    MetricDef("sys_uptime_ticks", ".1.3.6.1.2.1.1.3.0"),
    MetricDef(
        "ups_ident_model",
        ".1.3.6.1.2.1.33.1.1.2.0",
        fallback_oids=(".1.3.6.1.4.1.318.1.1.1.1.1.1.0",),
    ),
    MetricDef("ups_sku", ".1.3.6.1.4.1.318.1.1.1.1.2.5.0"),
    MetricDef(
        "ups_ident_name",
        ".1.3.6.1.2.1.33.1.1.5.0",
        fallback_oids=(".1.3.6.1.4.1.318.1.1.1.1.1.2.0",),
    ),
    MetricDef("ups_battery_status", ".1.3.6.1.2.1.33.1.2.1.0"),
    MetricDef("ups_seconds_on_battery", ".1.3.6.1.2.1.33.1.2.2.0"),
    MetricDef("ups_minutes_remaining", ".1.3.6.1.2.1.33.1.2.3.0"),
    MetricDef("ups_charge_remaining", ".1.3.6.1.2.1.33.1.2.4.0"),
    MetricDef("ups_battery_voltage", ".1.3.6.1.2.1.33.1.2.5.0", scale=0.1, precision=1),
    MetricDef("ups_battery_current", ".1.3.6.1.2.1.33.1.2.6.0", scale=0.1, precision=1),
    MetricDef("ups_battery_temp", ".1.3.6.1.2.1.33.1.2.7.0"),
    MetricDef("ups_input_line_bads", ".1.3.6.1.2.1.33.1.3.1.0"),
    MetricDef("ups_input_frequency", ".1.3.6.1.2.1.33.1.3.3.1.2.1", scale=0.1, precision=1),
    MetricDef("ups_input_voltage", ".1.3.6.1.2.1.33.1.3.3.1.3.1"),
    MetricDef("ups_output_source", ".1.3.6.1.2.1.33.1.4.1.0"),
    MetricDef("ups_output_frequency", ".1.3.6.1.2.1.33.1.4.2.0", scale=0.1, precision=1),
    MetricDef("ups_output_voltage", ".1.3.6.1.2.1.33.1.4.4.1.2.1"),
    MetricDef("ups_output_current", ".1.3.6.1.2.1.33.1.4.4.1.3.1", scale=0.1, precision=1),
    MetricDef("ups_output_load", ".1.3.6.1.2.1.33.1.4.4.1.5.1"),
    MetricDef("ups_alarms_present", ".1.3.6.1.2.1.33.1.6.1.0"),
    MetricDef("ups_test_result", ".1.3.6.1.2.1.33.1.7.3.0"),
    MetricDef("pdu_device_num_outlets", ".1.3.6.1.4.1.318.1.1.26.9.1.0"),
    MetricDef("pdu_device_load_percent", ".1.3.6.1.4.1.318.1.1.26.11.2.0"),
    MetricDef("pdu_energy_kwh", ".1.3.6.1.4.1.318.1.1.26.11.3.0", scale=0.1, precision=1),
    MetricDef("pdu_peak_power_kw", ".1.3.6.1.4.1.318.1.1.26.4.3.1.6.1", scale=0.01, precision=2),
    MetricDef("pdu_phase_voltage", ".1.3.6.1.4.1.318.1.1.26.6.3.1.6.1"),
    MetricDef("pdu_phase_current", ".1.3.6.1.4.1.318.1.1.26.6.3.1.7.1", scale=0.1, precision=1),
    MetricDef("pdu_phase_power_kw", ".1.3.6.1.4.1.318.1.1.26.6.3.1.8.1", scale=0.01, precision=2),
    MetricDef("pdu_phase_active_power_w", ".1.3.6.1.4.1.318.1.1.26.6.3.1.8.1", scale=10.0, precision=1),
    MetricDef("pdu_power_factor", ".1.3.6.1.4.1.318.1.1.26.6.3.1.9.1", scale=0.01, precision=2),
    MetricDef("pdu_peak_current", ".1.3.6.1.4.1.318.1.1.26.6.3.1.10.1", scale=0.1, precision=1),
    MetricDef("pdu_bank_count", ".1.3.6.1.4.1.318.1.1.26.10.1.0"),
    MetricDef("pdu_name", ".1.3.6.1.4.1.318.1.1.26.2.1.3.1"),
    MetricDef("pdu_location", ".1.3.6.1.4.1.318.1.1.26.2.1.4.1"),
    MetricDef("pdu_model_number", ".1.3.6.1.4.1.318.1.1.26.2.1.8.1"),
    MetricDef("pdu_serial_number", ".1.3.6.1.4.1.318.1.1.26.2.1.9.1"),
    MetricDef("pdu_contact", ".1.3.6.1.4.1.318.1.1.26.2.1.10.1"),
    MetricDef("pdu_firmware_rpdu", ".1.3.6.1.4.1.318.1.1.26.2.1.6.1"),
    MetricDef("pdu_firmware_bootmon", ".1.3.6.1.4.1.318.1.1.26.2.1.11.1"),
    MetricDef("pdu_nps_status", ".1.3.6.1.4.1.318.1.1.26.12.0"),
    MetricDef("pdu_env_temp_f", ".1.3.6.1.4.1.318.1.1.26.10.2.2.1.7.1", scale=0.1, precision=1),
    MetricDef("pdu_env_temp_c", ".1.3.6.1.4.1.318.1.1.26.10.2.2.1.8.1", scale=0.1, precision=1),
    MetricDef("pdu_env_temp_status", ".1.3.6.1.4.1.318.1.1.26.10.2.2.1.9.1"),
    MetricDef("pdu_env_humidity", ".1.3.6.1.4.1.318.1.1.26.10.2.2.1.10.1"),
    MetricDef("pdu_env_humidity_status", ".1.3.6.1.4.1.318.1.1.26.10.2.2.1.11.1"),
)


CONTROL_TABLES: tuple[ControlTableDef, ...] = (
    ControlTableDef(
        key="rpdu2_outlet",
        label="PDU Outlet",
        name_oid=".1.3.6.1.4.1.318.1.1.26.9.2.3.1.3",
        status_oid=".1.3.6.1.4.1.318.1.1.26.9.2.3.1.5",
        control_oid=".1.3.6.1.4.1.318.1.1.26.9.2.3.1.6",
    ),
    ControlTableDef(
        key="spdu_outlet",
        label="PDU Outlet",
        name_oid=".1.3.6.1.4.1.318.1.1.4.5.2.1.4",
        status_oid=".1.3.6.1.4.1.318.1.1.4.2.3.1.3",
        control_oid=".1.3.6.1.4.1.318.1.1.4.5.2.1.3",
    ),
    ControlTableDef(
        key="ups_outlet_group",
        label="UPS Outlet Group",
        name_oid=".1.3.6.1.4.1.318.1.1.1.12.2.3.1.2",
        status_oid=".1.3.6.1.4.1.318.1.1.1.12.2.3.1.4",
        control_oid=".1.3.6.1.4.1.318.1.1.1.12.2.3.1.3",
    ),
)


