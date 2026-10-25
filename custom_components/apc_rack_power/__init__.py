"""The APC Rack Power integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, issue_registry as ir
from homeassistant.helpers.service import async_register_admin_service
from homeassistant.helpers.typing import ConfigType
import voluptuous as vol

from .const import (
    CONF_COMMUNITY,
    CONF_CUSTOM_OIDS,
    CONF_PORT,
    CONF_RETRIES,
    CONF_SCAN_INTERVAL,
    CONF_SNMP_VERSION,
    CONF_TIMEOUT,
    CONF_TRAP_COMMUNITY,
    CONF_TRAP_ENABLED,
    CONF_TRAP_PORT,
    CONF_V3_AUTH_PASSPHRASE,
    CONF_V3_AUTH_PROTOCOL,
    CONF_V3_PRIV_PASSPHRASE,
    CONF_V3_PRIV_PROTOCOL,
    CONF_V3_USERNAME,
    CONF_WRITE_COMMUNITY,
    CONNECTION_KEYS,
    DEFAULT_COMMUNITY,
    DEFAULT_PORT,
    DEFAULT_RETRIES,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SNMP_VERSION,
    DEFAULT_TIMEOUT,
    DEFAULT_TRAP_COMMUNITY,
    DEFAULT_TRAP_PORT,
    DOMAIN,
    LEGACY_OPTION_KEYS,
    PLATFORMS,
    POLLING_KEYS,
    SERVICE_CONTROL_ACTION,
    SERVICE_SET_OID,
    MetricDef,
)
from .coordinator import ApcCoordinator
from .snmp_client import ApcSnmpClient, SnmpCredentials
from .traps import async_register_trap_handler

_LOGGER = logging.getLogger(__name__)

type ApcConfigEntry = ConfigEntry[ApcCoordinator]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

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


def parse_custom_oids(raw: str | None) -> list[MetricDef]:
    """Parse "key=oid" lines from the options."""
    defs: list[MetricDef] = []
    for line in (raw or "").splitlines():
        cleaned = line.strip()
        if not cleaned or cleaned.startswith("#") or "=" not in cleaned:
            continue
        key, oid = cleaned.split("=", 1)
        metric_key = key.strip().lower().replace(" ", "_")
        metric_oid = oid.strip()
        if metric_key and metric_oid:
            defs.append(MetricDef(metric_key, ((metric_oid, 1.0),), allow_negative=True))
    return defs


def credentials_from(data: dict) -> SnmpCredentials:
    """Build SNMP credentials from entry data or flow input."""
    return SnmpCredentials(
        version=str(data.get(CONF_SNMP_VERSION, DEFAULT_SNMP_VERSION)),
        community=str(data.get(CONF_COMMUNITY, DEFAULT_COMMUNITY) or ""),
        write_community=str(data.get(CONF_WRITE_COMMUNITY, "") or ""),
        v3_username=str(data.get(CONF_V3_USERNAME, "") or ""),
        v3_auth_protocol=str(data.get(CONF_V3_AUTH_PROTOCOL, "none") or "none"),
        v3_auth_passphrase=str(data.get(CONF_V3_AUTH_PASSPHRASE, "") or ""),
        v3_priv_protocol=str(data.get(CONF_V3_PRIV_PROTOCOL, "none") or "none"),
        v3_priv_passphrase=str(data.get(CONF_V3_PRIV_PASSPHRASE, "") or ""),
    )


def _get_coordinator(hass: HomeAssistant, entry_id: str) -> ApcCoordinator:
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN or not hasattr(entry, "runtime_data"):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="unknown_entry",
            translation_placeholders={"entry_id": entry_id},
        )
    return entry.runtime_data


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the services."""

    async def _handle_set_oid(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass, call.data["entry_id"])
        await coordinator.async_write(call.data["oid"], int(call.data["value"]))

    async def _handle_control_action(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass, call.data["entry_id"])
        uid = call.data["control_uid"]
        control = next((item for item in coordinator.controls if item.uid == uid), None)
        if control is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_control",
                translation_placeholders={"control_uid": uid},
            )
        action = call.data["action"]
        await coordinator.async_control(control, "reboot" if action == "cycle" else action)

    async_register_admin_service(hass, DOMAIN, SERVICE_SET_OID, _handle_set_oid, SET_OID_SCHEMA)
    async_register_admin_service(hass, DOMAIN, SERVICE_CONTROL_ACTION, _handle_control_action, CONTROL_ACTION_SCHEMA)
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Move credentials from options into data (1.1 -> 1.2)."""
    if entry.version > 1:
        return False
    if entry.version == 1 and entry.minor_version < 2:
        data = dict(entry.data)
        options = dict(entry.options)
        for key in CONNECTION_KEYS:
            if key in options:
                data[key] = options.pop(key)
        for key in POLLING_KEYS:
            if key in data:
                options.setdefault(key, data.pop(key))
        for key in LEGACY_OPTION_KEYS:
            data.pop(key, None)
            options.pop(key, None)
        hass.config_entries.async_update_entry(entry, data=data, options=options, minor_version=2)
        _LOGGER.debug("Migrated %s to version 1.2", entry.title)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ApcConfigEntry) -> bool:
    """Set up one APC device."""
    data = dict(entry.data)
    options = dict(entry.options)

    client = await ApcSnmpClient.async_create(
        hass,
        host=str(data[CONF_HOST]),
        port=int(data.get(CONF_PORT, DEFAULT_PORT)),
        timeout=int(options.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)),
        retries=int(options.get(CONF_RETRIES, DEFAULT_RETRIES)),
        credentials=credentials_from(data),
    )
    coordinator = ApcCoordinator(
        hass,
        entry,
        client,
        scan_interval=int(options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
        custom_metrics=parse_custom_oids(options.get(CONF_CUSTOM_OIDS)),
    )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await _async_setup_traps(hass, entry, coordinator)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_setup_traps(hass: HomeAssistant, entry: ApcConfigEntry, coordinator: ApcCoordinator) -> None:
    issue_id = f"trap_port_{entry.entry_id}"
    if not entry.options.get(CONF_TRAP_ENABLED, False):
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        return
    port = int(entry.options.get(CONF_TRAP_PORT, DEFAULT_TRAP_PORT))
    try:
        unregister = await async_register_trap_handler(
            hass,
            entry.entry_id,
            str(entry.data[CONF_HOST]),
            port,
            str(entry.options.get(CONF_TRAP_COMMUNITY, DEFAULT_TRAP_COMMUNITY)),
            coordinator.handle_trap,
        )
    except OSError as err:
        _LOGGER.warning("Cannot listen for SNMP traps on UDP port %s: %s", port, err)
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="trap_port",
            translation_placeholders={"name": entry.title, "port": str(port), "error": str(err)},
        )
        return
    ir.async_delete_issue(hass, DOMAIN, issue_id)
    entry.async_on_unload(unregister)


async def _async_update_listener(hass: HomeAssistant, entry: ApcConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ApcConfigEntry) -> bool:
    """Unload an entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ApcConfigEntry) -> None:
    """Remove the repair issues of a deleted entry."""
    for prefix in ("battery_replace", "write_failed", "trap_port"):
        ir.async_delete_issue(hass, DOMAIN, f"{prefix}_{entry.entry_id}")
