"""Base entity for APC Rack Power."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from homeassistant.core import callback
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import ApcCoordinator, ApcSnapshot, ControlPoint


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

    def _set_name_placeholders(self, **values: str) -> None:
        """Update translation placeholders, e.g. after an outlet was renamed."""
        self._attr_translation_placeholders = {**self._attr_translation_placeholders, **values}
        # HA caches the formatted name; drop it so the new placeholder is used.
        self.__dict__.pop("name", None)


class ApcControlEntity(ApcEntity):
    """An entity that belongs to one outlet or outlet group and follows its name."""

    def __init__(self, coordinator: ApcCoordinator, key: str, control: ControlPoint) -> None:
        super().__init__(coordinator, key, control.module)
        self._control = control
        self._attr_translation_placeholders = {"name": control.name, "index": control.index}

    @callback
    def _handle_coordinator_update(self) -> None:
        current = next((c for c in self.coordinator.controls if c.uid == self._control.uid), None)
        if current is not None and current.name != self._control.name:
            self._control = current
            self._set_name_placeholders(name=current.name)
        super()._handle_coordinator_update()


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
