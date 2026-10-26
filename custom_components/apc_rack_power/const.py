"""Constants and SNMP object definitions for APC Rack Power.

OIDs follow the APC PowerNet-MIB and RFC 1628 (UPS-MIB). Every value is
optional: devices only expose what their model and firmware support, and the
integration creates entities for whatever answers.
"""

from __future__ import annotations

from dataclasses import dataclass, field

DOMAIN = "apc_rack_power"

# Connection data (stored in entry.data)
CONF_COMMUNITY = "community"
CONF_WRITE_COMMUNITY = "write_community"
CONF_SNMP_VERSION = "snmp_version"
CONF_V3_USERNAME = "v3_username"
CONF_V3_AUTH_PROTOCOL = "v3_auth_protocol"
CONF_V3_AUTH_PASSPHRASE = "v3_auth_passphrase"
CONF_V3_PRIV_PROTOCOL = "v3_priv_protocol"
CONF_V3_PRIV_PASSPHRASE = "v3_priv_passphrase"
CONF_PORT = "port"
CONF_NAME = "name"

# Polling options (stored in entry.options)
CONF_SCAN_INTERVAL = "scan_interval"
CONF_TIMEOUT = "timeout"
CONF_RETRIES = "retries"
CONF_CUSTOM_OIDS = "custom_oids"
CONF_TRAP_ENABLED = "trap_enabled"
CONF_TRAP_PORT = "trap_port"
CONF_TRAP_COMMUNITY = "trap_community"

# Options of earlier versions that are no longer used
LEGACY_OPTION_KEYS = ("pdu_nominal_watts", "temperature_scale")

CONNECTION_KEYS = (
    CONF_SNMP_VERSION,
    CONF_COMMUNITY,
    CONF_WRITE_COMMUNITY,
    CONF_V3_USERNAME,
    CONF_V3_AUTH_PROTOCOL,
    CONF_V3_AUTH_PASSPHRASE,
    CONF_V3_PRIV_PROTOCOL,
    CONF_V3_PRIV_PASSPHRASE,
)
POLLING_KEYS = (CONF_SCAN_INTERVAL, CONF_TIMEOUT, CONF_RETRIES, CONF_CUSTOM_OIDS)

SNMP_V1 = "v1"
SNMP_V2C = "v2c"
SNMP_V3 = "v3"
SNMP_VERSIONS = [SNMP_V3, SNMP_V2C, SNMP_V1]

# "sha" is SHA-1 (kept for entries created by earlier versions).
AUTH_PROTOCOLS = ["none", "md5", "sha", "sha224", "sha256", "sha384", "sha512"]
# "aes" is AES-128. "aes192"/"aes256" use the Blumenthal key extension
# (net-snmp default), the "c" variants the Reeder/Cisco key extension.
PRIV_PROTOCOLS = ["none", "des", "3des", "aes", "aes192", "aes256", "aes192c", "aes256c"]

DEFAULT_NAME = "APC Device"
DEFAULT_PORT = 161
DEFAULT_SCAN_INTERVAL = 30
DEFAULT_TIMEOUT = 3
DEFAULT_RETRIES = 1
DEFAULT_COMMUNITY = "public"
DEFAULT_SNMP_VERSION = SNMP_V2C
DEFAULT_TRAP_PORT = 162
DEFAULT_TRAP_COMMUNITY = "public"

PLATFORMS: list[str] = ["binary_sensor", "button", "select", "sensor", "switch"]

SERVICE_SET_OID = "set_oid"
SERVICE_CONTROL_ACTION = "control_action"

EVENT_TRAP = f"{DOMAIN}_trap"

# Controls and the discovery of tables are refreshed every n polls.
DISCOVERY_EVERY = 20

DEVICE_PDU = "pdu"
DEVICE_UPS = "ups"
DEVICE_MIXED = "mixed"


