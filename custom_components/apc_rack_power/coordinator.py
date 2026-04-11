"""DataUpdateCoordinator for APC Rack Power."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import BASE_METRICS, CONTROL_TABLES, ControlTableDef, MetricDef
from .snmp_client import ApcSnmpClient, ApcSnmpError

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class ControlPoint:
    """A single controllable outlet/group discovered via SNMP."""

    uid: str
    table_key: str
    label: str
    name: str
    index: str
    status_oid: str
    control_oid: str
    on_value: int
    off_value: int
    cycle_value: int | None


@dataclass(slots=True)
class ApcSnapshot:
    """Coordinator payload."""

    metrics: dict[str, Any]
    control_states: dict[str, Any]
    discovered_controls: list[ControlPoint]


class ApcEnterpriseCoordinator(DataUpdateCoordinator[ApcSnapshot]):
    """Poll and control APC devices via SNMP."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        name: str,
        snmp_client: ApcSnmpClient,
        scan_interval: int,
        custom_metrics: list[MetricDef],
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"APC Rack Power {name}",
            update_interval=timedelta(seconds=scan_interval),
        )
        self.entry_id = entry_id
        self.snmp = snmp_client
        self.custom_metrics = custom_metrics
        self._controls: list[ControlPoint] = []
        self._controls_loaded = False
        self._refresh_counter = 0
        self._reload_requested = False

    @property
    def controls(self) -> list[ControlPoint]:
        """Return discovered controls."""
        return self._controls

    @property
    def reload_requested(self) -> bool:
        """Whether platform reload is required."""
        return self._reload_requested

    def clear_reload_request(self) -> None:
        """Reset reload flag after platforms were reloaded."""
        self._reload_requested = False

    @staticmethod
    def _with_index(base_oid: str, index: str) -> str:
        return f"{base_oid}.{index}"

    @staticmethod
    def _parse_index(oid: str, base_oid: str) -> str | None:
        normalized_oid = oid.lstrip(".")
        normalized_base = base_oid.lstrip(".")
        if not normalized_oid.startswith(normalized_base):
            return None
        suffix = normalized_oid[len(normalized_base) :].lstrip(".")
        return suffix or None

    async def _load_controls(self) -> None:
        discovered: list[ControlPoint] = []
        have_rpdu2 = False

        for table in CONTROL_TABLES:
            if table.key == "spdu_outlet" and have_rpdu2:
                continue
            try:
                name_map = await self.snmp.walk(table.name_oid, 512)
            except ApcSnmpError:
                continue

            for oid, name_value in name_map.items():
                index = self._parse_index(oid, table.name_oid)
                if index is None:
                    continue
                label = str(name_value).strip() or f"{table.label} {index}"
                if label in {"0", "None"}:
                    continue
                cp = self._build_control_point(table, index, label)
                discovered.append(cp)
                if table.key == "rpdu2_outlet":
                    have_rpdu2 = True

        if discovered:
            deduped: dict[str, ControlPoint] = {control.uid: control for control in discovered}
            self._controls = list(deduped.values())
            self._controls_loaded = True

    def _build_control_point(self, table: ControlTableDef, index: str, name: str) -> ControlPoint:
        uid = f"{table.key}_{index.replace('.', '_')}"
        return ControlPoint(
            uid=uid,
            table_key=table.key,
            label=table.label,
            name=name,
            index=index,
            status_oid=self._with_index(table.status_oid, index),
            control_oid=self._with_index(table.control_oid, index),
            on_value=table.on_value,
            off_value=table.off_value,
            cycle_value=table.cycle_value,
        )

    async def async_set_control(self, control: ControlPoint, state: bool) -> None:
        """Set one control on/off."""
        value = control.on_value if state else control.off_value
        await self.snmp.set_integer(control.control_oid, value)
        await asyncio.sleep(0.25)
        await self.async_request_refresh()

    async def async_cycle_control(self, control: ControlPoint) -> None:
        """Cycle one control if supported."""
        if control.cycle_value is None:
            raise ApcSnmpError("Cycle command not supported for this control")
        await self.snmp.set_integer(control.control_oid, control.cycle_value)
        await asyncio.sleep(0.25)
        await self.async_request_refresh()

    async def async_set_oid(self, oid: str, value: int) -> None:
        """Set arbitrary OID as integer."""
        await self.snmp.set_integer(oid, value)
        await asyncio.sleep(0.25)
        await self.async_request_refresh()

    async def _async_poll_metric(self, metric: MetricDef) -> Any | None:
        raw: Any | None = None
        oids = (metric.oid, *metric.fallback_oids)
        for oid in oids:
            try:
                raw = await self.snmp.get(oid)
            except ApcSnmpError:
                raw = None
            if raw is not None:
                break
        if raw is None:
            return None
        if isinstance(raw, (int, float)):
            scaled = float(raw) * metric.scale
            if metric.precision is not None:
                return round(scaled, metric.precision)
            if metric.scale != 1.0:
                return scaled
            if isinstance(raw, float) and raw.is_integer():
                return int(raw)
        return raw

    async def _async_update_data(self) -> ApcSnapshot:
        if not self._controls_loaded or self._refresh_counter % 20 == 0:
            before = {item.uid for item in self._controls}
            await self._load_controls()
            after = {item.uid for item in self._controls}
            if after and after != before:
                self._reload_requested = True

        metric_defs = [*BASE_METRICS, *self.custom_metrics]
        metrics: dict[str, Any] = {}
        for metric in metric_defs:
            metrics[metric.key] = await self._async_poll_metric(metric)

        control_states: dict[str, Any] = {}
        for control in self._controls:
            try:
                control_states[control.uid] = await self.snmp.get(control.status_oid)
            except ApcSnmpError:
                control_states[control.uid] = None

        self._refresh_counter += 1
        if all(value is None for value in metrics.values()):
            raise UpdateFailed("No SNMP metrics could be read. Check IP/community/ACL.")
        return ApcSnapshot(
            metrics=metrics,
            control_states=control_states,
            discovered_controls=self._controls,
        )

