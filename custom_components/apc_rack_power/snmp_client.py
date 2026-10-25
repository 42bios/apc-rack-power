"""Async SNMP client for APC Rack Power based on pysnmp."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.singleton import singleton
from pyasn1.type import univ
from pysnmp.hlapi.v3arch.asyncio import (
    CommunityData,
    ContextData,
    Integer32,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    Udp6TransportTarget,
    UdpTransportTarget,
    UsmUserData,
    bulk_walk_cmd,
    get_cmd,
    set_cmd,
    usm3DESEDEPrivProtocol,
    usmAesBlumenthalCfb192Protocol,
    usmAesBlumenthalCfb256Protocol,
    usmAesCfb128Protocol,
    usmAesCfb192Protocol,
    usmAesCfb256Protocol,
    usmDESPrivProtocol,
    usmHMAC128SHA224AuthProtocol,
    usmHMAC192SHA256AuthProtocol,
    usmHMAC256SHA384AuthProtocol,
    usmHMAC384SHA512AuthProtocol,
    usmHMACMD5AuthProtocol,
    usmHMACSHAAuthProtocol,
    usmNoAuthProtocol,
    usmNoPrivProtocol,
    walk_cmd,
)
from pysnmp.hlapi.v3arch.asyncio.cmdgen import LCD
from pysnmp.proto import rfc1902, rfc1905
from pysnmp.smi import view

from .const import SNMP_V1, SNMP_V3

_LOGGER = logging.getLogger(__name__)

DATA_ENGINE = "apc_rack_power_snmp_engine"

# APC agents answer reliably with up to this many varbinds per request.
GET_BATCH_SIZE = 16
WALK_REPETITIONS = 24

AUTH_PROTOCOL_MAP = {
    "none": usmNoAuthProtocol,
    "md5": usmHMACMD5AuthProtocol,
    "sha": usmHMACSHAAuthProtocol,
    "sha1": usmHMACSHAAuthProtocol,
    "sha224": usmHMAC128SHA224AuthProtocol,
    "sha256": usmHMAC192SHA256AuthProtocol,
    "sha384": usmHMAC256SHA384AuthProtocol,
    "sha512": usmHMAC384SHA512AuthProtocol,
}

PRIV_PROTOCOL_MAP = {
    "none": usmNoPrivProtocol,
    "des": usmDESPrivProtocol,
    "3des": usm3DESEDEPrivProtocol,
    "aes": usmAesCfb128Protocol,
    "aes192": usmAesBlumenthalCfb192Protocol,
    "aes256": usmAesBlumenthalCfb256Protocol,
    "aes192c": usmAesCfb192Protocol,
    "aes256c": usmAesCfb256Protocol,
}

# Error indications that mean "wrong SNMPv3 credentials"
_AUTH_ERRORS = {
    "WrongDigest",
    "UnknownUserName",
    "UnknownSecurityName",
    "UnsupportedSecurityLevel",
    "AuthenticationFailure",
    "AuthenticationError",
    "DecryptionError",
}

_NO_VALUE = (rfc1905.NoSuchObject, rfc1905.NoSuchInstance, rfc1905.EndOfMibView)


class ApcSnmpError(Exception):
    """Raised when an SNMP request fails."""


class ApcSnmpAuthError(ApcSnmpError):
    """Raised when the device rejects the SNMPv3 credentials."""


@dataclass(slots=True, frozen=True)
class SnmpCredentials:
    """Credentials for one device."""

    version: str
    community: str = ""
    write_community: str = ""
    v3_username: str = ""
    v3_auth_protocol: str = "none"
    v3_auth_passphrase: str = ""
    v3_priv_protocol: str = "none"
    v3_priv_passphrase: str = ""


@singleton(DATA_ENGINE)
async def async_get_engine(hass: HomeAssistant) -> SnmpEngine:
    """Return the shared SNMP engine (created in the executor, it loads MIBs)."""
    engine = await hass.async_add_executor_job(_create_engine)

    @callback
    def _shutdown(_event: Event) -> None:
        LCD.unconfigure(engine, None)

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _shutdown)
    return engine


def _create_engine() -> SnmpEngine:
    engine = SnmpEngine()
    controller = view.MibViewController(engine.message_dispatcher.mib_instrum_controller.get_mib_builder())
    engine.cache["mibViewController"] = controller
    controller.mibBuilder.load_modules()
    return engine


def convert_value(value: Any) -> Any:
    """Convert a pysnmp value into a plain Python value."""
    if value is None or isinstance(value, _NO_VALUE):
        return None
    if hasattr(value, "getOid"):  # ObjectIdentity resolved through the MIB view
        return str(value.getOid())
    if isinstance(value, rfc1902.IpAddress):
        return value.prettyPrint()
    if isinstance(value, univ.Integer):
        return int(value)
    if isinstance(value, univ.ObjectIdentifier):
        return str(value)
    if isinstance(value, univ.OctetString):
        raw = bytes(value)
        try:
            return raw.decode("utf-8").strip("\x00").strip()
        except UnicodeDecodeError:
            return value.prettyPrint()
    return value.prettyPrint() if hasattr(value, "prettyPrint") else value


def _normalize(oid: str) -> str:
    return oid.lstrip(".")


class ApcSnmpClient:
    """SNMP access to one APC network management card."""

    def __init__(
        self,
        engine: SnmpEngine,
        host: str,
        port: int,
        timeout: int,
        retries: int,
        credentials: SnmpCredentials,
    ) -> None:
        self._engine = engine
        self.host = host
        self.port = port
        self.timeout = timeout
        self.retries = retries
        self.credentials = credentials
        self._target: UdpTransportTarget | Udp6TransportTarget | None = None

    @classmethod
    async def async_create(
        cls,
        hass: HomeAssistant,
        host: str,
        port: int,
        timeout: int,
        retries: int,
        credentials: SnmpCredentials,
    ) -> ApcSnmpClient:
        """Create a client using the shared engine."""
        return cls(await async_get_engine(hass), host, port, timeout, retries, credentials)

    @property
    def can_write(self) -> bool:
        """Whether credentials for write requests exist."""
        if self.credentials.version == SNMP_V3:
            return bool(self.credentials.v3_username)
        return bool(self.credentials.write_community or self.credentials.community)

    def _auth(self, write: bool = False) -> CommunityData | UsmUserData:
        creds = self.credentials
        if creds.version == SNMP_V3:
            auth_proto = AUTH_PROTOCOL_MAP.get(creds.v3_auth_protocol.lower(), usmNoAuthProtocol)
            priv_proto = PRIV_PROTOCOL_MAP.get(creds.v3_priv_protocol.lower(), usmNoPrivProtocol)
            if auth_proto == usmNoAuthProtocol:
                return UsmUserData(creds.v3_username)
            if priv_proto == usmNoPrivProtocol:
                return UsmUserData(
                    creds.v3_username,
                    authKey=creds.v3_auth_passphrase,
                    authProtocol=auth_proto,
                )
            return UsmUserData(
                creds.v3_username,
                authKey=creds.v3_auth_passphrase,
                privKey=creds.v3_priv_passphrase,
                authProtocol=auth_proto,
                privProtocol=priv_proto,
            )
        community = (creds.write_community or creds.community) if write else creds.community
        return CommunityData(community, mpModel=0 if creds.version == SNMP_V1 else 1)

    async def _get_target(self) -> UdpTransportTarget | Udp6TransportTarget:
        if self._target is None:
            target_cls = Udp6TransportTarget if ":" in self.host else UdpTransportTarget
            try:
                self._target = await target_cls.create(
                    (self.host, self.port), timeout=self.timeout, retries=self.retries
                )
            except Exception as err:  # noqa: BLE001 - pysnmp raises plain errors for DNS failures
                raise ApcSnmpError(f"Cannot resolve {self.host}: {err}") from err
        return self._target

    @staticmethod
    def _raise_indication(indication: Any) -> None:
        if type(indication).__name__ in _AUTH_ERRORS:
            raise ApcSnmpAuthError(str(indication))
        raise ApcSnmpError(str(indication))

    async def get_many(self, oids: list[str]) -> dict[str, Any]:
        """Read many scalars; unsupported OIDs come back as None."""
        result: dict[str, Any] = {}
        pending = [_normalize(oid) for oid in oids]
        target = await self._get_target()
        auth = self._auth()
        while pending:
            batch, pending = pending[:GET_BATCH_SIZE], pending[GET_BATCH_SIZE:]
            while batch:
                indication, status, index, var_binds = await get_cmd(
                    self._engine,
                    auth,
                    target,
                    ContextData(),
                    *(ObjectType(ObjectIdentity(oid)) for oid in batch),
                )
                if indication:
                    self._raise_indication(indication)
                if status:
                    # SNMPv1 rejects the whole request when one OID is missing:
                    # drop the offending varbind and ask again.
                    position = int(index) - 1
                    if 0 <= position < len(batch):
                        result[batch.pop(position)] = None
                        continue
                    for oid in batch:
                        result[oid] = None
                    break
                for var_bind in var_binds:
                    result[_normalize(str(var_bind[0]))] = convert_value(var_bind[1])
                for oid in batch:
                    result.setdefault(oid, None)
                break
        return result

    async def get(self, oid: str) -> Any:
        """Read one scalar."""
        return (await self.get_many([oid])).get(_normalize(oid))

    async def walk(self, root_oid: str, max_rows: int = 1024) -> dict[str, Any]:
        """Walk a subtree and return {oid: value}."""
        root = _normalize(root_oid)
        target = await self._get_target()
        auth = self._auth()
        output: dict[str, Any] = {}
        if self.credentials.version == SNMP_V1:
            iterator = walk_cmd(
                self._engine,
                auth,
                target,
                ContextData(),
                ObjectType(ObjectIdentity(root)),
                lexicographicMode=False,
            )
        else:
            iterator = bulk_walk_cmd(
                self._engine,
                auth,
                target,
                ContextData(),
                0,
                WALK_REPETITIONS,
                ObjectType(ObjectIdentity(root)),
                lexicographicMode=False,
            )
        async for indication, status, _index, var_binds in iterator:
            if indication:
                self._raise_indication(indication)
            if status:
                break
            for var_bind in var_binds:
                oid = str(var_bind[0])
                if not oid.startswith(f"{root}."):
                    return output
                value = convert_value(var_bind[1])
                if value is not None:
                    output[oid] = value
            if len(output) >= max_rows:
                break
        return output

    async def set_integer(self, oid: str, value: int) -> None:
        """Write an integer value."""
        target = await self._get_target()
        indication, status, _index, _var_binds = await set_cmd(
            self._engine,
            self._auth(write=True),
            target,
            ContextData(),
            ObjectType(ObjectIdentity(_normalize(oid)), Integer32(int(value))),
        )
        if indication:
            self._raise_indication(indication)
        if status:
            raise ApcSnmpError(f"SNMP set {oid} failed: {status.prettyPrint()}")
