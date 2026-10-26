"""Config, options, reconfigure and reauth flows."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo

from custom_components.apc_rack_power.const import DOMAIN
from custom_components.apc_rack_power.snmp_client import ApcSnmpAuthError

from .conftest import FakeAgent, make_entry

USER_INPUT = {"host": "192.0.2.10", "name": "Rack UPS", "port": 161}


async def _start(hass: HomeAssistant, version: str) -> dict:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    return await hass.config_entries.flow.async_configure(result["flow_id"], {**USER_INPUT, "snmp_version": version})


async def test_user_v2c(hass: HomeAssistant, agent: FakeAgent) -> None:
    """v2c asks for communities and warns about plain text."""
    agent.use("ups")
    result = await _start(hass, "v2c")
    assert result["step_id"] == "community"
    assert result["description_placeholders"] == {"version": "V2C"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"community": "public", "write_community": "private"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Rack UPS"
    assert result["data"] == {
        "host": "192.0.2.10",
        "name": "Rack UPS",
        "port": 161,
        "snmp_version": "v2c",
        "community": "public",
        "write_community": "private",
    }
    assert result["result"].unique_id == "192.0.2.10"


async def test_user_v3(hass: HomeAssistant, agent: FakeAgent) -> None:
    """v3 validates the passphrases before connecting."""
    agent.use("ups")
    result = await _start(hass, "v3")
    assert result["step_id"] == "v3"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "v3_username": "ha",
            "v3_auth_protocol": "sha256",
            "v3_auth_passphrase": "short",
            "v3_priv_protocol": "aes256",
            "v3_priv_passphrase": "",
        },
    )
    assert result["errors"] == {
        "v3_auth_passphrase": "passphrase_too_short",
        "v3_priv_passphrase": "passphrase_too_short",
    }

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "v3_username": "ha",
            "v3_auth_protocol": "sha256",
            "v3_auth_passphrase": "authpass123",
            "v3_priv_protocol": "aes256",
            "v3_priv_passphrase": "privpass123",
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["v3_auth_protocol"] == "sha256"
    assert "community" not in result["data"]


async def test_user_cannot_connect(hass: HomeAssistant, agent: FakeAgent) -> None:
    """No answer shows cannot_connect."""
    result = await _start(hass, "v2c")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"community": "public"})
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_invalid_auth(hass: HomeAssistant, agent: FakeAgent) -> None:
    """Rejected v3 credentials show invalid_auth."""
    agent.get_error = ApcSnmpAuthError("wrong digest")
    result = await _start(hass, "v3")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "v3_username": "ha",
            "v3_auth_protocol": "sha",
            "v3_auth_passphrase": "authpass123",
            "v3_priv_protocol": "none",
        },
    )
    assert result["errors"] == {"base": "invalid_auth"}


async def test_already_configured(hass: HomeAssistant, agent: FakeAgent) -> None:
    """The same host cannot be added twice."""
    make_entry().add_to_hass(hass)
    result = await _start(hass, "v2c")
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_dhcp_discovery(hass: HomeAssistant, agent: FakeAgent) -> None:
    """A discovered card pre-fills the host."""
    agent.use("pdu")
    info = DhcpServiceInfo(ip="192.0.2.30", hostname="apc537ff3", macaddress="00c0b7aabbcc")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_DHCP}, data=info
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    schema_defaults = {str(key): key.default() for key in result["data_schema"].schema if hasattr(key, "default")}
    assert schema_defaults["host"] == "192.0.2.30"

    make_entry(host="192.0.2.31").add_to_hass(hass)
    info = DhcpServiceInfo(ip="192.0.2.31", hostname="apc", macaddress="282986aabbcc")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_DHCP}, data=info
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure_to_v3(hass: HomeAssistant, agent: FakeAgent) -> None:
    """Reconfigure switches an entry from v2c to v3."""
    agent.use("ups")
    entry = make_entry(write_community="private")
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "192.0.2.10", "port": 161, "snmp_version": "v3"}
    )
    assert result["step_id"] == "v3"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "v3_username": "ha",
            "v3_auth_protocol": "sha512",
            "v3_auth_passphrase": "authpass123",
            "v3_priv_protocol": "aes",
            "v3_priv_passphrase": "privpass123",
        },
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data["snmp_version"] == "v3"
    assert entry.data["v3_auth_protocol"] == "sha512"
    assert "community" not in entry.data
    assert "write_community" not in entry.data
    assert entry.data["name"] == "UPS"


async def test_reauth(hass: HomeAssistant, agent: FakeAgent) -> None:
    """Reauth asks for the credentials of the configured version."""
    agent.use("ups")
    entry = make_entry(snmp_version="v3", v3_username="ha", v3_auth_protocol="sha", v3_auth_passphrase="oldpass123")
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "v3"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "v3_username": "ha",
            "v3_auth_protocol": "sha",
            "v3_auth_passphrase": "newpass123",
            "v3_priv_protocol": "none",
        },
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data["v3_auth_passphrase"] == "newpass123"


async def test_options(hass: HomeAssistant, agent: FakeAgent) -> None:
    """Options store polling and trap settings."""
    agent.use("ups")
    entry = make_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "polling": {"scan_interval": 60, "timeout": 5, "retries": 2},
            "traps": {"trap_enabled": False, "trap_port": 1162, "trap_community": "public"},
            "advanced": {"custom_oids": " x=.1.3.6.1.2.1.1.5.0 "},
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["scan_interval"] == 60
    assert entry.options["trap_port"] == 1162
    assert entry.options["custom_oids"] == "x=.1.3.6.1.2.1.1.5.0"
