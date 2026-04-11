"""SNMP helper client for APC Rack Power based on puresnmp."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from puresnmp import Auth, Priv, V1, V2C, V3, Client, PyWrapper  # type: ignore[import-untyped]
from x690.types import Integer as XInteger  # type: ignore[import-untyped]


class ApcSnmpError(RuntimeError):
    """Raised when SNMP command fails."""


@dataclass(slots=True)
class ApcSnmpClient:
    """Async SNMP client with v2c->v1 fallback and retry support."""

    host: str
    community: str
    write_community: str
    port: int
    timeout: int
    retries: int
    snmp_version: str = "v2c"
    v3_username: str = ""
    v3_auth_protocol: str = "none"
    v3_auth_passphrase: str = ""
    v3_priv_protocol: str = "none"
    v3_priv_passphrase: str = ""
    _wrappers: dict[tuple[str, int], PyWrapper] | None = None

    def __post_init__(self) -> None:
        self._wrappers = {}

    @staticmethod
    def _normalize_oid(oid: str) -> str:
        return oid.lstrip(".")

    @staticmethod
    def _normalize_value(value: Any) -> Any:
        if isinstance(value, bytes):
            try:
                return value.decode("utf-8", errors="ignore")
            except Exception:
                return repr(value)
        return value

    async def _call_with_retries(self, coro_factory):
        last_err: Exception | None = None
        attempts = max(1, self.retries + 1)
        for _ in range(attempts):
            try:
                return await coro_factory()
            except Exception as err:
                last_err = err
        raise ApcSnmpError(str(last_err) if last_err else "SNMP operation failed")

    def _wrapper(self, community: str, mp_model: int) -> PyWrapper:
        assert self._wrappers is not None
        if self.snmp_version == "v3":
            cache_key = ("v3", 3)
        else:
            cache_key = (community, mp_model)
        cached = self._wrappers.get(cache_key)
        if cached is not None:
            return cached
        if self.snmp_version == "v3":
            username = self.v3_username.strip()
            auth_proto = self.v3_auth_protocol.strip().lower()
            priv_proto = self.v3_priv_protocol.strip().lower()
            auth = None
            priv = None
            if auth_proto != "none" and self.v3_auth_passphrase:
                auth = Auth(self.v3_auth_passphrase.encode("utf-8"), auth_proto)
            if priv_proto != "none" and self.v3_priv_passphrase and auth is not None:
                priv = Priv(self.v3_priv_passphrase.encode("utf-8"), priv_proto)
            creds = V3(username=username, auth=auth, priv=priv)
        else:
            creds = V2C(community) if mp_model == 1 else V1(community)
        wrapper = PyWrapper(Client(self.host, creds, port=self.port))
        self._wrappers[cache_key] = wrapper
        return wrapper

    @staticmethod
    def _iter_models() -> tuple[int, int]:
        return (1, 0)

    async def get(self, oid: str) -> Any | None:
        normalized = self._normalize_oid(oid)
        if self.snmp_version == "v3":
            wrapper = await asyncio.to_thread(self._wrapper, self.community, 3)
            try:
                value = await self._call_with_retries(
                    lambda wrapper=wrapper: wrapper.get(normalized)
                )
                return self._normalize_value(value)
            except Exception as err:
                raise ApcSnmpError(str(err)) from err
        last_err: Exception | None = None
        for mp_model in self._iter_models():
            wrapper = await asyncio.to_thread(self._wrapper, self.community, mp_model)
            try:
                value = await self._call_with_retries(
                    lambda wrapper=wrapper: wrapper.get(normalized)
                )
                return self._normalize_value(value)
            except Exception as err:
                last_err = err
        raise ApcSnmpError(str(last_err) if last_err else "SNMP get failed")

    async def set_integer(self, oid: str, value: int) -> None:
        normalized = self._normalize_oid(oid)
        if self.snmp_version == "v3":
            wrapper = await asyncio.to_thread(self._wrapper, self.community, 3)
            try:
                await self._call_with_retries(
                    lambda wrapper=wrapper: wrapper.set(normalized, XInteger(int(value)))
                )
                return
            except Exception as err:
                raise ApcSnmpError(str(err)) from err
        last_err: Exception | None = None
        for mp_model in self._iter_models():
            wrapper = await asyncio.to_thread(self._wrapper, self.write_community, mp_model)
            try:
                await self._call_with_retries(
                    lambda wrapper=wrapper: wrapper.set(normalized, XInteger(int(value)))
                )
                return
            except Exception as err:
                last_err = err
        raise ApcSnmpError(str(last_err) if last_err else "SNMP set failed")

    async def walk(self, root_oid: str, max_rows: int = 256) -> dict[str, Any]:
        normalized = self._normalize_oid(root_oid)
        if self.snmp_version == "v3":
            wrapper = await asyncio.to_thread(self._wrapper, self.community, 3)
            output: dict[str, Any] = {}
            try:
                async def _run_walk(wrapper=wrapper, output=output) -> None:
                    count = 0
                    async for row in wrapper.walk(normalized):
                        oid = str(getattr(row, "oid", row[0] if isinstance(row, tuple) else ""))
                        value = getattr(
                            row,
                            "value",
                            row[1] if isinstance(row, tuple) and len(row) > 1 else None,
                        )
                        output[oid] = self._normalize_value(value)
                        count += 1
                        if count >= max_rows:
                            break

                await self._call_with_retries(_run_walk)
                return output
            except Exception as err:
                raise ApcSnmpError(str(err)) from err
        last_err: Exception | None = None
        for mp_model in self._iter_models():
            wrapper = await asyncio.to_thread(self._wrapper, self.community, mp_model)
            output: dict[str, Any] = {}
            try:
                async def _run_walk(wrapper=wrapper, output=output) -> None:
                    count = 0
                    async for row in wrapper.walk(normalized):
                        oid = str(getattr(row, "oid", row[0] if isinstance(row, tuple) else ""))
                        value = getattr(
                            row,
                            "value",
                            row[1] if isinstance(row, tuple) and len(row) > 1 else None,
                        )
                        output[oid] = self._normalize_value(value)
                        count += 1
                        if count >= max_rows:
                            break

                await self._call_with_retries(_run_walk)
                return output
            except Exception as err:
                last_err = err
        raise ApcSnmpError(str(last_err) if last_err else "SNMP walk failed")

