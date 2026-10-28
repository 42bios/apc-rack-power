"""Event entity for APC Rack Power: messages the card sends as SNMP traps."""

from __future__ import annotations

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ApcConfigEntry
from .const import CONF_TRAP_ENABLED
from .coordinator import ApcCoordinator
from .entity import ApcEntity

PARALLEL_UPDATES = 0

EVENT_TYPE = "message"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ApcConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the message entity when traps are received."""
    if entry.options.get(CONF_TRAP_ENABLED, False):
        async_add_entities([ApcTrapEvent(entry.runtime_data)])


class ApcTrapEvent(ApcEntity, EventEntity):
    """The latest message (SNMP trap) of the network card."""

    _attr_translation_key = "card_message"
    _attr_event_types = [EVENT_TYPE]

    def __init__(self, coordinator: ApcCoordinator) -> None:
        super().__init__(coordinator, "card_message")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.coordinator.async_add_trap_listener(self._on_trap))

    @callback
    def _on_trap(self, message: str | None, trap_oid: str) -> None:
        self._trigger_event(EVENT_TYPE, {"message": message, "trap_oid": trap_oid})
        self.async_write_ha_state()
