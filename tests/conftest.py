"""Fixtures for APC Rack Power tests.

The fixtures in tests/fixtures are SNMP walks of a Smart-UPS SRT3000 with an
AP9641 card and of a switched Rack PDU AP8959EU3 (serials anonymised).
"""

from __future__ import annotations

from collections.abc import Generator
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.apc_rack_power.const import DOMAIN
from custom_components.apc_rack_power.snmp_client import ApcSnmpClient

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict[str, Any]:
    """Load an SNMP walk as {oid: value}."""
    return {oid.lstrip("."): value for oid, value in json.loads((FIXTURES / f"{name}.json").read_text()).items()}


class FakeAgent:
    """In-memory SNMP agent replacing the network."""

    def __init__(self) -> None:
        self.values: dict[str, Any] = {}
        self.writes: list[tuple[str, int | str]] = []
        self.get_error: Exception | None = None
        self.set_error: Exception | None = None

    def use(self, name: str) -> None:
        self.values = load_fixture(name)

    async def get_many(self, oids: list[str]) -> dict[str, Any]:
        if self.get_error:
            raise self.get_error
        return {oid.lstrip("."): self.values.get(oid.lstrip(".")) for oid in oids}

    async def get(self, oid: str) -> Any:
        return (await self.get_many([oid]))[oid.lstrip(".")]

    async def walk(self, root: str, max_rows: int = 1024) -> dict[str, Any]:
        if self.get_error:
            raise self.get_error
        prefix = root.lstrip(".") + "."
        return {oid: value for oid, value in self.values.items() if oid.startswith(prefix)}

    async def set_integer(self, oid: str, value: int | str) -> None:
        if self.set_error:
            raise self.set_error
        self.writes.append((oid.lstrip("."), value))
        self.values[oid.lstrip(".")] = value


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load the integration from custom_components."""


@pytest.fixture
def agent() -> Generator[FakeAgent]:
    """Patch the SNMP client so it talks to a FakeAgent."""
    fake = FakeAgent()
    with (
        patch(
            "custom_components.apc_rack_power.snmp_client.async_get_engine",
            AsyncMock(return_value=MagicMock()),
        ),
        patch.object(ApcSnmpClient, "get_many", lambda self, oids: fake.get_many(oids)),
        patch.object(ApcSnmpClient, "get", lambda self, oid: fake.get(oid)),
        patch.object(ApcSnmpClient, "walk", lambda self, root, max_rows=1024: fake.walk(root, max_rows)),
        patch.object(ApcSnmpClient, "set_integer", lambda self, oid, value: fake.set_integer(oid, value)),
        patch.object(ApcSnmpClient, "set_text", lambda self, oid, value: fake.set_integer(oid, value)),
        patch.object(ApcSnmpClient, "set_timeticks", lambda self, oid, value: fake.set_integer(oid, value)),
        patch("custom_components.apc_rack_power.coordinator.asyncio.sleep", AsyncMock()),
    ):
        yield fake


def make_entry(name: str = "UPS", host: str = "192.0.2.10", **data: Any) -> MockConfigEntry:
    """A config entry in the current format."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=name,
        unique_id=host,
        version=1,
        minor_version=2,
        data={"host": host, "port": 161, "name": name, "snmp_version": "v2c", "community": "public", **data},
        options={},
    )