@dataclass(slots=True, frozen=True)
class MetricDef:
    """A scalar value; the first source that answers wins.

    Each source is (oid, scale). Raw values below zero are treated as "not
    supported" (APC agents answer -1) unless allow_negative is set.
    """

    key: str
    sources: tuple[tuple[str, float], ...]
    precision: int | None = None
    allow_negative: bool = False


def _m(
    key: str,
    *sources: str | tuple[str, float],
    precision: int | None = None,
    allow_negative: bool = False,
) -> MetricDef:
    normalized = tuple(src if isinstance(src, tuple) else (src, 1.0) for src in sources)
    return MetricDef(key, normalized, precision, allow_negative)


_UPS = ".1.3.6.1.4.1.318.1.1.1"
_RFC = ".1.3.6.1.2.1.33.1"
_RPDU2 = ".1.3.6.1.4.1.318.1.1.26"
_RPDU = ".1.3.6.1.4.1.318.1.1.12"
_SPDU = ".1.3.6.1.4.1.318.1.1.4"

METRICS: tuple[MetricDef, ...] = (
    # MIB-2 system group
    _m("sys_descr", ".1.3.6.1.2.1.1.1.0"),
    _m("sys_object_id", ".1.3.6.1.2.1.1.2.0"),
    _m("sys_uptime_ticks", ".1.3.6.1.2.1.1.3.0"),
    _m("sys_name", ".1.3.6.1.2.1.1.5.0"),
    # UPS identification
    _m("ups_ident_model", f"{_RFC}.1.2.0", f"{_UPS}.1.1.1.0"),
    _m("ups_ident_name", f"{_RFC}.1.5.0", f"{_UPS}.1.1.2.0"),
    _m("ups_sku", f"{_UPS}.1.2.5.0"),
    _m("ups_firmware", f"{_UPS}.1.2.1.0", f"{_RFC}.1.3.0"),
    _m("ups_serial_number", f"{_UPS}.1.2.3.0"),
    # UPS battery
    _m("rfc_battery_status", f"{_RFC}.2.1.0"),
    _m("apc_battery_status", f"{_UPS}.2.1.1.0"),
    _m("ups_seconds_on_battery", f"{_RFC}.2.2.0"),
    _m("ups_minutes_remaining", f"{_RFC}.2.3.0"),
    _m("ups_charge_remaining", f"{_RFC}.2.4.0", f"{_UPS}.2.2.1.0"),
    _m("ups_battery_voltage", (f"{_RFC}.2.5.0", 0.1), (f"{_UPS}.2.3.4.0", 0.1), precision=1),
    _m("ups_battery_current", (f"{_RFC}.2.6.0", 0.1), precision=1, allow_negative=True),
    _m("ups_battery_temp", f"{_RFC}.2.7.0", (f"{_UPS}.2.3.2.0", 0.1), f"{_UPS}.2.2.2.0", precision=1),
    _m("ups_battery_last_replaced", f"{_UPS}.2.1.3.0"),
    _m("ups_battery_replace_indicator", f"{_UPS}.2.2.4.0"),
    _m("ups_battery_packs", f"{_UPS}.2.2.5.0"),
    _m("ups_battery_bad_packs", f"{_UPS}.2.2.6.0"),
    _m("ups_external_battery_model", f"{_UPS}.2.2.20.0"),
    _m("ups_battery_replace_by", f"{_UPS}.2.2.21.0"),
    # UPS input
    _m("ups_input_line_bads", f"{_RFC}.3.1.0"),
    _m("ups_input_frequency", (f"{_RFC}.3.3.1.2.1", 0.1), (f"{_UPS}.3.3.4.0", 0.1), f"{_UPS}.3.2.4.0", precision=1),
    _m("ups_input_voltage", f"{_RFC}.3.3.1.3.1", (f"{_UPS}.3.3.1.0", 0.1), f"{_UPS}.3.2.1.0", precision=1),
    _m("ups_last_transfer_cause", f"{_UPS}.3.2.5.0"),
    # UPS output
    _m("rfc_output_source", f"{_RFC}.4.1.0"),
    _m("apc_output_status", f"{_UPS}.4.1.1.0"),
    _m("ups_output_frequency", (f"{_RFC}.4.2.0", 0.1), (f"{_UPS}.4.3.2.0", 0.1), f"{_UPS}.4.2.2.0", precision=1),
    _m("ups_output_voltage", f"{_RFC}.4.4.1.2.1", (f"{_UPS}.4.3.1.0", 0.1), f"{_UPS}.4.2.1.0", precision=1),
    _m("ups_output_current", (f"{_RFC}.4.4.1.3.1", 0.1), (f"{_UPS}.4.3.4.0", 0.1), f"{_UPS}.4.2.4.0", precision=1),
    _m("ups_output_power", f"{_RFC}.4.4.1.4.1", f"{_UPS}.4.2.8.0"),
    _m("ups_output_apparent_power", f"{_UPS}.4.2.9.0"),
    _m("ups_output_load", f"{_RFC}.4.4.1.5.1", (f"{_UPS}.4.3.3.0", 0.1), f"{_UPS}.4.2.3.0", precision=1),
    _m("ups_output_energy", (f"{_UPS}.4.3.6.0", 0.01), precision=2),
    _m("ups_efficiency_raw", f"{_UPS}.4.3.5.0", allow_negative=True),
    # UPS state, alarms and tests
    _m("ups_alarms_present", f"{_RFC}.6.1.0"),
    _m("ups_state_flags", f"{_UPS}.11.1.1.0"),
    _m("ups_comm_status", f"{_UPS}.8.1.0"),
    _m("rfc_test_result", f"{_RFC}.7.3.0"),
    _m("apc_test_result", f"{_UPS}.7.2.3.0"),
    _m("ups_last_self_test", f"{_UPS}.7.2.4.0"),
    _m("ups_test_command", f"{_UPS}.7.2.2.0"),
    _m("ups_calibration_command", f"{_UPS}.7.2.5.0"),
    _m("ups_calibration_result", f"{_UPS}.7.2.6.0"),
    _m("ups_last_calibration", f"{_UPS}.7.2.7.0"),
    _m("ups_flash_and_beep", f"{_UPS}.6.2.5.0"),
    _m("ups_alarm_beeper", f"{_UPS}.5.2.4.0"),
    # Rack PDU identification (rPDU2, then rPDU, then the MasterSwitch sPDU)
    _m("pdu_name", f"{_RPDU2}.2.1.3.1", f"{_RPDU}.1.1.0"),
    _m("pdu_location", f"{_RPDU2}.2.1.4.1"),
    _m("pdu_hardware_rev", f"{_RPDU2}.2.1.5.1", f"{_RPDU}.1.2.0", f"{_SPDU}.1.1.0"),
    _m("pdu_firmware_rpdu", f"{_RPDU2}.2.1.6.1", f"{_RPDU}.1.3.0", f"{_SPDU}.1.2.0"),
    _m("pdu_model_number", f"{_RPDU2}.2.1.8.1", f"{_RPDU}.1.5.0", f"{_SPDU}.1.4.0"),
    _m("pdu_serial_number", f"{_RPDU2}.2.1.9.1", f"{_RPDU}.1.6.0", f"{_SPDU}.1.5.0"),
    _m("pdu_contact", f"{_RPDU2}.2.1.10.1"),
    _m("pdu_firmware_bootmon", f"{_RPDU2}.2.1.11.1"),
    # Rack PDU properties
    _m("pdu_device_num_outlets", f"{_RPDU2}.4.2.1.4.1", f"{_RPDU}.1.8.0", f"{_SPDU}.4.1.0"),
    _m("pdu_num_phases", f"{_RPDU2}.4.2.1.7.1", f"{_RPDU}.1.9.0"),
    _m("pdu_bank_count", f"{_RPDU2}.7.0", f"{_RPDU}.2.1.4.0"),
    _m("pdu_max_current", f"{_RPDU2}.4.2.1.9.1", f"{_RPDU}.1.7.0"),
    _m("pdu_power_rating", (f"{_RPDU2}.4.2.1.13.1", 100.0)),
    # Rack PDU device status
    _m("pdu_load_state", f"{_RPDU2}.4.3.1.4.1"),
    _m("pdu_power", (f"{_RPDU2}.4.3.1.5.1", 10.0)),
    _m("pdu_peak_power_kw", (f"{_RPDU2}.4.3.1.6.1", 0.01), precision=2),
    _m("pdu_energy_kwh", (f"{_RPDU2}.4.3.1.9.1", 0.1), (f"{_RPDU2}.11.3.0", 0.1), precision=1),
    _m("pdu_power_supply_alarm", f"{_RPDU2}.4.3.1.12.1"),
    _m("pdu_legacy_power_supply_alarm", f"{_RPDU}.4.1.3.0"),
    _m("pdu_apparent_power", (f"{_RPDU2}.4.3.1.16.1", 10.0)),
    _m("pdu_device_power_factor", (f"{_RPDU2}.4.3.1.17.1", 0.01), precision=2),
    _m("pdu_nps_type", f"{_RPDU2}.4.3.1.18.1"),
    # Shared environment units
    _m("mem_temp_units", ".1.3.6.1.4.1.318.1.1.10.4.2.1.0"),
)


