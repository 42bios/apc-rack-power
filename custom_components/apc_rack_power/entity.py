"""Base entity for APC Rack Power."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from homeassistant.core import callback
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import ApcCoordinator, ApcSnapshot


class ApcEntity(CoordinatorEntity[ApcCoordinator]):
    """Common base: unique id, device info, name from translations."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: ApcCoordinator, key: str, module: int = 1) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{key}"
        self._attr_device_info = coordinator.module_device_info(module)

    @property
    def snapshot(self) -> ApcSnapshot:
        """Latest data."""
        return self.coordinator.data


def add_entities_when_found(
    coordinator: ApcCoordinator,
    async_add_entities: AddConfigEntryEntitiesCallback,
    build: Callable[[ApcSnapshot], Iterable[tuple[str, Callable[[], Entity]]]],
) -> None:
    """Add entities now and whenever discovery finds new outlets or sensors.

    `build` returns (key, factory) pairs; each key is only added once.
    """
    known: set[str] = set()

    @callback
    def _add() -> None:
        if not coordinator.data:
            return
        new = [(key, factory) for key, factory in build(coordinator.data) if key not in known]
        if new:
            known.update(key for key, _factory in new)
            async_add_entities([factory() for _key, factory in new])

    _add()
    coordinator.config_entry.async_on_unload(coordinator.async_add_listener(_add))
