"""Config flow for APC Rack Power integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, ConfigFlow
from homeassistant.const import CONF_HOST
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_COMMUNITY,
    CONF_CUSTOM_OIDS,
    CONF_NAME,
    CONF_PDU_NOMINAL_WATTS,
    CONF_PORT,
    CONF_RETRIES,
    CONF_SCAN_INTERVAL,
    CONF_TEMP_SCALE,
    CONF_TIMEOUT,
    CONF_WRITE_COMMUNITY,
    DEFAULT_COMMUNITY,
    DEFAULT_NAME,
    DEFAULT_PDU_NOMINAL_WATTS,
    DEFAULT_PORT,
    DEFAULT_RETRIES,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TEMP_SCALE,
    DEFAULT_TIMEOUT,
    DOMAIN,
)
from .device_profile import DEVICE_UPS, detect_device_kind
from .snmp_client import ApcSnmpClient, ApcSnmpError


async def _test_connection(
    hass,
    host: str,
    port: int,
    community: str,
    write_community: str,
    timeout: int,
    retries: int,
) -> bool:
    client = ApcSnmpClient(
        host=host,
        community=community,
        write_community=write_community,
        port=port,
        timeout=timeout,
        retries=retries,
    )
    try:
        value = await client.get(".1.3.6.1.2.1.1.1.0")
    except ApcSnmpError:
        return False
    return value is not None


class ApcEnterpriseOptionsFlow(config_entries.OptionsFlow):
    """Options flow for APC Rack Power."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        data = dict(self._entry.data)
        options = dict(self._entry.options)
        schema_fields: dict[Any, Any] = {
            vol.Required(
                CONF_SCAN_INTERVAL,
                default=options.get(
                    CONF_SCAN_INTERVAL, data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
                ),
            ): vol.All(vol.Coerce(int), vol.Range(min=5, max=600)),
            vol.Required(
                CONF_TIMEOUT,
                default=options.get(CONF_TIMEOUT, data.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)),
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=30)),
            vol.Required(
                CONF_RETRIES,
                default=options.get(CONF_RETRIES, data.get(CONF_RETRIES, DEFAULT_RETRIES)),
            ): vol.All(vol.Coerce(int), vol.Range(min=0, max=10)),
            vol.Optional(
                CONF_CUSTOM_OIDS,
                default=options.get(CONF_CUSTOM_OIDS, data.get(CONF_CUSTOM_OIDS, "")),
            ): str,
            vol.Required(
                CONF_TEMP_SCALE,
                default=options.get(CONF_TEMP_SCALE, data.get(CONF_TEMP_SCALE, DEFAULT_TEMP_SCALE)),
            ): vol.In({"celsius": "celsius", "fahrenheit": "fahrenheit"}),
        }

        coordinator = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {}).get("coordinator")
        metrics = coordinator.data.metrics if coordinator and coordinator.data else {}
        device_kind = detect_device_kind(metrics)
        if device_kind != DEVICE_UPS:
            schema_fields[
                vol.Required(
                    CONF_PDU_NOMINAL_WATTS,
                    default=options.get(
                        CONF_PDU_NOMINAL_WATTS,
                        data.get(CONF_PDU_NOMINAL_WATTS, DEFAULT_PDU_NOMINAL_WATTS),
                    ),
                )
            ] = vol.All(vol.Coerce(int), vol.Range(min=0, max=200000))

        schema = vol.Schema(schema_fields)
        return self.async_show_form(step_id="init", data_schema=schema)


class ApcEnterpriseConfigFlow(ConfigFlow, domain=DOMAIN):
    """Main config flow."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = str(user_input[CONF_HOST]).strip()
            await self.async_set_unique_id(host)
            self._abort_if_unique_id_configured()

            ok = await _test_connection(
                self.hass,
                host=host,
                port=int(user_input[CONF_PORT]),
                community=str(user_input[CONF_COMMUNITY]),
                write_community=str(user_input[CONF_WRITE_COMMUNITY]),
                timeout=int(user_input[CONF_TIMEOUT]),
                retries=int(user_input[CONF_RETRIES]),
            )
            if ok:
                return self.async_create_entry(
                    title=str(user_input[CONF_NAME]),
                    data=user_input,
                )
            errors["base"] = "cannot_connect"

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
                vol.Required(CONF_COMMUNITY, default=DEFAULT_COMMUNITY): str,
                vol.Required(CONF_WRITE_COMMUNITY, default=DEFAULT_COMMUNITY): str,
                vol.Required(CONF_PORT, default=DEFAULT_PORT): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=65535)
                ),
                vol.Required(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
                    vol.Coerce(int), vol.Range(min=5, max=600)
                ),
                vol.Required(CONF_TIMEOUT, default=DEFAULT_TIMEOUT): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=30)
                ),
                vol.Required(CONF_RETRIES, default=DEFAULT_RETRIES): vol.All(
                    vol.Coerce(int), vol.Range(min=0, max=10)
                ),
                vol.Optional(CONF_CUSTOM_OIDS, default=""): str,
                vol.Required(CONF_PDU_NOMINAL_WATTS, default=DEFAULT_PDU_NOMINAL_WATTS): vol.All(
                    vol.Coerce(int), vol.Range(min=0, max=200000)
                ),
                vol.Required(CONF_TEMP_SCALE, default=DEFAULT_TEMP_SCALE): vol.In(
                    {"celsius": "celsius", "fahrenheit": "fahrenheit"}
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> ApcEnterpriseOptionsFlow:
        return ApcEnterpriseOptionsFlow(config_entry)