@dataclass(slots=True, frozen=True)
class Column:
    """One column of an SNMP table."""

    oid: str
    scale: float = 1.0
    precision: int | None = None


@dataclass(slots=True, frozen=True)
class TableDef:
    """An SNMP table polled column by column."""

    key: str
    columns: dict[str, Column] = field(default_factory=dict)
    # Columns only read during discovery (names, thresholds)
    static_columns: dict[str, Column] = field(default_factory=dict)


def _c(oid: str, scale: float = 1.0, precision: int | None = None) -> Column:
    return Column(oid, scale, precision)


TABLES: tuple[TableDef, ...] = (
    # All rPDU2 devices; rows beyond the first are Network Port Sharing guests
    TableDef(
        "device_rpdu2",
        columns={
            "load_state": _c(f"{_RPDU2}.4.3.1.4"),
            "power": _c(f"{_RPDU2}.4.3.1.5", 10.0, 0),
            "energy": _c(f"{_RPDU2}.4.3.1.9", 0.1, 1),
            "power_supply_alarm": _c(f"{_RPDU2}.4.3.1.12"),
            "apparent_power": _c(f"{_RPDU2}.4.3.1.16", 10.0, 0),
            "power_factor": _c(f"{_RPDU2}.4.3.1.17", 0.01, 2),
        },
        static_columns={
            "module": _c(f"{_RPDU2}.2.1.2"),
            "name": _c(f"{_RPDU2}.2.1.3"),
            "firmware": _c(f"{_RPDU2}.2.1.6"),
            "model": _c(f"{_RPDU2}.2.1.8"),
            "serial": _c(f"{_RPDU2}.2.1.9"),
        },
    ),
    # rPDU2 phases: load state, current (0.1 A), voltage, power (0.01 kW)
    TableDef(
        "phase_rpdu2",
        columns={
            "load_state": _c(f"{_RPDU2}.6.3.1.4"),
            "current": _c(f"{_RPDU2}.6.3.1.5", 0.1, 1),
            "voltage": _c(f"{_RPDU2}.6.3.1.6"),
            "power": _c(f"{_RPDU2}.6.3.1.7", 10.0, 0),
            "apparent_power": _c(f"{_RPDU2}.6.3.1.8", 10.0, 0),
            "power_factor": _c(f"{_RPDU2}.6.3.1.9", 0.01, 2),
            "peak_current": _c(f"{_RPDU2}.6.3.1.10", 0.1, 1),
        },
        static_columns={
            "module": _c(f"{_RPDU2}.6.3.1.2"),
            "number": _c(f"{_RPDU2}.6.3.1.3"),
            "low_load_threshold": _c(f"{_RPDU2}.6.1.1.5"),
            "near_overload_threshold": _c(f"{_RPDU2}.6.1.1.6"),
            "overload_threshold": _c(f"{_RPDU2}.6.1.1.7"),
        },
    ),
    # rPDU2 banks (only on models with breaker banks)
    TableDef(
        "bank_rpdu2",
        columns={
            "load_state": _c(f"{_RPDU2}.8.3.1.4"),
            "current": _c(f"{_RPDU2}.8.3.1.5", 0.1, 1),
            "peak_current": _c(f"{_RPDU2}.8.3.1.6", 0.1, 1),
        },
        static_columns={
            "module": _c(f"{_RPDU2}.8.3.1.2"),
            "number": _c(f"{_RPDU2}.8.3.1.3"),
            "low_load_threshold": _c(f"{_RPDU2}.8.1.1.5"),
            "near_overload_threshold": _c(f"{_RPDU2}.8.1.1.6"),
            "overload_threshold": _c(f"{_RPDU2}.8.1.1.7"),
        },
    ),
    # Legacy rPDU phase/bank load (AP78xx/AP79xx with older firmware)
    TableDef(
        "load_rpdu",
        columns={
            "current": _c(f"{_RPDU}.2.3.1.1.2", 0.1, 1),
            "legacy_load_state": _c(f"{_RPDU}.2.3.1.1.3"),
        },
        static_columns={
            "phase": _c(f"{_RPDU}.2.3.1.1.4"),
            "bank": _c(f"{_RPDU}.2.3.1.1.5"),
        },
    ),
    TableDef(
        "load_rpdu_cfg",
        static_columns={
            "low_load_threshold": _c(f"{_RPDU}.2.2.1.1.2"),
            "near_overload_threshold": _c(f"{_RPDU}.2.2.1.1.3"),
            "overload_threshold": _c(f"{_RPDU}.2.2.1.1.4"),
        },
    ),
    # rPDU2 metered outlets (metered-by-outlet models such as AP88xx)
    TableDef(
        "outlet_metered_rpdu2",
        columns={
            "load_state": _c(f"{_RPDU2}.9.4.3.1.5"),
            "current": _c(f"{_RPDU2}.9.4.3.1.6", 0.1, 1),
            "power": _c(f"{_RPDU2}.9.4.3.1.7"),
            "energy": _c(f"{_RPDU2}.9.4.3.1.11", 0.1, 1),
        },
        static_columns={"name": _c(f"{_RPDU2}.9.4.3.1.3"), "module": _c(f"{_RPDU2}.9.4.3.1.2")},
    ),
    # Temperature/humidity sensor on the rPDU2 sensor port (AP9335T/TH)
    TableDef(
        "env_rpdu2",
        columns={
            "type": _c(f"{_RPDU2}.10.2.2.1.5"),
            "temperature": _c(f"{_RPDU2}.10.2.2.1.8", 0.1, 1),
            "humidity": _c(f"{_RPDU2}.10.2.2.1.10"),
            "temp_status": _c(f"{_RPDU2}.10.2.2.1.9"),
            "humidity_status": _c(f"{_RPDU2}.10.2.2.1.11"),
        },
        static_columns={"name": _c(f"{_RPDU2}.10.2.2.1.3"), "module": _c(f"{_RPDU2}.10.2.2.1.2")},
    ),
    # Universal I/O sensor ports of NMC2/NMC3 cards (AP9631, AP9641, ...)
    TableDef(
        "env_uio",
        columns={
            "temperature": _c(".1.3.6.1.4.1.318.1.1.25.1.2.1.6"),
            "humidity": _c(".1.3.6.1.4.1.318.1.1.25.1.2.1.7"),
            "alarm_status": _c(".1.3.6.1.4.1.318.1.1.25.1.2.1.9"),
            "comm_status": _c(".1.3.6.1.4.1.318.1.1.25.1.2.1.10"),
        },
        static_columns={
            "name": _c(".1.3.6.1.4.1.318.1.1.25.1.2.1.3"),
            "location": _c(".1.3.6.1.4.1.318.1.1.25.1.2.1.4"),
        },
    ),
    # Integrated environmental monitor of older cards (AP9619, AP9631 probe port)
    TableDef(
        "env_iem",
        columns={
            "status": _c(".1.3.6.1.4.1.318.1.1.10.2.3.2.1.3"),
            "temperature": _c(".1.3.6.1.4.1.318.1.1.10.2.3.2.1.4"),
            "units": _c(".1.3.6.1.4.1.318.1.1.10.2.3.2.1.5"),
            "humidity": _c(".1.3.6.1.4.1.318.1.1.10.2.3.2.1.6"),
        },
        static_columns={"name": _c(".1.3.6.1.4.1.318.1.1.10.2.3.2.1.2")},
    ),
    # Modular environmental manager sensors (NetBotz/EMU style)
    TableDef(
        "env_mem",
        columns={
            "temperature": _c(".1.3.6.1.4.1.318.1.1.10.4.2.3.1.5"),
            "humidity": _c(".1.3.6.1.4.1.318.1.1.10.4.2.3.1.6"),
            "comm_status": _c(".1.3.6.1.4.1.318.1.1.10.4.2.3.1.7"),
            "alarm_status": _c(".1.3.6.1.4.1.318.1.1.10.4.2.3.1.8"),
        },
        static_columns={"name": _c(".1.3.6.1.4.1.318.1.1.10.4.2.3.1.3")},
    ),
)


