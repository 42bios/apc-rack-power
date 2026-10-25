"""Config flow for APC Rack Power."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.config_entries import (
    SOURCE_REAUTH,
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
import voluptuous as vol

from . import credentials_from
from .const import (
    AUTH_PROTOCOLS,
    CONF_COMMUNITY,
    CONF_CUSTOM_OIDS,
    CONF_NAME,
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
    DEFAULT_NAME,
    DEFAULT_PORT,
    DEFAULT_RETRIES,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SNMP_VERSION,
    DEFAULT_TIMEOUT,
    DEFAULT_TRAP_COMMUNITY,
    DEFAULT_TRAP_PORT,
    DOMAIN,
    PRIV_PROTOCOLS,
    SNMP_V3,
    SNMP_VERSIONS,
)
from .snmp_client import ApcSnmpAuthError, ApcSnmpClient, ApcSnmpError

_PASSWORD = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
_TEXT = TextSelector()


def _select(options: list[str], key: str) -> SelectSelector:
    return SelectSelector(SelectSelectorConfig(options=options, translation_key=key, mode=SelectSelectorMode.DROPDOWN))


def _number(minimum: int, maximum: int, unit: str | None = None) -> NumberSelector:
    config = NumberSelectorConfig(min=minimum, max=maximum, step=1, mode=NumberSelectorMode.BOX)
    if unit:
        config["unit_of_measurement"] = unit
    return NumberSelector(config)


def _connection_schema(defaults: Mapping[str, Any], with_name: bool) -> vol.Schema:
    fields: dict[Any, Any] = {vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): _TEXT}
    if with_name:
        fields[vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, DEFAULT_NAME))] = _TEXT
    fields[vol.Required(CONF_PORT, default=int(defaults.get(CONF_PORT, DEFAULT_PORT)))] = _number(1, 65535)
    fields[vol.Required(CONF_SNMP_VERSION, default=defaults.get(CONF_SNMP_VERSION, DEFAULT_SNMP_VERSION))] = _select(
        SNMP_VERSIONS, "snmp_version"
    )
    return vol.Schema(fields)


def _community_schema(defaults: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_COMMUNITY, default=defaults.get(CONF_COMMUNITY, DEFAULT_COMMUNITY)): _PASSWORD,
            vol.Optional(CONF_WRITE_COMMUNITY, default=defaults.get(CONF_WRITE_COMMUNITY, "")): _PASSWORD,
        }
    )


def _v3_schema(defaults: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_V3_USERNAME, default=defaults.get(CONF_V3_USERNAME, "")): _TEXT,
            vol.Required(CONF_V3_AUTH_PROTOCOL, default=defaults.get(CONF_V3_AUTH_PROTOCOL, "sha256")): _select(
                AUTH_PROTOCOLS, "auth_protocol"
            ),
            vol.Optional(CONF_V3_AUTH_PASSPHRASE, default=defaults.get(CONF_V3_AUTH_PASSPHRASE, "")): _PASSWORD,
            vol.Required(CONF_V3_PRIV_PROTOCOL, default=defaults.get(CONF_V3_PRIV_PROTOCOL, "aes")): _select(
                PRIV_PROTOCOLS, "priv_protocol"
            ),
            vol.Optional(CONF_V3_PRIV_PASSPHRASE, default=defaults.get(CONF_V3_PRIV_PASSPHRASE, "")): _PASSWORD,
        }
    )


def _validate_v3(user_input: Mapping[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    auth = str(user_input.get(CONF_V3_AUTH_PROTOCOL, "none"))
    priv = str(user_input.get(CONF_V3_PRIV_PROTOCOL, "none"))
    if not str(user_input.get(CONF_V3_USERNAME, "")).strip():
        errors[CONF_V3_USERNAME] = "username_required"
    if auth != "none" and len(str(user_input.get(CONF_V3_AUTH_PASSPHRASE, ""))) < 8:
        errors[CONF_V3_AUTH_PASSPHRASE] = "passphrase_too_short"
    if priv != "none":
        if auth == "none":
            errors[CONF_V3_PRIV_PROTOCOL] = "priv_requires_auth"
        elif len(str(user_input.get(CONF_V3_PRIV_PASSPHRASE, ""))) < 8:
            errors[CONF_V3_PRIV_PASSPHRASE] = "passphrase_too_short"
    return errors


class ApcConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up an APC network management card."""

    VERSION = 1
    MINOR_VERSION = 2

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> ApcOptionsFlow:
        return ApcOptionsFlow()

    # ------------------------------------------------------------ entry points

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Host and SNMP version."""
        if user_input is not None:
            host = str(user_input[CONF_HOST]).strip()
            await self.async_set_unique_id(host)
            self._abort_if_unique_id_configured()
            self._data.update(user_input, **{CONF_HOST: host, CONF_PORT: int(user_input[CONF_PORT])})
            return await self._async_step_credentials()
        return self.async_show_form(step_id="user", data_schema=_connection_schema(self._data, with_name=True))

    async def async_step_dhcp(self, discovery_info: DhcpServiceInfo) -> ConfigFlowResult:
        """An APC network card asked for an IP address."""
        host = discovery_info.ip
        await self.async_set_unique_id(host)
        self._abort_if_unique_id_configured()
        self._async_abort_entries_match({CONF_HOST: host})
        self._data[CONF_HOST] = host
        self.context["title_placeholders"] = {"host": host}
        return await self.async_step_user()

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Change address, port, SNMP version or credentials."""
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            host = str(user_input[CONF_HOST]).strip()
            if host != entry.data[CONF_HOST]:
                await self.async_set_unique_id(host)
                self._abort_if_unique_id_configured()
            self._data = {**entry.data, **user_input, CONF_HOST: host, CONF_PORT: int(user_input[CONF_PORT])}
            return await self._async_step_credentials()
        return self.async_show_form(step_id="reconfigure", data_schema=_connection_schema(entry.data, with_name=False))

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """The device rejected the stored credentials."""
        self._data = dict(entry_data)
        return await self._async_step_credentials()

    # ------------------------------------------------------------- credentials

    async def _async_step_credentials(self) -> ConfigFlowResult:
        if self._data.get(CONF_SNMP_VERSION) == SNMP_V3:
            return await self.async_step_v3()
        return await self.async_step_community()

    async def async_step_community(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Community strings for SNMPv1/v2c."""
        errors: dict[str, str] = {}
        if user_input is not None:
            candidate = {**self._data, **user_input}
            errors = await self._async_test(candidate)
            if not errors:
                return self._async_finish(candidate)
        return self.async_show_form(
            step_id="community",
            data_schema=self.add_suggested_values_to_schema(_community_schema(self._data), user_input or self._data),
            errors=errors,
            description_placeholders={"version": str(self._data.get(CONF_SNMP_VERSION, "v2c")).upper()},
        )

    async def async_step_v3(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """User and keys for SNMPv3."""
        errors: dict[str, str] = {}
        if user_input is not None:
            candidate = {**self._data, **user_input}
            errors = _validate_v3(candidate) or await self._async_test(candidate)
            if not errors:
                return self._async_finish(candidate)
        return self.async_show_form(
            step_id="v3",
            data_schema=self.add_suggested_values_to_schema(_v3_schema(self._data), user_input or self._data),
            errors=errors,
        )

    async def _async_test(self, data: Mapping[str, Any]) -> dict[str, str]:
        client = await ApcSnmpClient.async_create(
            self.hass,
            host=str(data[CONF_HOST]),
            port=int(data.get(CONF_PORT, DEFAULT_PORT)),
            timeout=DEFAULT_TIMEOUT,
            retries=DEFAULT_RETRIES,
            credentials=credentials_from(dict(data)),
        )
        try:
            value = await client.get(".1.3.6.1.2.1.1.1.0")
        except ApcSnmpAuthError:
            return {"base": "invalid_auth"}
        except ApcSnmpError:
            return {"base": "cannot_connect"}
        return {} if value else {"base": "cannot_connect"}

    def _async_finish(self, data: dict[str, Any]) -> ConfigFlowResult:
        # Keep only the fields of the chosen SNMP version.
        is_v3 = data.get(CONF_SNMP_VERSION) == SNMP_V3
        unused = (
            (CONF_COMMUNITY, CONF_WRITE_COMMUNITY)
            if is_v3
            else (
                CONF_V3_USERNAME,
                CONF_V3_AUTH_PROTOCOL,
                CONF_V3_AUTH_PASSPHRASE,
                CONF_V3_PRIV_PROTOCOL,
                CONF_V3_PRIV_PASSPHRASE,
            )
        )
        clean = {key: value for key, value in data.items() if key not in unused}

        if self.source == SOURCE_RECONFIGURE:
            entry = self._get_reconfigure_entry()
            new_data = {key: value for key, value in entry.data.items() if key not in CONNECTION_KEYS}
            new_data.update(clean)
            return self.async_update_reload_and_abort(
                entry,
                unique_id=str(clean[CONF_HOST]),
                data=new_data,
                options={key: value for key, value in entry.options.items() if key not in CONNECTION_KEYS},
            )
        if self.source == SOURCE_REAUTH:
            entry = self._get_reauth_entry()
            new_data = {key: value for key, value in entry.data.items() if key not in CONNECTION_KEYS}
            new_data.update(clean)
            return self.async_update_reload_and_abort(entry, data=new_data)
        return self.async_create_entry(title=str(clean.get(CONF_NAME) or DEFAULT_NAME), data=clean)


class ApcOptionsFlow(OptionsFlow):
    """Polling and trap settings."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            data = dict(user_input)
            for key in (CONF_SCAN_INTERVAL, CONF_TIMEOUT, CONF_RETRIES, CONF_TRAP_PORT):
                data[key] = int(data[key])
            return self.async_create_entry(data=data)

        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL, default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
                ): _number(5, 600, "s"),
                vol.Required(CONF_TIMEOUT, default=options.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)): _number(1, 30, "s"),
                vol.Required(CONF_RETRIES, default=options.get(CONF_RETRIES, DEFAULT_RETRIES)): _number(0, 10),
                vol.Optional(CONF_CUSTOM_OIDS, default=options.get(CONF_CUSTOM_OIDS, "")): TextSelector(
                    TextSelectorConfig(multiline=True)
                ),
                vol.Required(CONF_TRAP_ENABLED, default=options.get(CONF_TRAP_ENABLED, False)): BooleanSelector(),
                vol.Required(CONF_TRAP_PORT, default=options.get(CONF_TRAP_PORT, DEFAULT_TRAP_PORT)): _number(1, 65535),
                vol.Optional(
                    CONF_TRAP_COMMUNITY, default=options.get(CONF_TRAP_COMMUNITY, DEFAULT_TRAP_COMMUNITY)
                ): _PASSWORD,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
