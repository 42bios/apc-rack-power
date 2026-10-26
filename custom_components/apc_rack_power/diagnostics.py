"""Diagnostics support for APC Rack Power."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from . import ApcConfigEntry
from .const import (
    CONF_COMMUNITY,
    CONF_TRAP_COMMUNITY,
    CONF_V3_AUTH_PASSPHRASE,
    CONF_V3_PRIV_PASSPHRASE,
    CONF_V3_USERNAME,
    CONF_WRITE_COMMUNITY,
)

TO_REDACT = {
    CONF_HOST,
    CONF_COMMUNITY,
    CONF_WRITE_COMMUNITY,
    CONF_TRAP_COMMUNITY,
    CONF_V3_USERNAME,
    CONF_V3_AUTH_PASSPHRASE,
    CONF_V3_PRIV_PASSPHRASE,
}

# Metric values that identify a specific unit or site
_PRIVATE_METRICS = {
    "sys_name",
    "sys_descr",
    "ups_serial_number",
    "ups_ident_name",
    "pdu_serial_number",
    "pdu_name",
    "pdu_location",
    "pdu_contact",
}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ApcConfigEntry) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    data = coordinator.data
    metrics = data.metrics if data else {}
    return {
        "entry_id": entry.entry_id,
        "name": entry.title,
        "data": async_redact_data(dict(entry.data), TO_REDACT),
        "options": async_redact_data(dict(entry.options), TO_REDACT),
        "device_kind": data.device_kind if data else None,
        "metrics": async_redact_data(
            {key: value for key, value in metrics.items() if value is not None}, _PRIVATE_METRICS
        ),
        "tables": {key: len(rows) for key, rows in (data.tables if data else {}).items()},
        "controls": [
            {"uid": item.uid, "table": item.table_key, "index": item.index, "state": data.control_states.get(item.uid)}
            for item in (data.controls if data else [])
        ],
        "traps_received": coordinator.trap_count,
        "last_trap": coordinator.last_trap,
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "update_interval_seconds": (
                int(coordinator.update_interval.total_seconds()) if coordinator.update_interval else None
            ),
        },
    }
