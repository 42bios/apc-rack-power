"""Binary sensors for APC Rack Power."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ApcConfigEntry
from .const import (
    DEVICE_PDU,
    DEVICE_UPS,
    FLAG_ABNORMAL,
    FLAG_BYPASS,
    FLAG_CALIBRATION,
    FLAG_LOW_BATTERY,
    FLAG_ON_BATTERY,
    FLAG_OVERLOAD,
    FLAG_REPLACE_BATTERY,
    FLAG_SELF_TEST,
)
from .coordinator import ApcCoordinator, ApcSnapshot
from .device_profile import flag, kind_matches
from .entity import ApcEntity, add_entities_when_found

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class ApcBinarySensorDescription(BinarySensorEntityDescription):
    """Describes one APC binary sensor; value_fn returns None if unknown."""

    value_fn: Callable[[ApcSnapshot], bool | None]
    kind: str | None = None


def _any(*values: bool | None) -> bool | None:
    known = [value for value in values if value is not None]
    return any(known) if known else None


def _eq(d: ApcSnapshot, key: str, *expected: int) -> bool | None:
    value = d.metric(key)
    return None if value is None else value in expected


def _gt(d: ApcSnapshot, key: str, limit: float) -> bool | None:
    value = d.metric(key)
    return None if not isinstance(value, (int, float)) else value > limit


def _on_battery(d: ApcSnapshot) -> bool | None:
    if (value := flag(d.flags, FLAG_ON_BATTERY)) is not None:
        return value
    return _any(_eq(d, "rfc_output_source", 5), _eq(d, "apc_output_status", 3))


def _low_battery(d: ApcSnapshot) -> bool | None:
    if (value := flag(d.flags, FLAG_LOW_BATTERY)) is not None:
        return value
    return _any(_eq(d, "rfc_battery_status", 3, 4), _eq(d, "apc_battery_status", 3))


def _replace_battery(d: ApcSnapshot) -> bool | None:
    return _any(flag(d.flags, FLAG_REPLACE_BATTERY), _eq(d, "ups_battery_replace_indicator", 2))


def _overload(d: ApcSnapshot) -> bool | None:
    return _any(flag(d.flags, FLAG_OVERLOAD), _gt(d, "ups_output_load", 100))


def _ups_alarm(d: ApcSnapshot) -> bool | None:
    return _any(flag(d.flags, FLAG_ABNORMAL), _gt(d, "ups_alarms_present", 0))


def _bypass(d: ApcSnapshot) -> bool | None:
    flags = [flag(d.flags, position) for position in FLAG_BYPASS]
    return _any(*flags, _eq(d, "rfc_output_source", 4))


def _self_test(d: ApcSnapshot) -> bool | None:
    return _any(flag(d.flags, FLAG_SELF_TEST), _eq(d, "apc_test_result", 4), _eq(d, "rfc_test_result", 5))


def _calibration(d: ApcSnapshot) -> bool | None:
    return _any(flag(d.flags, FLAG_CALIBRATION), _eq(d, "ups_calibration_result", 3))


def _communication(d: ApcSnapshot) -> bool | None:
    return _eq(d, "ups_comm_status", 1)


def _pdu_states(d: ApcSnapshot) -> list[str | int | None]:
    states: list[str | int | None] = [d.metric("pdu_load_state")]
    states += [row.get("load_state") for row in d.tables.get("device_rpdu2", {}).values()]
    states += [row.get("load_state") for row in d.tables.get("phase_rpdu2", {}).values()]
    states += [row.get("load_state") for row in d.tables.get("bank_rpdu2", {}).values()]
    return states


def _pdu_overload(d: ApcSnapshot) -> bool | None:
    states = [state for state in _pdu_states(d) if state is not None]
    legacy = [row.get("legacy_load_state") for row in d.tables.get("load_rpdu", {}).values()]
    legacy = [state for state in legacy if state is not None]
    if not states and not legacy:
        return None
    return 4 in states or 4 in legacy


def _pdu_near_overload(d: ApcSnapshot) -> bool | None:
    states = [state for state in _pdu_states(d) if state is not None]
    legacy = [row.get("legacy_load_state") for row in d.tables.get("load_rpdu", {}).values()]
    legacy = [state for state in legacy if state is not None]
    if not states and not legacy:
        return None
    return 3 in states or 3 in legacy


def _power_supply_alarm(d: ApcSnapshot) -> bool | None:
    return _any(_eq(d, "pdu_power_supply_alarm", 2), _gt(d, "pdu_legacy_power_supply_alarm", 1))


_PROBLEM = BinarySensorDeviceClass.PROBLEM
_RUNNING = BinarySensorDeviceClass.RUNNING

BINARY_SENSORS: tuple[ApcBinarySensorDescription, ...] = (
    ApcBinarySensorDescription(
        key="ups_on_battery", translation_key="ups_on_battery", value_fn=_on_battery, kind=DEVICE_UPS
    ),
    ApcBinarySensorDescription(
        key="ups_low_battery",
        translation_key="ups_low_battery",
        device_class=BinarySensorDeviceClass.BATTERY,
        value_fn=_low_battery,
        kind=DEVICE_UPS,
    ),
    ApcBinarySensorDescription(
        key="ups_replace_battery",
        translation_key="ups_replace_battery",
        device_class=_PROBLEM,
        value_fn=_replace_battery,
        kind=DEVICE_UPS,
    ),
    ApcBinarySensorDescription(
        key="ups_overload", translation_key="ups_overload", device_class=_PROBLEM, value_fn=_overload, kind=DEVICE_UPS
    ),
    ApcBinarySensorDescription(
        key="ups_alarm", translation_key="ups_alarm", device_class=_PROBLEM, value_fn=_ups_alarm, kind=DEVICE_UPS
    ),
    ApcBinarySensorDescription(key="ups_bypass", translation_key="ups_bypass", value_fn=_bypass, kind=DEVICE_UPS),
    ApcBinarySensorDescription(
        key="ups_self_test_running",
        translation_key="ups_self_test_running",
        device_class=_RUNNING,
        value_fn=_self_test,
        kind=DEVICE_UPS,
    ),
    ApcBinarySensorDescription(
        key="ups_calibration_running",
        translation_key="ups_calibration_running",
        device_class=_RUNNING,
        value_fn=_calibration,
        kind=DEVICE_UPS,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    ApcBinarySensorDescription(
        key="ups_communication",
        translation_key="ups_communication",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        value_fn=_communication,
        kind=DEVICE_UPS,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    ApcBinarySensorDescription(
        key="pdu_overload",
        translation_key="pdu_overload",
        device_class=_PROBLEM,
        value_fn=_pdu_overload,
        kind=DEVICE_PDU,
    ),
    ApcBinarySensorDescription(
        key="pdu_near_overload",
        translation_key="pdu_near_overload",
        device_class=_PROBLEM,
        value_fn=_pdu_near_overload,
        kind=DEVICE_PDU,
    ),
    ApcBinarySensorDescription(
        key="pdu_power_supply_alarm",
        translation_key="pdu_power_supply_alarm",
        device_class=_PROBLEM,
        value_fn=_power_supply_alarm,
        kind=DEVICE_PDU,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ApcConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up APC binary sensors."""
    coordinator = entry.runtime_data

    def _build(d: ApcSnapshot) -> Iterator[tuple[str, Callable[[], Entity]]]:
        for description in BINARY_SENSORS:
            if kind_matches(d.device_kind, description.kind) and description.value_fn(d) is not None:
                yield description.key, lambda description=description: ApcBinarySensor(coordinator, description)

    add_entities_when_found(coordinator, async_add_entities, _build)


class ApcBinarySensor(ApcEntity, BinarySensorEntity):
    """A binary sensor described by an ApcBinarySensorDescription."""

    entity_description: ApcBinarySensorDescription

    def __init__(self, coordinator: ApcCoordinator, description: ApcBinarySensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self.snapshot)
