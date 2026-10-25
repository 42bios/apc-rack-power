"""SNMP trap receiver for APC Rack Power.

APC network cards send a trap the moment something happens (mains failure,
switch to battery, alarms, outlet changes). The receiver matches the sender
against the configured devices, fires an event and triggers an immediate poll,
so Home Assistant no longer waits for the next scan interval.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
import logging
import socket
from typing import Any

from homeassistant.core import HomeAssistant, callback
from pyasn1.codec.ber import decoder
from pyasn1.type import univ
from pysnmp.proto import api

from .const import DOMAIN
from .snmp_client import convert_value

_LOGGER = logging.getLogger(__name__)

DATA_TRAP_SERVERS = f"{DOMAIN}_trap_servers"

_SNMP_TRAP_OID = "1.3.6.1.6.3.1.1.4.1.0"
_GENERIC_TRAPS = "1.3.6.1.6.3.1.1.5"


@dataclass(slots=True, frozen=True)
class TrapInfo:
    """A decoded trap."""

    source: str
    version: str
    community: str
    trap_oid: str
    varbinds: dict[str, Any]


def decode_trap(data: bytes, source: str) -> TrapInfo | None:
    """Decode an SNMPv1/v2c trap; return None for anything else."""
    version = int(api.decodeMessageVersion(data))
    if version not in api.PROTOCOL_MODULES:
        return None
    proto = api.PROTOCOL_MODULES[version]
    message, _rest = decoder.decode(data, asn1Spec=proto.Message())
    community = str(proto.apiMessage.get_community(message))
    pdu = proto.apiMessage.get_pdu(message)

    if version == api.SNMP_VERSION_1:
        if not pdu.isSameTypeWith(proto.TrapPDU()):
            return None
        enterprise = str(proto.apiTrapPDU.get_enterprise(pdu))
        generic = int(proto.apiTrapPDU.get_generic_trap(pdu))
        specific = int(proto.apiTrapPDU.get_specific_trap(pdu))
        trap_oid = f"{enterprise}.0.{specific}" if generic == 6 else f"{_GENERIC_TRAPS}.{generic + 1}"
        var_binds = proto.apiTrapPDU.get_varbinds(pdu)
        label = "v1"
    else:
        if not pdu.isSameTypeWith(proto.SNMPv2TrapPDU()):
            return None
        var_binds = proto.apiTrapPDU.get_varbinds(pdu)
        trap_oid = ""
        label = "v2c"

    values: dict[str, Any] = {}
    for oid, value in var_binds:
        key = str(oid)
        # Values arrive as ObjectSyntax choices; take the innermost component.
        if isinstance(value, univ.Choice):
            value = value.getComponent(innerFlag=True)
        converted = convert_value(value)
        if key == _SNMP_TRAP_OID:
            trap_oid = str(converted)
            continue
        values[key] = converted
    return TrapInfo(source=source, version=label, community=community, trap_oid=trap_oid, varbinds=values)


class _TrapProtocol(asyncio.DatagramProtocol):
    def __init__(self, server: TrapServer) -> None:
        self._server = server

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self._server.handle_datagram(data, addr[0])


class TrapServer:
    """One UDP listener shared by all entries on the same port."""

    def __init__(self, port: int) -> None:
        self.port = port
        self._transport: asyncio.DatagramTransport | None = None
        # source ip -> {entry_id: (community, callback)}
        self._handlers: dict[str, dict[str, tuple[str, Callable[[TrapInfo], None]]]] = {}

    async def async_start(self) -> None:
        loop = asyncio.get_running_loop()
        transport, _protocol = await loop.create_datagram_endpoint(
            lambda: _TrapProtocol(self), local_addr=("0.0.0.0", self.port), family=socket.AF_INET
        )
        self._transport = transport

    def stop(self) -> None:
        if self._transport is not None:
            self._transport.close()
            self._transport = None

    @property
    def empty(self) -> bool:
        return not any(self._handlers.values())

    def register(self, entry_id: str, addresses: set[str], community: str, handler: Callable[[TrapInfo], None]) -> None:
        for address in addresses:
            self._handlers.setdefault(address, {})[entry_id] = (community, handler)

    def unregister(self, entry_id: str) -> None:
        for handlers in self._handlers.values():
            handlers.pop(entry_id, None)

    @callback
    def handle_datagram(self, data: bytes, source: str) -> None:
        handlers = self._handlers.get(source)
        if not handlers:
            _LOGGER.debug("Ignoring trap from unknown sender %s", source)
            return
        try:
            trap = decode_trap(data, source)
        except Exception as err:  # noqa: BLE001 - malformed datagrams must never break the listener
            _LOGGER.debug("Cannot decode trap from %s: %s", source, err)
            return
        if trap is None:
            return
        for community, handler in handlers.values():
            if community and trap.community != community:
                _LOGGER.debug("Ignoring trap from %s with unexpected community", source)
                continue
            handler(trap)


async def async_register_trap_handler(
    hass: HomeAssistant,
    entry_id: str,
    host: str,
    port: int,
    community: str,
    handler: Callable[[TrapInfo], None],
) -> Callable[[], None]:
    """Listen for traps of one device; returns the unregister callback.

    Raises OSError when the port cannot be opened.
    """
    servers: dict[int, TrapServer] = hass.data.setdefault(DATA_TRAP_SERVERS, {})
    server = servers.get(port)
    if server is None:
        server = TrapServer(port)
        await server.async_start()
        servers[port] = server

    addresses = {host}
    try:
        infos = await hass.loop.getaddrinfo(host, None, family=socket.AF_INET)
        addresses.update(info[4][0] for info in infos)
    except OSError:
        _LOGGER.debug("Cannot resolve %s for trap matching", host)
    server.register(entry_id, addresses, community, handler)

    @callback
    def _unregister() -> None:
        server.unregister(entry_id)
        if server.empty:
            server.stop()
            servers.pop(port, None)

    return _unregister
