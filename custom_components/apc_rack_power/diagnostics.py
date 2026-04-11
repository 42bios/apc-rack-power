"""Diagnostics support for APC Rack Power integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from . import RUNTIME_COORDINATOR
from .const import DOMAIN
from .device_profile import detect_device_kind


def _redact_host(host: str) -> str:
    parts = host.split(".")
    if len(parts) == 4:
        return ".".join(parts[:3] + ["x"])
    return "redacted"


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
        "host": _redact_host(str(entry.data.get(CONF_HOST, ""))),
        "name": entry.title,
        "options": dict(entry.options),
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