@dataclass(slots=True, frozen=True)
class ControlTableDef:
    """A table of switchable outlets or outlet groups."""

    key: str
    kind: str  # "pdu" or "ups"
    name_oid: str
    state_oid: str
    command_oid: str
    state_on: int
    state_off: int
    cmd_on: int = 1
    cmd_off: int = 2
    cmd_reboot: int | None = 3
    # Column with the NPS module number of each row (rPDU2 only)
    module_oid: str | None = None


# PDU tables are mutually exclusive: the first one that answers is used
# (newer firmware exposes the legacy tables as well).
CONTROL_TABLES: tuple[ControlTableDef, ...] = (
    ControlTableDef(
        key="rpdu2_outlet",
        kind=DEVICE_PDU,
        name_oid=f"{_RPDU2}.9.2.3.1.3",
        state_oid=f"{_RPDU2}.9.2.3.1.5",
        command_oid=f"{_RPDU2}.9.2.4.1.5",
        state_on=2,
        state_off=1,
        module_oid=f"{_RPDU2}.9.2.3.1.2",
    ),
    ControlTableDef(
        key="rpdu_outlet",
        kind=DEVICE_PDU,
        name_oid=f"{_RPDU}.3.5.1.1.2",
        state_oid=f"{_RPDU}.3.5.1.1.4",
        command_oid=f"{_RPDU}.3.3.1.1.4",
        state_on=1,
        state_off=2,
    ),
    ControlTableDef(
        key="spdu_outlet",
        kind=DEVICE_PDU,
        name_oid=f"{_SPDU}.4.2.1.4",
        state_oid=f"{_SPDU}.4.2.1.3",
        command_oid=f"{_SPDU}.4.2.1.3",
        state_on=1,
        state_off=2,
    ),
    ControlTableDef(
        key="ups_outlet_group",
        kind=DEVICE_UPS,
        name_oid=f"{_UPS}.12.1.2.1.2",
        state_oid=f"{_UPS}.12.1.2.1.3",
        command_oid=f"{_UPS}.12.3.2.1.3",
        state_on=1,
        state_off=2,
    ),
)

