"""Initialize APC Rack Power integration."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.service import async_register_admin_service

from .const import (
    CONF_COMMUNITY,
    CONF_CUSTOM_OIDS,
    CONF_NAME,
    CONF_PORT,
    CONF_RETRIES,
    CONF_SCAN_INTERVAL,
    CONF_TIMEOUT,
    CONF_WRITE_COMMUNITY,
    DEFAULT_COMMUNITY,
    DEFAULT_NAME,
    DEFAULT_PORT,
    DEFAULT_RETRIES,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TIMEOUT,
    DOMAIN,
    PLATFORMS,
    SERVICE_CONTROL_ACTION,
    SERVICE_SET_OID,
    MetricDef,
)
from .coordinator import ApcEnterpriseCoordinator
from .snmp_client import ApcSnmpClient, ApcSnmpError

_LOGGER = logging.getLogger(__name__)

RUNTIME_COORDINATOR = "coordinator"

SET_OID_SCHEMA = vol.Schema(
    {
        vol.Required("entry_id"): cv.string,
        vol.Required("oid"): cv.string,
        vol.Required("value"): vol.Coerce(int),
    }
)

CONTROL_ACTION_SCHEMA = vol.Schema(
    {
        vol.Required("entry_id"): cv.string,
        vol.Required("control_uid"): cv.string,
        vol.Required("action"): vol.In(["on", "off", "cycle"]),
    }
)


def _parse_custom_oids(raw: str | None) -> list[MetricDef]:
    """Parse custom OID mappings from options."""
    if not raw:
        return []
    defs: list[MetricDef] = []
    for line in raw.splitlines():
        cleaned = line.strip()
        if not cleaned or cleaned.startswith("#"):
            continue
        if "=" not in cleaned:
            continue
        key, oid = cleaned.split("=", 1)
        metric_key = key.strip().lower().replace(" ", "_")
        metric_oid = oid.strip()
        if not metric_key or not metric_oid:
            continue
        defs.append(MetricDef(metric_key, metric_oid))
    return defs


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _get_entry(hass: HomeAssistant, entry_id: str) -> ConfigEntry | None:
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.entry_id == entry_id:
            return entry
    return None


def _get_runtime_coordinator(hass: HomeAssistant, entry_id: str) -> ApcEnterpriseCoordinator | None:
    runtime = hass.data.get(DOMAIN, {}).get(entry_id)
    if not runtime:
        return None
    return runtime.get(RUNTIME_COORDINATOR)


async def _setup_services(hass: HomeAssistant) -> None:
    async def _handle_set_oid(call: ServiceCall) -> None:
        coordinator = _get_runtime_coordinator(hass, call.data["entry_id"])
        if coordinator is None:
            raise ApcSnmpError("Unknown entry_id")
        await coordinator.async_set_oid(call.data["oid"], int(call.data["value"]))

    async def _handle_control_action(call: ServiceCall) -> None:
        coordinator = _get_runtime_coordinator(hass, call.data["entry_id"])
        if coordinator is None:
            raise ApcSnmpError("Unknown entry_id")
        uid = call.data["control_uid"]
        action = call.data["action"]
        target = next((control for control in coordinator.controls if control.uid == uid), None)
        if target is None:
            raise ApcSnmpError(f"Unknown control_uid: {uid}")
        if action == "cycle":
            await coordinator.async_cycle_control(target)
            return
        await coordinator.async_set_control(target, state=(action == "on"))

    async_register_admin_service(hass, DOMAIN, SERVICE_SET_OID, _handle_set_oid, SET_OID_SCHEMA)
    async_register_admin_service(
        hass, DOMAIN, SERVICE_CONTROL_ACTION, _handle_control_action, CONTROL_ACTION_SCHEMA
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up APC Rack Power entry."""
    hass.data.setdefault(DOMAIN, {})
    if not hass.data[DOMAIN].get("services_ready"):
        await _setup_services(hass)
        hass.data[DOMAIN]["services_ready"] = True

    options = dict(entry.options)
    data = dict(entry.data)
    community = str(data.get(CONF_COMMUNITY, DEFAULT_COMMUNITY))
    write_community = str(data.get(CONF_WRITE_COMMUNITY, community))
    scan_interval = int(options.get(CONF_SCAN_INTERVAL, data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)))
    timeout = int(options.get(CONF_TIMEOUT, data.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)))
    retries = int(options.get(CONF_RETRIES, data.get(CONF_RETRIES, DEFAULT_RETRIES)))
    custom_oids = str(options.get(CONF_CUSTOM_OIDS, data.get(CONF_CUSTOM_OIDS, "")))

    snmp = ApcSnmpClient(
        host=str(data[CONF_HOST]),
        community=community,
        write_community=write_community,
        port=int(data.get(CONF_PORT, DEFAULT_PORT)),
        timeout=timeout,
        retries=retries,
    )
    coordinator = ApcEnterpriseCoordinator(
        hass=hass,
        entry_id=entry.entry_id,
        name=str(data.get(CONF_NAME, DEFAULT_NAME)),
        snmp_client=snmp,
        scan_interval=scan_interval,
        custom_metrics=_parse_custom_oids(custom_oids),
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {RUNTIME_COORDINATOR: coordinator}
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload APC Rack Power entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        remaining = [item for item in hass.config_entries.async_entries(DOMAIN) if item.entry_id != entry.entry_id]
        if not remaining:
            if hass.services.has_service(DOMAIN, SERVICE_SET_OID):
                hass.services.async_remove(DOMAIN, SERVICE_SET_OID)
            if hass.services.has_service(DOMAIN, SERVICE_CONTROL_ACTION):
                hass.services.async_remove(DOMAIN, SERVICE_CONTROL_ACTION)
            hass.data[DOMAIN]["services_ready"] = False
    return unload_ok

