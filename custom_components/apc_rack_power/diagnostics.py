"""Diagnostics support for APC Rack Power integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from . import RUNTIME_COORDINATOR
from .const import (
    CONF_COMMUNITY,
    CONF_V3_AUTH_PASSPHRASE,
    CONF_V3_PRIV_PASSPHRASE,
    CONF_V3_USERNAME,
    CONF_WRITE_COMMUNITY,
    DOMAIN,
)
from .device_profile import detect_device_kind

TO_REDACT = {
    CONF_HOST,
    CONF_COMMUNITY,
    CONF_WRITE_COMMUNITY,
    CONF_V3_USERNAME,
    CONF_V3_AUTH_PASSPHRASE,
    CONF_V3_PRIV_PASSPHRASE,
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    runtime = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    coordinator = runtime.get(RUNTIME_COORDINATOR)
    data = coordinator.data if coordinator else None
    metrics = data.metrics if data else {}
    controls = data.discovered_controls if data else []

    return {
        "entry_id": entry.entry_id,
        "name": entry.title,
        "data": async_redact_data(dict(entry.data), TO_REDACT),
        "options": async_redact_data(dict(entry.options), TO_REDACT),
        "device_kind": detect_device_kind(metrics),
        "metric_keys_with_values": sorted([key for key, value in metrics.items() if value is not None]),
        "control_count": len(controls),
        "controls": [
            {"uid": item.uid, "table_key": item.table_key, "index": item.index, "name": item.name}
            for item in controls
        ],
        "coordinator": {
            "last_update_success": bool(coordinator.last_update_success) if coordinator else False,
            "update_interval_seconds": (
                int(coordinator.update_interval.total_seconds())
                if coordinator and coordinator.update_interval
                else None
            ),
            "reload_requested": bool(coordinator.reload_requested) if coordinator else False,
        },
    }

