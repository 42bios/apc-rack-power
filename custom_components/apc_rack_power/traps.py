"""SNMP trap receiver for APC Rack Power.

APC network cards send a trap the moment something happens (mains failure,
switch to battery, alarms, outlet changes). The receiver accepts SNMPv1/v2c
traps with the configured community and SNMPv3 traps of the entry's user
(authenticated and decrypted with its keys), matches the sender against the
configured devices, fires an event and triggers an immediate poll.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
import socket
from typing import Any

from homeassistant.core import HomeAssistant, callback
from pysnmp.carrier.asyncio.dgram import udp
from pysnmp.entity import config
from pysnmp.entity.engine import SnmpEngine
from pysnmp.entity.rfc3413 import ntfrcv
from pysnmp.proto import rfc1902

from .const import DOMAIN, SNMP_V3
from .snmp_client import AUTH_PROTOCOL_MAP, PRIV_PROTOCOL_MAP, SnmpCredentials, _create_engine, convert_value

_LOGGER = logging.getLogger(__name__)

DATA_TRAP_SERVERS = f"{DOMAIN}_trap_servers"

SNMP_TRAP_OID = "1.3.6.1.6.3.1.1.4.1.0"
SYS_UPTIME = "1.3.6.1.2.1.1.3.0"
OID_ENGINE_ID = ".1.3.6.1.6.3.10.2.1.1.0"


@dataclass(slots=True, frozen=True)
class TrapInfo:
    """A received trap."""

    source: str
    trap_oid: str
    varbinds: dict[str, Any]


@dataclass(slots=True)
class _Registration:
    addresses: set[str]
    handler: Callable[[TrapInfo], None]
    community_index: str | None = None
    v3_user: tuple[str, Any] | None = None


def engine_id_bytes(value: Any) -> bytes | None:
    """Convert the snmpEngineID read via SNMP ("0x8000...") into bytes."""
    if isinstance(value, str) and value.startswith("0x") and len(value) > 10:
        try:
            return bytes.fromhex(value[2:])
        except ValueError:
            return None
    return None


class TrapServer:
    """One UDP listener (and SNMP engine) shared by all entries on a port."""

    def __init__(self, port: int) -> None:
        self.port = port
        self._engine: SnmpEngine | None = None
        self._transport: udp.UdpAsyncioTransport | None = None
        self._registrations: dict[str, _Registration] = {}

    async def async_start(self, hass: HomeAssistant, host: str = "0.0.0.0") -> None:
        """Bind the port (raises OSError if it is not available)."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setblocking(False)
            sock.bind((host, self.port))
        except OSError:
            sock.close()
            raise
        self._engine = await hass.async_add_executor_job(_create_engine)
        self._transport = udp.UdpAsyncioTransport().open_server_mode(sock=sock)
        config.add_transport(self._engine, udp.DOMAIN_NAME, self._transport)
        ntfrcv.NotificationReceiver(self._engine, self._on_notification)

    def stop(self) -> None:
        if self._engine is not None:
            # Closes the transport and stops the dispatcher's timer task
            self._engine.close_dispatcher()
        self._transport = None
        self._engine = None

    @property
    def empty(self) -> bool:
        return not self._registrations

    def register(
        self,
        entry_id: str,
        addresses: set[str],
        handler: Callable[[TrapInfo], None],
        community: str | None,
        credentials: SnmpCredentials | None = None,
        engine_id: bytes | None = None,
    ) -> None:
        """Accept traps of one device."""
        assert self._engine is not None
        registration = _Registration(addresses=addresses, handler=handler)
        if community:
            registration.community_index = f"apc-{entry_id}"
            config.add_v1_system(self._engine, registration.community_index, community)
        if credentials is not None and credentials.version == SNMP_V3 and credentials.v3_username and engine_id:
            auth = AUTH_PROTOCOL_MAP.get(credentials.v3_auth_protocol.lower(), AUTH_PROTOCOL_MAP["none"])
            priv = PRIV_PROTOCOL_MAP.get(credentials.v3_priv_protocol.lower(), PRIV_PROTOCOL_MAP["none"])
            security_engine = rfc1902.OctetString(engine_id)
            kwargs: dict[str, Any] = {"securityEngineId": security_engine}
            if auth != AUTH_PROTOCOL_MAP["none"]:
                kwargs.update(authProtocol=auth, authKey=credentials.v3_auth_passphrase)
                if priv != PRIV_PROTOCOL_MAP["none"]:
                    kwargs.update(privProtocol=priv, privKey=credentials.v3_priv_passphrase)
            config.add_v3_user(self._engine, credentials.v3_username, **kwargs)
            registration.v3_user = (credentials.v3_username, security_engine)
        self._registrations[entry_id] = registration

    def unregister(self, entry_id: str) -> None:
        registration = self._registrations.pop(entry_id, None)
        if registration is None or self._engine is None:
            return
        if registration.community_index:
            config.delete_v1_system(self._engine, registration.community_index)
        if registration.v3_user:
            user, engine_id = registration.v3_user
            config.delete_v3_user(self._engine, user, securityEngineId=engine_id)

    @callback
    def _on_notification(
        self,
        snmp_engine: SnmpEngine,
        state_reference: Any,
        context_engine_id: Any,
        context_name: Any,
        var_binds: Any,
        cb_ctx: Any,
    ) -> None:
        try:
            _domain, address = snmp_engine.message_dispatcher.get_transport_info(state_reference)
            source = str(address[0])
        except Exception:  # noqa: BLE001 - a strange packet must never break the receiver
            return
        targets = [r for r in self._registrations.values() if source in r.addresses]
        if not targets:
            _LOGGER.debug("Ignoring trap from unknown sender %s", source)
            return
        trap_oid = ""
        values: dict[str, Any] = {}
        for oid, value in var_binds:
            key = str(oid)
            converted = convert_value(value)
            if key == SNMP_TRAP_OID:
                trap_oid = str(converted)
            elif key != SYS_UPTIME:
                values[key] = converted
        trap = TrapInfo(source=source, trap_oid=trap_oid, varbinds=values)
        _LOGGER.debug("Trap %s from %s", trap_oid, source)
        for registration in targets:
            registration.handler(trap)


async def async_register_trap_handler(
    hass: HomeAssistant,
    entry_id: str,
    host: str,
    port: int,
    community: str | None,
    handler: Callable[[TrapInfo], None],
    credentials: SnmpCredentials | None = None,
    engine_id: bytes | None = None,
) -> Callable[[], None]:
    """Listen for traps of one device; returns the unregister callback.

    Raises OSError when the port cannot be opened.
    """
    servers: dict[int, TrapServer] = hass.data.setdefault(DATA_TRAP_SERVERS, {})
    server = servers.get(port)
    if server is None:
        server = TrapServer(port)
        await server.async_start(hass)
        servers[port] = server

    addresses = {host}
    try:
        infos = await hass.loop.getaddrinfo(host, None, family=socket.AF_INET)
        addresses.update(info[4][0] for info in infos)
    except OSError:
        _LOGGER.debug("Cannot resolve %s for trap matching", host)
    server.register(entry_id, addresses, handler, community, credentials, engine_id)

    @callback
    def _unregister() -> None:
        server.unregister(entry_id)
        if server.empty:
            server.stop()
            servers.pop(port, None)

    return _unregister