# Writable scalars used by buttons and selects
OID_UPS_TEST = f"{_UPS}.7.2.2.0"  # testDiagnostics(2)
OID_UPS_CALIBRATION = f"{_UPS}.7.2.5.0"  # performCalibration(2), cancel(3)
OID_UPS_FLASH_AND_BEEP = f"{_UPS}.6.2.5.0"  # flashAndBeep(2)
OID_UPS_ALARM_BEEPER = f"{_UPS}.5.2.4.0"  # timed(1) atLowBattery(2) never(3) mute(4)

# Enumerations (raw SNMP value -> state)
RFC_BATTERY_STATUS = {1: "unknown", 2: "normal", 3: "low", 4: "depleted"}
APC_BATTERY_STATUS = {1: "unknown", 2: "normal", 3: "low", 4: "fault", 5: "not_present"}
BATTERY_STATUS_OPTIONS = ["unknown", "normal", "low", "depleted", "fault", "not_present"]

RFC_OUTPUT_SOURCE = {
    1: "other",
    2: "none",
    3: "normal",
    4: "bypass",
    5: "battery",
    6: "booster",
    7: "reducer",
}

APC_OUTPUT_STATUS = {
    1: "unknown",
    2: "on_line",
    3: "on_battery",
    4: "on_smart_boost",
    5: "timed_sleeping",
    6: "software_bypass",
    7: "off",
    8: "rebooting",
    9: "switched_bypass",
    10: "hardware_failure_bypass",
    11: "sleeping_until_power_return",
    12: "on_smart_trim",
    13: "eco_mode",
    14: "hot_standby",
    15: "on_battery_test",
    16: "emergency_static_bypass",
    17: "static_bypass_standby",
    18: "power_saving_mode",
    19: "spot_mode",
    20: "e_conversion",
    21: "charger_spot_mode",
    22: "inverter_spot_mode",
    23: "active_load",
    24: "battery_discharge_spot_mode",
    25: "inverter_standby",
    26: "charger_only",
    27: "distributed_energy_reserve",
    28: "self_test",
}

