"""Select entities for APC Rack Power."""

from __future__ import annotations

from collections.abc import Callable, Iterator

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ApcConfigEntry
from .const import ALARM_BEEPER, DEVICE_UPS, OID_UPS_ALARM_BEEPER
from .coordinator import ApcCoordinator, ApcSnapshot
from .device_profile import kind_matches
from .entity import ApcEntity, add_entities_when_found

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ApcConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up APC selects."""
    coordinator = entry.runtime_data

    def _build(d: ApcSnapshot) -> Iterator[tuple[str, Callable[[], Entity]]]:
        if kind_matches(d.device_kind, DEVICE_UPS) and d.metric("ups_alarm_beeper") in ALARM_BEEPER:
            yield "ups_alarm_beeper", lambda: ApcAlarmBeeperSelect(coordinator)

    add_entities_when_found(coordinator, async_add_entities, _build)


class ApcAlarmBeeperSelect(ApcEntity, SelectEntity):
    """When the UPS beeps on alarms (timed, at low battery, never, muted)."""

    _attr_translation_key = "ups_alarm_beeper"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = list(ALARM_BEEPER.values())

    def __init__(self, coordinator: ApcCoordinator) -> None:
        super().__init__(coordinator, "ups_alarm_beeper")

    @property
    def current_option(self) -> str | None:
        return ALARM_BEEPER.get(self.snapshot.metric("ups_alarm_beeper"))

    async def async_select_option(self, option: str) -> None:
        value = next(raw for raw, name in ALARM_BEEPER.items() if name == option)
        await self.coordinator.async_write(OID_UPS_ALARM_BEEPER, value)
