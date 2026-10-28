"""Text entities for APC Rack Power: outlet and outlet group names on the device."""

from __future__ import annotations

from collections.abc import Callable, Iterator

from homeassistant.components.text import TextEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ApcConfigEntry
from .coordinator import ApcCoordinator, ApcSnapshot, ControlPoint
from .device_profile import kind_matches
from .entity import ApcControlEntity, add_entities_when_found

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ApcConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up name fields for outlets and outlet groups."""
    coordinator = entry.runtime_data

    def _build(d: ApcSnapshot) -> Iterator[tuple[str, Callable[[], Entity]]]:
        for control in d.controls:
            if control.name_write_oid and kind_matches(d.device_kind, control.kind):
                yield f"{control.uid}_name", lambda control=control: ApcOutletNameText(coordinator, control)

    add_entities_when_found(coordinator, async_add_entities, _build)


class ApcOutletNameText(ApcControlEntity, TextEntity):
    """Name of an outlet as stored on the device; changing it renames the outlet there."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "outlet_name"

    def __init__(self, coordinator: ApcCoordinator, control: ControlPoint) -> None:
        super().__init__(coordinator, f"{control.uid}_name", control)
        self._attr_native_max = control.name_max_length

    @property
    def native_value(self) -> str | None:
        return self._control.name

    async def async_set_value(self, value: str) -> None:
        await self.coordinator.async_set_control_name(self._control, value.strip())
