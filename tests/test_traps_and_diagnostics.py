"""Trap decoding/dispatch and diagnostics redaction."""

from __future__ import annotations

from typing import Any

from homeassistant.core import Event, HomeAssistant
from pyasn1.codec.ber import encoder
from pysnmp.proto import api
from pytest_homeassistant_custom_component.components.diagnostics import get_diagnostics_for_config_entry
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.apc_rack_power.const import EVENT_TRAP
from custom_components.apc_rack_power.traps import TrapInfo, TrapServer, decode_trap

from .conftest import FakeAgent, make_entry


def _v1_trap(community: str = "public") -> bytes:
    proto = api.PROTOCOL_MODULES[api.SNMP_VERSION_1]
    pdu = proto.TrapPDU()
    proto.apiTrapPDU.set_defaults(pdu)
    proto.apiTrapPDU.set_enterprise(pdu, (1, 3, 6, 1, 4, 1, 318))
    proto.apiTrapPDU.set_generic_trap(pdu, 6)
    proto.apiTrapPDU.set_specific_trap(pdu, 5)
    proto.apiTrapPDU.set_varbinds(
        pdu, [(proto.ObjectIdentifier("1.3.6.1.4.1.318.2.3.1.0"), proto.OctetString("UPS: On battery power"))]
    )
    message = proto.Message()
    proto.apiMessage.set_defaults(message)
    proto.apiMessage.set_community(message, community)
    proto.apiMessage.set_pdu(message, pdu)
    return encoder.encode(message)


def _v2c_trap() -> bytes:
    proto = api.PROTOCOL_MODULES[api.SNMP_VERSION_2C]
    pdu = proto.SNMPv2TrapPDU()
    proto.apiTrapPDU.set_defaults(pdu)
    proto.apiTrapPDU.set_varbinds(
        pdu,
        [
            (proto.ObjectIdentifier("1.3.6.1.2.1.1.3.0"), proto.TimeTicks(12345)),
            (proto.ObjectIdentifier("1.3.6.1.6.3.1.1.4.1.0"), proto.ObjectIdentifier("1.3.6.1.4.1.318.0.636")),
            (proto.ObjectIdentifier("1.3.6.1.4.1.318.2.3.1.0"), proto.OctetString("Outlet 3 off")),
        ],
    )
    message = proto.Message()
    proto.apiMessage.set_defaults(message)
    proto.apiMessage.set_community(message, "public")
    proto.apiMessage.set_pdu(message, pdu)
    return encoder.encode(message)


def test_decode_v1_trap() -> None:
    trap = decode_trap(_v1_trap(), "192.0.2.10")
    assert trap is not None
    assert trap.version == "v1"
    assert trap.trap_oid == "1.3.6.1.4.1.318.0.5"
    assert trap.varbinds == {"1.3.6.1.4.1.318.2.3.1.0": "UPS: On battery power"}


def test_decode_v2c_trap() -> None:
    trap = decode_trap(_v2c_trap(), "192.0.2.10")
    assert trap is not None
    assert trap.trap_oid == "1.3.6.1.4.1.318.0.636"
    assert trap.varbinds["1.3.6.1.4.1.318.2.3.1.0"] == "Outlet 3 off"


def test_dispatch_checks_sender_and_community() -> None:
    server = TrapServer(1162)
    received: list[TrapInfo] = []
    server.register("entry", {"192.0.2.10"}, "public", received.append)
    server.handle_datagram(_v1_trap(), "192.0.2.99")  # unknown sender
    server.handle_datagram(_v1_trap("wrong"), "192.0.2.10")  # wrong community
    server.handle_datagram(b"garbage", "192.0.2.10")  # not SNMP
    server.handle_datagram(_v1_trap(), "192.0.2.10")
    assert len(received) == 1


async def test_trap_fires_event_and_refreshes(hass: HomeAssistant, agent: FakeAgent) -> None:
    agent.use("ups")
    entry = make_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    events: list[Event] = []
    hass.bus.async_listen(EVENT_TRAP, events.append)
    trap = decode_trap(_v1_trap(), "192.0.2.10")
    assert trap is not None
    entry.runtime_data.handle_trap(trap)
    await hass.async_block_till_done()
    assert events[0].data["trap_oid"] == "1.3.6.1.4.1.318.0.5"
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
