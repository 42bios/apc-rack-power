"""Switches for APC Rack Power integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import RUNTIME_COORDINATOR
from .const import DOMAIN, OFF_VALUES, ON_VALUES
from .coordinator import ApcEnterpriseCoordinator, ControlPoint
from .device_profile import detect_device_kind, table_matches_device


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up APC control switches."""
    coordinator: ApcEnterpriseCoordinator = hass.data[DOMAIN][entry.entry_id][RUNTIME_COORDINATOR]
    created: set[str] = set()

    def _build_new_entities() -> list[ApcControlSwitch]:
        controls = coordinator.data.discovered_controls if coordinator.data else coordinator.controls
        metrics = coordinator.data.metrics if coordinator.data else {}
        device_kind = detect_device_kind(metrics)
        new_entities: list[ApcControlSwitch] = []
        for control in controls:
            if not table_matches_device(device_kind, control.table_key):
                continue
            if control.uid in created:
                continue
            created.add(control.uid)
            new_entities.append(ApcControlSwitch(entry, coordinator, control))
        return new_entities

    initial = _build_new_entities()
    if initial:
        async_add_entities(initial)

    @callback
    def _handle_coordinator_update() -> None:
        new_entities = _build_new_entities()
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(_handle_coordinator_update))


class ApcControlSwitch(CoordinatorEntity[ApcEnterpriseCoordinator], SwitchEntity):
    """One discovered APC control point as switch."""

    _attr_has_entity_name = True

    def __init__(
        self,
        entry: ConfigEntry,
        coordinator: ApcEnterpriseCoordinator,
        control: ControlPoint,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._control = control
        self._attr_unique_id = f"{entry.entry_id}_{control.uid}"
        normalized_name = str(control.name).strip()
        if normalized_name.lower().startswith("outlet "):
            self._attr_name = normalized_name
        else:
            self._attr_name = f"{control.label} {normalized_name}"

    @property
    def is_on(self) -> bool | None:
        if not self.coordinator.data:
            return None
        value = self.coordinator.data.control_states.get(self._control.uid)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            value_int = int(value)
            if value_int in ON_VALUES:
                return True
            if value_int in OFF_VALUES:
                return False
        return None

    @property
    def available(self) -> bool:
        return bool(self.coordinator.last_update_success)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "uid": self._control.uid,
            "table": self._control.table_key,
            "index": self._control.index,
            "status_oid": self._control.status_oid,
            "control_oid": self._control.control_oid,
        }

    @property
    def device_info(self) -> dict[str, Any]:
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": self._entry.title,
            "manufacturer": "APC",
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_control(self._control, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_control(self._control, False)

