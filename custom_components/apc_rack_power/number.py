"""Number entities for APC Rack Power: device settings (disabled by default)."""

from __future__ import annotations

from collections.abc import Callable, Iterator

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import EntityCategory, UnitOfElectricCurrent, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ApcConfigEntry
from .const import DEVICE_PDU, DEVICE_UPS, OID_PHASE_NEAR_OVERLOAD, OID_PHASE_OVERLOAD, OID_UPS_LOW_BATTERY_RUNTIME
from .coordinator import ApcCoordinator, ApcSnapshot, ControlPoint
from .device_profile import kind_matches
from .entity import ApcControlEntity, ApcEntity, add_entities_when_found

PARALLEL_UPDATES = 1

# Settings of one outlet: (key, translation key)
OUTLET_SETTINGS = (
    ("on_delay", "outlet_on_delay"),
    ("off_delay", "outlet_off_delay"),
    ("reboot_duration", "outlet_reboot_duration"),
)
PHASE_THRESHOLDS = (
    ("near_overload_threshold", OID_PHASE_NEAR_OVERLOAD, "phase_near_overload_threshold"),
    ("overload_threshold", OID_PHASE_OVERLOAD, "phase_overload_threshold"),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ApcConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up setting entities."""
    coordinator = entry.runtime_data

    def _build(d: ApcSnapshot) -> Iterator[tuple[str, Callable[[], Entity]]]:
        for control in d.controls:
            if not kind_matches(d.device_kind, control.kind):
                continue
            for key, translation_key in OUTLET_SETTINGS:
                if key in d.control_settings.get(control.uid, {}):
                    yield (
                        f"{control.uid}_{key}",
                        lambda control=control, key=key, tk=translation_key: ApcOutletSettingNumber(
                            coordinator, control, key, tk
                        ),
                    )
        if kind_matches(d.device_kind, DEVICE_PDU):
            for index, row in d.tables.get("phase_rpdu2", {}).items():
                if row.get("module", 1) not in (None, 1):
                    continue
                for column, oid, translation_key in PHASE_THRESHOLDS:
                    if isinstance(row.get(column), int):
                        yield (
                            f"pdu_phase_{index}_{column}",
                            lambda index=index, column=column, oid=oid, tk=translation_key: ApcPhaseThresholdNumber(
                                coordinator, index, column, oid, tk
                            ),
                        )
        if kind_matches(d.device_kind, DEVICE_UPS) and isinstance(d.metric("ups_low_battery_runtime"), int):
            yield "ups_low_battery_runtime", lambda: ApcLowBatteryRuntimeNumber(coordinator)

    add_entities_when_found(coordinator, async_add_entities, _build)


class ApcOutletSettingNumber(ApcControlEntity, NumberEntity):
    """Power-on delay, power-off delay or reboot duration of an outlet."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False
    _attr_mode = NumberMode.BOX
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_device_class = NumberDeviceClass.DURATION

    def __init__(self, coordinator: ApcCoordinator, control: ControlPoint, key: str, translation_key: str) -> None:
        super().__init__(coordinator, f"{control.uid}_{key}", control)
        self._key = key
        self._attr_translation_key = translation_key
        low, high = control.reboot_range if key == "reboot_duration" else control.delay_range
        self._attr_native_min_value = low
        self._attr_native_max_value = high

    @property
    def native_value(self) -> int | None:
        return self.snapshot.control_settings.get(self._control.uid, {}).get(self._key)

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_control_setting(self._control, self._key, int(value))


class ApcPhaseThresholdNumber(ApcEntity, NumberEntity):
    """Near-overload or overload current threshold of a PDU phase."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False
    _attr_mode = NumberMode.BOX
    _attr_native_step = 1
    _attr_native_min_value = 0
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_device_class = NumberDeviceClass.CURRENT

    def __init__(self, coordinator: ApcCoordinator, index: str, column: str, oid: str, translation_key: str) -> None:
        super().__init__(coordinator, f"pdu_phase_{index}_{column}")
        self._index = index
        self._column = column
        self._oid = oid
        self._attr_translation_key = translation_key
        self._attr_translation_placeholders = {"phase": index}
        rating = coordinator.data.metric("pdu_max_current") if coordinator.data else None
        self._attr_native_max_value = rating if isinstance(rating, int) and rating > 0 else 63

    @property
    def native_value(self) -> int | None:
        return self.snapshot.tables.get("phase_rpdu2", {}).get(self._index, {}).get(self._column)

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_table_value("phase_rpdu2", self._index, self._column, self._oid, int(value))


class ApcLowBatteryRuntimeNumber(ApcEntity, NumberEntity):
    """Remaining runtime at which the UPS reports a low battery."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False
    _attr_mode = NumberMode.BOX
    _attr_native_step = 1
    _attr_native_min_value = 0
    _attr_native_max_value = 60
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_device_class = NumberDeviceClass.DURATION
    _attr_translation_key = "ups_low_battery_runtime"

    def __init__(self, coordinator: ApcCoordinator) -> None:
        super().__init__(coordinator, "ups_low_battery_runtime")

    @property
    def native_value(self) -> float | None:
        ticks = self.snapshot.metric("ups_low_battery_runtime")
        return round(ticks / 6000, 1) if isinstance(ticks, int) else None

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_write(OID_UPS_LOW_BATTERY_RUNTIME, int(value * 6000), "timeticks")
