"""Trap decoding/dispatch and diagnostics redaction."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
import socket
from typing import Any

from homeassistant.core import Event, HomeAssistant
from pysnmp.hlapi.v3arch.asyncio import (
    CommunityData,
    ContextData,
    NotificationType,
    ObjectIdentity,
    ObjectType,
    OctetString,
    SnmpEngine,
    UdpTransportTarget,
    UsmUserData,
    send_notification,
    usmAesCfb128Protocol,
    usmHMACSHAAuthProtocol,
)
import pytest
from pytest_homeassistant_custom_component.components.diagnostics import get_diagnostics_for_config_entry
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.apc_rack_power.const import EVENT_TRAP
from custom_components.apc_rack_power.snmp_client import SnmpCredentials
from custom_components.apc_rack_power.traps import TrapInfo, TrapServer, engine_id_bytes

from .conftest import FakeAgent, make_entry

V3_ENGINE_ID = bytes.fromhex("8000013e030000000000a1")
V3_CREDS = SnmpCredentials(
    "v3",
    v3_username="ha",
    v3_auth_protocol="sha",
    v3_auth_passphrase="authpass123",
    v3_priv_protocol="aes",
    v3_priv_passphrase="privpass123",
)


async def _send(port: int, auth: Any, engine_id: bytes | None = None) -> None:
    engine = SnmpEngine(OctetString(engine_id)) if engine_id else SnmpEngine()
    target = await UdpTransportTarget.create(("127.0.0.1", port))
    await send_notification(
        engine,
        auth,
        target,
        ContextData(),
        "trap",
        NotificationType(ObjectIdentity("1.3.6.1.4.1.318.0.636")).add_varbinds(
            ObjectType(ObjectIdentity("1.3.6.1.4.1.318.2.3.1.0"), OctetString("Outlet 24 off"))
        ),
    )
    await asyncio.sleep(0.3)
    engine.close_dispatcher()


@pytest.fixture
async def trap_server(
    hass: HomeAssistant, socket_enabled: None
) -> AsyncGenerator[tuple[TrapServer, int, list[TrapInfo]]]:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = TrapServer(port)
    await server.async_start(hass, "127.0.0.1")
    received: list[TrapInfo] = []
    server.register("entry", {"127.0.0.1"}, received.append, "public", V3_CREDS, V3_ENGINE_ID)
    yield server, port, received
    server.unregister("entry")
    server.stop()


async def test_receives_v3_trap(trap_server: tuple[TrapServer, int, list[TrapInfo]]) -> None:
    """An authenticated and encrypted SNMPv3 trap of the entry's user is accepted."""
    _server, port, received = trap_server
    auth = UsmUserData(
        "ha", "authpass123", "privpass123", authProtocol=usmHMACSHAAuthProtocol, privProtocol=usmAesCfb128Protocol
    )
    await _send(port, auth, V3_ENGINE_ID)
    assert len(received) == 1
    assert received[0].trap_oid == "1.3.6.1.4.1.318.0.636"
    assert received[0].varbinds == {"1.3.6.1.4.1.318.2.3.1.0": "Outlet 24 off"}


async def test_rejects_v3_trap_with_wrong_key(trap_server: tuple[TrapServer, int, list[TrapInfo]]) -> None:
    _server, port, received = trap_server
    auth = UsmUserData(
        "ha", "wrongpass99", "privpass123", authProtocol=usmHMACSHAAuthProtocol, privProtocol=usmAesCfb128Protocol
    )
    await _send(port, auth, V3_ENGINE_ID)
    assert received == []


async def test_v2c_trap_checks_community(trap_server: tuple[TrapServer, int, list[TrapInfo]]) -> None:
    _server, port, received = trap_server
    await _send(port, CommunityData("wrong", mpModel=1))
    assert received == []
    await _send(port, CommunityData("public", mpModel=1))
    assert [trap.trap_oid for trap in received] == ["1.3.6.1.4.1.318.0.636"]


def test_engine_id_conversion() -> None:
    assert engine_id_bytes("0x8000013e0328298697 85e0".replace(" ", "")) == bytes.fromhex("8000013e032829869785e0")
    assert engine_id_bytes("not an id") is None


async def test_trap_fires_event_and_refreshes(hass: HomeAssistant, agent: FakeAgent) -> None:
    agent.use("ups")
    entry = make_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    events: list[Event] = []
    hass.bus.async_listen(EVENT_TRAP, events.append)
    entry.runtime_data.handle_trap(
        TrapInfo("192.0.2.10", "1.3.6.1.4.1.318.0.5", {"1.3.6.1.4.1.318.2.3.3.0": "UPS: On battery power"})
    )
    await hass.async_block_till_done()
    assert events[0].data["trap_oid"] == "1.3.6.1.4.1.318.0.5"
    assert events[0].data["message"] == "UPS: On battery power"
    assert entry.runtime_data.trap_count == 1


async def test_diagnostics_redacts_credentials(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, agent: FakeAgent
) -> None:
    agent.use("ups")
    entry = make_entry(write_community="private")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result: dict[str, Any] = await get_diagnostics_for_config_entry(hass, hass_client, entry)
    assert result["data"]["host"] == "**REDACTED**"
    assert result["data"]["community"] == "**REDACTED**"
    assert result["data"]["write_community"] == "**REDACTED**"
    assert result["metrics"]["ups_serial_number"] == "**REDACTED**"
    assert result["metrics"]["sys_descr"] == "**REDACTED**"
    assert result["metrics"]["ups_output_power"] == 228
    assert "public" not in str(result)
    assert "private" not in str(result)