RFC_TEST_RESULT = {
    1: "passed",
    2: "warning",
    3: "error",
    4: "aborted",
    5: "in_progress",
    6: "none",
}
APC_TEST_RESULT = {1: "passed", 2: "error", 3: "aborted", 4: "in_progress"}
TEST_RESULT_OPTIONS = ["passed", "warning", "error", "aborted", "in_progress", "none"]

TRANSFER_CAUSE = {
    1: "no_transfer",
    2: "high_line_voltage",
    3: "brownout",
    4: "blackout",
    5: "small_momentary_sag",
    6: "deep_momentary_sag",
    7: "small_momentary_spike",
    8: "large_momentary_spike",
    9: "self_test",
    10: "rate_of_voltage_change",
}

CALIBRATION_RESULT = {
    1: "ok",
    2: "invalid",
    3: "in_progress",
    4: "refused",
    5: "aborted",
    6: "pending",
    7: "unknown",
}

ALARM_BEEPER = {1: "timed", 2: "at_low_battery", 3: "never", 4: "mute"}

LOAD_STATE = {1: "low_load", 2: "normal", 3: "near_overload", 4: "overload"}
# Legacy rPDU numbers its load states differently
LEGACY_LOAD_STATE = {1: "normal", 2: "low_load", 3: "near_overload", 4: "overload"}

NPS_TYPE = {1: "not_nps", 2: "host", 3: "guest"}

# Flags of upsBasicStateOutputState (1-based positions)
FLAG_ABNORMAL = 1
FLAG_ON_BATTERY = 2
FLAG_LOW_BATTERY = 3
FLAG_REPLACE_BATTERY = 5
FLAG_OVERLOAD = 9
FLAG_CALIBRATION = 10
FLAG_BYPASS = (12, 13, 14, 15, 16, 44)
FLAG_SELF_TEST = 29
