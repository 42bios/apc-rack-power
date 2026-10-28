"""DataUpdateCoordinator for APC Rack Power."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import timedelta
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONTROL_TABLES,
    DEVICE_PDU,
    DEVICE_UPS,
    DISCOVERY_EVERY,
    DOMAIN,
    EVENT_TRAP,
    FLAG_ON_BATTERY,
    FLAG_REPLACE_BATTERY,
    METRICS,
    ON_BATTERY_SCAN_INTERVAL,
    SNMP_V3,
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
from .snmp_client import ApcSnmpAuthError, ApcSnmpClient, ApcSnmpError, async_read_mac
from .traps import OID_ENGINE_ID, engine_id_bytes

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from .traps import TrapInfo

_LOGGER = logging.getLogger(__name__)

# Which device kind a table belongs to (None = any network card)
TABLE_KIND: dict[str, str | None] = {
    "device_rpdu2": DEVICE_PDU,
    "phase_rpdu2": DEVICE_PDU,
    "phase_epdu": DEVICE_PDU,
    "ups_input_lines": DEVICE_UPS,
    "ups_output_lines": DEVICE_UPS,
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
    module: int = 1
    # Writable configuration (full OIDs; None = not available)
    name_write_oid: str | None = None
    name_max_length: int = 20
    on_delay_oid: str | None = None
    off_delay_oid: str | None = None
    reboot_duration_oid: str | None = None
    delay_range: tuple[int, int] = (-1, 7200)
    reboot_range: tuple[int, int] = (5, 60)


@dataclass(slots=True)
class ApcSnapshot:
    """Coordinator payload."""

    metrics: dict[str, Any]
    device_kind: str
    controls: list[ControlPoint] = field(default_factory=list)
    control_states: dict[str, bool | None] = field(default_factory=dict)
    # table key -> row index -> column -> value
    tables: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    # control uid -> {"on_delay", "off_delay", "reboot_duration"}
    control_settings: dict[str, dict[str, Any]] = field(default_factory=dict)

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
    if precision == 0 or (precision is None and float(value).is_integer()):
        return int(value)
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
        self._scan_interval = timedelta(seconds=scan_interval)
        self.custom_metrics = custom_metrics
        self._metric_defs = (*METRICS, *custom_metrics)
        self._supported_oids: set[str] | None = None
        self._controls: list[ControlPoint] = []
        self._table_rows: dict[str, dict[str, dict[str, Any]]] = {}
        self._control_settings: dict[str, dict[str, Any]] = {}
        self._trap_listeners: list[Callable[[str | None, str], None]] = []
        self._polls = 0
        self.mac: str | None = None
        # snmpEngineID of the card, needed to verify its SNMPv3 traps
        self.engine_id: bytes | None = None
        self._discovery_task: asyncio.Task | None = None
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

    def module_device_info(self, module: int) -> DeviceInfo:
        """Device of a chained (Network Port Sharing) PDU; module 1 is the card itself."""
        if module <= 1:
            return self.device_info
        rows = self.data.tables.get("device_rpdu2", {}) if self.data else {}
        row = next((r for r in rows.values() if r.get("module") == module), {})
        label = str(row.get("name") or "").strip() or f"PDU {module}"
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self.config_entry.entry_id}_module_{module}")},
            name=f"{self.config_entry.title} {label}",
            manufacturer="APC",
            model=str(row.get("model") or "").strip() or None,
            serial_number=str(row.get("serial") or "").strip() or None,
            sw_version=str(row.get("firmware") or "").strip() or None,
            via_device=(DOMAIN, self.config_entry.entry_id),
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
            if self._polls == 0:
                await self._discover_identity()
            if discover and (self._discovery_task is None or self._discovery_task.done()):
                # Walking tables is slow on older cards (about 10 s on an NMC2):
                # never delay a poll or the start of Home Assistant for it.
                self._discovery_task = self.config_entry.async_create_background_task(
                    self.hass, self._async_rediscover(device_kind, refresh=self._polls == 0), f"{DOMAIN}_discovery"
                )
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
            control_settings={uid: dict(values) for uid, values in self._control_settings.items()},
        )
        self._update_issues(snapshot)
        self._adapt_interval(snapshot)
        return snapshot

    def _adapt_interval(self, snapshot: ApcSnapshot) -> None:
        """Poll faster while a UPS runs on battery."""
        on_battery = flag(snapshot.flags, FLAG_ON_BATTERY)
        if on_battery is None:
            on_battery = snapshot.metric("rfc_output_source") == 5 or snapshot.metric("apc_output_status") == 3
        self.update_interval = timedelta(seconds=ON_BATTERY_SCAN_INTERVAL) if on_battery else self._scan_interval

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

    async def _discover_identity(self) -> None:
        """MAC address (unique id) and engine ID (SNMPv3 traps) of the card."""
        self.mac = await async_read_mac(self.client) or self.mac
        if self.engine_id is None and self.client.credentials.version == SNMP_V3:
            try:
                self.engine_id = engine_id_bytes(await self.client.get(OID_ENGINE_ID))
            except ApcSnmpError as err:
                _LOGGER.debug("Cannot read the engine ID: %s", err)

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
            modules: dict[str, Any] = {}
            if table.module_oid and names:
                modules = {
                    index: value
                    for oid, value in (await self._walk(table.module_oid)).items()
                    if (index := self._index(oid, table.module_oid)) is not None
                }
            rows = [
                self._control_point(table, index, str(name).strip(), modules.get(index))
                for oid, name in names.items()
                if (index := self._index(oid, table.name_oid)) is not None
            ]
            if rows and table.kind == DEVICE_PDU:
                have_pdu_table = True
            controls.extend(rows)
        if controls or not self._controls:
            self._controls = controls
        await self._read_control_settings()

        table_rows: dict[str, dict[str, dict[str, Any]]] = {}
        for table in TABLES:
            if not kind_matches(device_kind, TABLE_KIND.get(table.key)):
                continue
            if table.key in ("load_rpdu", "phase_epdu") and "phase_rpdu2" in table_rows:
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

    async def _async_rediscover(self, device_kind: str, refresh: bool = False) -> None:
        try:
            await self._discover(device_kind)
        except ApcSnmpError as err:
            _LOGGER.debug("Background discovery failed: %s", err)
            return
        if refresh:
            # First discovery after start: show the outlets and tables right away
            await self.async_refresh()

    async def _read_control_settings(self) -> None:
        cells: dict[str, tuple[str, str]] = {}
        for control in self._controls:
            for key in ("on_delay", "off_delay", "reboot_duration"):
                if oid := getattr(control, f"{key}_oid"):
                    cells[oid.lstrip(".")] = (control.uid, key)
        if not cells:
            return
        values = await self.client.get_many(list(cells))
        settings: dict[str, dict[str, Any]] = {}
        for oid, (uid, key) in cells.items():
            if isinstance(value := values.get(oid), int):
                settings.setdefault(uid, {})[key] = value
        self._control_settings = settings

    @staticmethod
    def _control_point(table: ControlTableDef, index: str, name: str, module: Any = None) -> ControlPoint:
        if not name or name in {"0", "None"}:
            name = f"{index}"
        if name.isdigit():  # ePDU reports outlet numbers instead of names
            name = f"Outlet {name}"

        def column(oid: str | None) -> str | None:
            return f"{oid}.{index}" if oid else None

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
            module=module if isinstance(module, int) and module > 0 else 1,
            name_write_oid=column(table.name_write_oid),
            name_max_length=table.name_max_length,
            on_delay_oid=column(table.on_delay_oid),
            off_delay_oid=column(table.off_delay_oid),
            reboot_duration_oid=column(table.reboot_duration_oid),
            delay_range=table.delay_range,
            reboot_range=table.reboot_range,
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

    async def async_write(self, oid: str, value: int | str, value_type: str = "integer", refresh: bool = True) -> None:
        """Write a value ("integer", "text" or "timeticks") and refresh afterwards."""
        issue_id = f"write_failed_{self.config_entry.entry_id}"
        try:
            if value_type == "text":
                await self.client.set_text(oid, str(value))
            elif value_type == "timeticks":
                await self.client.set_timeticks(oid, int(value))
            else:
                await self.client.set_integer(oid, int(value))
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
        if refresh:
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

    async def async_set_control_name(self, control: ControlPoint, name: str) -> None:
        """Rename an outlet or outlet group on the device."""
        if control.name_write_oid is None:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="not_writable")
        await self.async_write(control.name_write_oid, name, "text", refresh=False)
        self._controls = [replace(c, name=name) if c.uid == control.uid else c for c in self._controls]
        if self.data:
            self.data.controls = list(self._controls)
        self._show_change()

    async def async_set_control_setting(self, control: ControlPoint, key: str, value: int) -> None:
        """Change a delay or the reboot duration of an outlet."""
        oid = getattr(control, f"{key}_oid")
        if oid is None:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="not_writable")
        await self.async_write(oid, value, refresh=False)
        self._control_settings.setdefault(control.uid, {})[key] = value
        if self.data:
            self.data.control_settings.setdefault(control.uid, {})[key] = value
        self._show_change()

    async def async_set_table_value(self, table_key: str, index: str, column: str, oid: str, value: int) -> None:
        """Write a configuration cell of a table (e.g. a phase threshold)."""
        await self.async_write(f"{oid}.{index}", value, refresh=False)
        self._table_rows.setdefault(table_key, {}).setdefault(index, {})[column] = value
        if self.data:
            self.data.tables.setdefault(table_key, {}).setdefault(index, {})[column] = value
        self._show_change()

    @callback
    def _show_change(self) -> None:
        """Show a written setting at once; the device is read again shortly after."""
        self.async_update_listeners()
        self.config_entry.async_create_background_task(
            self.hass, self.async_request_refresh(), f"{DOMAIN}_refresh_after_write"
        )

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
        # APC traps carry their description in mtrapargsString
        message = trap.varbinds.get("1.3.6.1.4.1.318.2.3.3.0")
        self.last_trap = {
            "trap_oid": trap.trap_oid,
            "message": message,
            "varbinds": trap.varbinds,
        }
        self.hass.bus.async_fire(
            EVENT_TRAP,
            {
                "entry_id": self.config_entry.entry_id,
                "host": trap.source,
                "trap_oid": trap.trap_oid,
                "message": message,
                "varbinds": trap.varbinds,
            },
        )
        for listener in list(self._trap_listeners):
            listener(message, trap.trap_oid)
        self.config_entry.async_create_background_task(
            self.hass, self.async_request_refresh(), f"{DOMAIN}_trap_refresh"
        )

    @callback
    def async_add_trap_listener(self, listener: Callable[[str | None, str], None]) -> Callable[[], None]:
        """Call `listener(message, trap_oid)` for every trap of this device."""
        self._trap_listeners.append(listener)

        @callback
        def _remove() -> None:
            self._trap_listeners.remove(listener)

        return _remove
