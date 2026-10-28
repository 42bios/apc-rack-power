"""Switches for APC Rack Power: PDU outlets and UPS outlet groups."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ApcConfigEntry
from .const import DEVICE_UPS
from .coordinator import ApcCoordinator, ApcSnapshot, ControlPoint
from .device_profile import kind_matches
from .entity import ApcControlEntity, add_entities_when_found

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ApcConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up APC outlet switches."""
    coordinator = entry.runtime_data

    def _build(d: ApcSnapshot) -> Iterator[tuple[str, Callable[[], Entity]]]:
        for control in d.controls:
            if kind_matches(d.device_kind, control.kind):
                yield control.uid, lambda control=control: ApcControlSwitch(coordinator, control)

    add_entities_when_found(coordinator, async_add_entities, _build)


class ApcControlSwitch(ApcControlEntity, SwitchEntity):
    """One outlet or outlet group."""

    _attr_device_class = SwitchDeviceClass.OUTLET

    def __init__(self, coordinator: ApcCoordinator, control: ControlPoint) -> None:
        super().__init__(coordinator, control.uid, control)
        if control.kind == DEVICE_UPS:
            self._attr_translation_key = "outlet_group"
        elif control.name.strip().lower().startswith("outlet "):
            self._attr_translation_key = "outlet_default"
        else:
            self._attr_translation_key = "outlet"

    @property
    def is_on(self) -> bool | None:
        return self.snapshot.control_states.get(self._control.uid)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"uid": self._control.uid, "index": self._control.index}

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_control(self._control, "on")

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_control(self._control, "off")
