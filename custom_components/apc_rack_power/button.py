"""Buttons for APC Rack Power: UPS tests and outlet reboots."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ApcConfigEntry
from .const import (
    DEVICE_UPS,
    OID_UPS_CALIBRATION,
    OID_UPS_FLASH_AND_BEEP,
    OID_UPS_TEST,
)
from .coordinator import ApcCoordinator, ApcSnapshot, ControlPoint
from .device_profile import kind_matches
from .entity import ApcControlEntity, ApcEntity, add_entities_when_found

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class ApcButtonDescription(ButtonEntityDescription):
    """A button that writes one value to one OID."""

    oid: str
    value: int
    # Metric that must answer for the button to exist
    requires: str


BUTTONS: tuple[ApcButtonDescription, ...] = (
    ApcButtonDescription(
        key="ups_self_test",
        translation_key="ups_self_test",
        oid=OID_UPS_TEST,
        value=2,
        requires="ups_test_command",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    ApcButtonDescription(
        key="ups_calibration_start",
        translation_key="ups_calibration_start",
        oid=OID_UPS_CALIBRATION,
        value=2,
        requires="ups_calibration_command",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    ApcButtonDescription(
        key="ups_calibration_cancel",
        translation_key="ups_calibration_cancel",
        oid=OID_UPS_CALIBRATION,
        value=3,
        requires="ups_calibration_command",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    ApcButtonDescription(
        key="ups_identify",
        translation_key="ups_identify",
        device_class=ButtonDeviceClass.IDENTIFY,
        oid=OID_UPS_FLASH_AND_BEEP,
        value=2,
        requires="ups_flash_and_beep",
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ApcConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up APC buttons."""
    coordinator = entry.runtime_data

    def _build(d: ApcSnapshot) -> Iterator[tuple[str, Callable[[], Entity]]]:
        if kind_matches(d.device_kind, DEVICE_UPS):
            for description in BUTTONS:
                if d.metrics.get(description.requires) is not None:
                    yield description.key, lambda description=description: ApcCommandButton(coordinator, description)
        for control in d.controls:
            if control.cmd_reboot is not None:
                yield f"{control.uid}_reboot", lambda control=control: ApcRebootButton(coordinator, control)

    add_entities_when_found(coordinator, async_add_entities, _build)


class ApcCommandButton(ApcEntity, ButtonEntity):
    """Writes a fixed value to an OID."""

    entity_description: ApcButtonDescription

    def __init__(self, coordinator: ApcCoordinator, description: ApcButtonDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    async def async_press(self) -> None:
        await self.coordinator.async_write(self.entity_description.oid, self.entity_description.value)


class ApcRebootButton(ApcControlEntity, ButtonEntity):
    """Power cycles an outlet or outlet group (off, then on after the configured delay)."""

    _attr_device_class = ButtonDeviceClass.RESTART

    def __init__(self, coordinator: ApcCoordinator, control: ControlPoint) -> None:
        super().__init__(coordinator, f"{control.uid}_reboot", control)
        self._attr_translation_key = "outlet_group_reboot" if control.kind == DEVICE_UPS else "outlet_reboot"

    async def async_press(self) -> None:
        await self.coordinator.async_control(self._control, "reboot")
