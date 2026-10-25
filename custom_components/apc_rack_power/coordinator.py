"""DataUpdateCoordinator for APC Rack Power."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import timedelta
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONTROL_TABLES,
    DEVICE_PDU,
    DISCOVERY_EVERY,
    DOMAIN,
    EVENT_TRAP,
    FLAG_REPLACE_BATTERY,
    METRICS,
    TABLES,
    ControlTableDef,
    MetricDef,
)
from .device_profile import (
    detect_device_kind,
    extract_model_number,
    flag,
    is_unavailable,
    kind_matches,
    parse_flags,
)
from .snmp_client import ApcSnmpAuthError, ApcSnmpClient, ApcSnmpError

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from .traps import TrapInfo

_LOGGER = logging.getLogger(__name__)

# Which device kind a table belongs to (None = any network card)
TABLE_KIND: dict[str, str | None] = {
    "phase_rpdu2": DEVICE_PDU,
    "bank_rpdu2": DEVICE_PDU,
    "load_rpdu": DEVICE_PDU,
    "load_rpdu_cfg": DEVICE_PDU,
    "outlet_metered_rpdu2": DEVICE_PDU,
    "env_rpdu2": DEVICE_PDU,
    "env_uio": None,
    "env_iem": None,
    "env_mem": None,
}


@dataclass(slots=True, frozen=True)
class ControlPoint:
    """A switchable outlet or outlet group."""

    uid: str
    table_key: str
    kind: str
    name: str
    index: str
    state_oid: str
    command_oid: str
    state_on: int
    state_off: int
    cmd_on: int
    cmd_off: int
    cmd_reboot: int | None


@dataclass(slots=True)
class ApcSnapshot:
    """Coordinator payload."""

    metrics: dict[str, Any]
    device_kind: str
    controls: list[ControlPoint] = field(default_factory=list)
    control_states: dict[str, bool | None] = field(default_factory=dict)
    # table key -> row index -> column -> value
    tables: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)

    def metric(self, key: str) -> Any:
        """Return a metric, None for "not available" markers."""
        value = self.metrics.get(key)
        return None if is_unavailable(value) else value

    @property
    def flags(self) -> str | None:
        """UPS state flags."""
        return parse_flags(self.metrics.get("ups_state_flags"))


def _scale(raw: Any, scale: float, precision: int | None) -> Any:
    if not isinstance(raw, (int, float)) or isinstance(raw, bool):
        return raw
    if scale == 1.0 and precision is None:
        return raw
    value = raw * scale
    if precision is not None:
        value = round(value, precision)
        if precision == 0:
            value = int(value)
    return value


class ApcCoordinator(DataUpdateCoordinator[ApcSnapshot]):
    """Poll and control one APC network management card."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: ApcSnmpClient,
        scan_interval: int,
        custom_metrics: list[MetricDef],
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=timedelta(seconds=scan_interval),
        )
        self.client = client
        self.custom_metrics = custom_metrics
        self._metric_defs = (*METRICS, *custom_metrics)
        self._supported_oids: set[str] | None = None
        self._controls: list[ControlPoint] = []
        self._table_rows: dict[str, dict[str, dict[str, Any]]] = {}
        self._polls = 0
        self.trap_count = 0
        self.last_trap: dict[str, Any] | None = None

    @property
    def controls(self) -> list[ControlPoint]:
        """Discovered controls."""
        return self._controls

    @property
    def device_info(self) -> DeviceInfo:
        """Device registry entry built from the identification values."""
        metrics = self.data.metrics if self.data else {}

        def text(*keys: str) -> str | None:
            for key in keys:
                value = metrics.get(key)
                if not is_unavailable(value):
                    return str(value).strip()
            return None

        model = text("ups_sku", "pdu_model_number", "ups_ident_model") or extract_model_number(metrics)
        return DeviceInfo(
            identifiers={(DOMAIN, self.config_entry.entry_id)},
            name=self.config_entry.title,
            manufacturer="APC",
            model=model,
            serial_number=text("ups_serial_number", "pdu_serial_number"),
            sw_version=text("ups_firmware", "pdu_firmware_rpdu"),
            hw_version=text("pdu_hardware_rev"),
            configuration_url=f"http://{self.config_entry.data[CONF_HOST]}",
        )

    # ----------------------------------------------------------------- polling

    async def _async_update_data(self) -> ApcSnapshot:
        discover = self._polls % DISCOVERY_EVERY == 0 or self._supported_oids is None
        try:
            metrics = await self._poll_metrics(discover)
            if all(value is None for value in metrics.values()):
                raise UpdateFailed(
                    translation_domain=DOMAIN,
                    translation_key="no_data",
                )
            device_kind = detect_device_kind(metrics)
            if discover:
                await self._discover(device_kind)
            tables, control_states = await self._poll_tables()
        except ApcSnmpAuthError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="auth_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        except ApcSnmpError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err)},
            ) from err

        self._polls += 1
        snapshot = ApcSnapshot(
            metrics=metrics,
            device_kind=device_kind,
            controls=list(self._controls),
            control_states=control_states,
            tables=tables,
        )
        self._update_issues(snapshot)
        return snapshot

    async def _poll_metrics(self, discover: bool) -> dict[str, Any]:
        oids = [oid for metric in self._metric_defs for oid, _scale in metric.sources]
        if not discover and self._supported_oids is not None:
            oids = [oid for oid in oids if oid.lstrip(".") in self._supported_oids]
        raw = await self.client.get_many(list(dict.fromkeys(oids)))
        if discover:
            self._supported_oids = {oid for oid, value in raw.items() if value is not None}

        metrics: dict[str, Any] = {}
        for metric in self._metric_defs:
            metrics[metric.key] = None
            for oid, scale in metric.sources:
                value = raw.get(oid.lstrip("."))
                if value is None or is_unavailable(value) and not metric.allow_negative:
                    continue
                if isinstance(value, (int, float)) and value < 0 and not metric.allow_negative:
                    continue
                metrics[metric.key] = _scale(value, scale, metric.precision)
                break
        return metrics

    async def _walk(self, oid: str) -> dict[str, Any]:
        try:
            return await self.client.walk(oid)
        except ApcSnmpAuthError:
            raise
        except ApcSnmpError as err:
            _LOGGER.debug("Walk of %s failed: %s", oid, err)
            return {}

    @staticmethod
    def _index(oid: str, base: str) -> str | None:
        base = base.lstrip(".")
        oid = oid.lstrip(".")
        if not oid.startswith(f"{base}."):
            return None
        return oid[len(base) + 1 :] or None

    async def _discover(self, device_kind: str) -> None:
        """Find outlets, outlet groups and tables the device supports."""
        controls: list[ControlPoint] = []
        have_pdu_table = False
        for table in CONTROL_TABLES:
            if not kind_matches(device_kind, table.kind):
                continue
            if table.kind == DEVICE_PDU and have_pdu_table:
                continue
            names = await self._walk(table.name_oid)
            rows = [
                self._control_point(table, index, str(name).strip())
                for oid, name in names.items()
                if (index := self._index(oid, table.name_oid)) is not None
            ]
            if rows and table.kind == DEVICE_PDU:
                have_pdu_table = True
            controls.extend(rows)
        if controls or not self._controls:
            self._controls = controls

        table_rows: dict[str, dict[str, dict[str, Any]]] = {}
        for table in TABLES:
            if not kind_matches(device_kind, TABLE_KIND.get(table.key)):
                continue
            if table.key == "load_rpdu" and "phase_rpdu2" in table_rows:
                continue
            if table.key == "load_rpdu_cfg" and "load_rpdu" not in table_rows:
                continue
            probe = next(iter({**table.columns, **table.static_columns}.values()))
            indexes = [
                index for oid in await self._walk(probe.oid) if (index := self._index(oid, probe.oid)) is not None
            ]
            if not indexes:
                continue
            rows: dict[str, dict[str, Any]] = {index: {} for index in indexes}
            if table.static_columns:
                cells = {
                    f"{column.oid}.{index}".lstrip("."): (index, name, column)
                    for name, column in table.static_columns.items()
                    for index in indexes
                }
                values = await self.client.get_many(list(cells))
                for oid, (index, name, column) in cells.items():
                    rows[index][name] = _scale(values.get(oid), column.scale, column.precision)
            table_rows[table.key] = rows
        # A table that failed to answer this time keeps its previous rows.
        self._table_rows = {**self._table_rows, **table_rows}

    @staticmethod
    def _control_point(table: ControlTableDef, index: str, name: str) -> ControlPoint:
        if not name or name in {"0", "None"}:
            name = f"{index}"
        return ControlPoint(
            uid=f"{table.key}_{index.replace('.', '_')}",
            table_key=table.key,
            kind=table.kind,
            name=name,
            index=index,
            state_oid=f"{table.state_oid}.{index}",
            command_oid=f"{table.command_oid}.{index}",
            state_on=table.state_on,
            state_off=table.state_off,
            cmd_on=table.cmd_on,
            cmd_off=table.cmd_off,
            cmd_reboot=table.cmd_reboot,
        )

    async def _poll_tables(
        self,
    ) -> tuple[dict[str, dict[str, dict[str, Any]]], dict[str, bool | None]]:
        """Read all known table cells and control states in batched requests."""
        cells: dict[str, tuple[str, str, str, Any]] = {}
        for table in TABLES:
            rows = self._table_rows.get(table.key)
            if not rows:
                continue
            for index in rows:
                for name, column in table.columns.items():
                    cells[f"{column.oid}.{index}".lstrip(".")] = (table.key, index, name, column)
        state_oids = {control.state_oid.lstrip("."): control for control in self._controls}
        values = await self.client.get_many([*cells, *state_oids]) if cells or state_oids else {}

        tables: dict[str, dict[str, dict[str, Any]]] = {
            key: {index: dict(static) for index, static in rows.items()} for key, rows in self._table_rows.items()
        }
        for oid, (table_key, index, name, column) in cells.items():
            raw = values.get(oid)
            if raw == -1:
                raw = None
            tables[table_key][index][name] = _scale(raw, column.scale, column.precision)

        states: dict[str, bool | None] = {}
        for oid, control in state_oids.items():
            raw = values.get(oid)
            states[control.uid] = True if raw == control.state_on else False if raw == control.state_off else None
        return tables, states

    # ---------------------------------------------------------------- commands

    async def async_write(self, oid: str, value: int) -> None:
        """Write an integer and refresh afterwards."""
        issue_id = f"write_failed_{self.config_entry.entry_id}"
        try:
            await self.client.set_integer(oid, value)
        except ApcSnmpError as err:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="write_failed",
                translation_placeholders={"name": self.config_entry.title},
            )
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="write_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        ir.async_delete_issue(self.hass, DOMAIN, issue_id)
        await asyncio.sleep(0.5)
        await self.async_request_refresh()

    async def async_control(self, control: ControlPoint, action: str) -> None:
        """Switch a control on, off or reboot it."""
        if action == "on":
            value = control.cmd_on
        elif action == "off":
            value = control.cmd_off
        elif control.cmd_reboot is not None:
            value = control.cmd_reboot
        else:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="reboot_not_supported",
            )
        await self.async_write(control.command_oid, value)

    # ------------------------------------------------------------------ issues

    def _update_issues(self, snapshot: ApcSnapshot) -> None:
        issue_id = f"battery_replace_{self.config_entry.entry_id}"
        replace = snapshot.metric("ups_battery_replace_indicator") == 2 or bool(
            flag(snapshot.flags, FLAG_REPLACE_BATTERY)
        )
        if replace:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="battery_replace",
                translation_placeholders={"name": self.config_entry.title},
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)

    # ------------------------------------------------------------------- traps

    def handle_trap(self, trap: TrapInfo) -> None:
        """React to a trap from this device: fire an event and poll at once."""
        self.trap_count += 1
        self.last_trap = {
            "trap_oid": trap.trap_oid,
            "varbinds": trap.varbinds,
        }
        self.hass.bus.async_fire(
            EVENT_TRAP,
            {
                "entry_id": self.config_entry.entry_id,
                "host": trap.source,
                "trap_oid": trap.trap_oid,
                "varbinds": trap.varbinds,
            },
        )
        self.config_entry.async_create_background_task(
            self.hass, self.async_request_refresh(), f"{DOMAIN}_trap_refresh"
        )
