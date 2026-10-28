"""Outlet names, settings, card messages, device triggers, polling and device removal."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, patch

from homeassistant.components.device_automation import DeviceAutomationType
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_get_device_automations,
)

from custom_components.apc_rack_power import async_remove_config_entry_device
from custom_components.apc_rack_power.const import DOMAIN
from custom_components.apc_rack_power.traps import TrapInfo

from .conftest import FakeAgent, make_entry
from .test_init import _add_nps_guest

UPS_FLAGS = "1.3.6.1.4.1.318.1.1.1.11.1.1.0"
ON_LINE_FLAGS = "0001010000000000001000000000000000000000000000000010000000000000"
ON_BATTERY_FLAGS = "0100010000000000001000000000000000000000000000000010000000000000"


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)


async def _enable(hass: HomeAssistant, entry: MockConfigEntry, *entity_ids: str) -> None:
    registry = er.async_get(hass)
    for entity_id in entity_ids:
        registry.async_update_entity(entity_id, disabled_by=None)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)


def _state(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    assert state is not None, f"{entity_id} missing"
    return state.state


def _main_device(hass: HomeAssistant, entry: MockConfigEntry) -> dr.DeviceEntry:
    return next(
        d
        for d in dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
        if (DOMAIN, entry.entry_id) in d.identifiers
    )


async def test_rename_outlet(hass: HomeAssistant, agent: FakeAgent) -> None:
    """The name field writes the name to the PDU; switch and reboot button follow."""
    agent.use("pdu")
    await _setup(hass, make_entry("PDU", host="192.0.2.11"))
    assert _state(hass, "text.pdu_outlet_3_name") == "Outlet 3"

    await hass.services.async_call(
        "text", "set_value", {"entity_id": "text.pdu_outlet_3_name", "value": " Server "}, blocking=True
    )
    await hass.async_block_till_done(wait_background_tasks=True)

    assert ("1.3.6.1.4.1.318.1.1.26.9.2.1.1.3.3", "Server") in agent.writes
    assert _state(hass, "text.pdu_outlet_3_name") == "Server"
    assert hass.states.get("switch.pdu_outlet_3").attributes["friendly_name"] == "PDU Server"
    assert hass.states.get("button.pdu_outlet_3_reboot").attributes["friendly_name"] == "PDU Server reboot"


async def test_outlet_and_phase_settings(hass: HomeAssistant, agent: FakeAgent) -> None:
    """Outlet delays and phase thresholds are disabled by default and writable."""
    agent.use("pdu")
    entry = make_entry("PDU", host="192.0.2.11")
    await _setup(hass, entry)
    registry = er.async_get(hass)
    for entity_id in ("number.pdu_outlet_3_power_on_delay", "number.pdu_phase_1_overload_threshold"):
        assert registry.async_get(entity_id).disabled_by is er.RegistryEntryDisabler.INTEGRATION

    await _enable(hass, entry, "number.pdu_outlet_3_reboot_duration", "number.pdu_phase_1_overload_threshold")
    assert _state(hass, "number.pdu_outlet_3_reboot_duration") == "5"
    assert _state(hass, "number.pdu_phase_1_overload_threshold") == "16"

    await hass.services.async_call(
        "number", "set_value", {"entity_id": "number.pdu_outlet_3_reboot_duration", "value": 10}, blocking=True
    )
    await hass.services.async_call(
        "number", "set_value", {"entity_id": "number.pdu_phase_1_overload_threshold", "value": 15}, blocking=True
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    assert ("1.3.6.1.4.1.318.1.1.26.9.2.1.1.7.3", 10) in agent.writes
    assert ("1.3.6.1.4.1.318.1.1.26.6.1.1.7.1", 15) in agent.writes
    assert _state(hass, "number.pdu_outlet_3_reboot_duration") == "10"
    assert _state(hass, "number.pdu_phase_1_overload_threshold") == "15"


async def test_low_battery_runtime(hass: HomeAssistant, agent: FakeAgent) -> None:
    """The low-battery runtime is shown in minutes and written as TimeTicks."""
    agent.use("ups")
    entry = make_entry("UPS")
    await _setup(hass, entry)
    await _enable(hass, entry, "number.ups_low_battery_runtime")
    assert _state(hass, "number.ups_low_battery_runtime") == "2.0"

    await hass.services.async_call(
        "number", "set_value", {"entity_id": "number.ups_low_battery_runtime", "value": 3}, blocking=True
    )
    assert ("1.3.6.1.4.1.318.1.1.1.5.2.8.0", 18000) in agent.writes


async def test_card_message_event(hass: HomeAssistant, agent: FakeAgent) -> None:
    """With traps enabled, card messages appear on an event entity."""
    agent.use("ups")
    entry = make_entry("UPS")
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={"trap_enabled": True, "trap_port": 1162})
    with patch("custom_components.apc_rack_power.async_register_trap_handler", AsyncMock(return_value=lambda: None)):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)

    assert _state(hass, "event.ups_card_message") == "unknown"
    entry.runtime_data.handle_trap(
        TrapInfo("192.0.2.10", "1.3.6.1.4.1.318.0.5", {"1.3.6.1.4.1.318.2.3.3.0": "UPS: On battery power"})
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    state = hass.states.get("event.ups_card_message")
    assert state.attributes["event_type"] == "message"
    assert state.attributes["message"] == "UPS: On battery power"


async def test_device_triggers_and_fast_polling(hass: HomeAssistant, agent: FakeAgent) -> None:
    """Device triggers fire on battery operation, which also speeds up polling."""
    agent.use("ups")
    entry = make_entry("UPS")
    await _setup(hass, entry)
    device = _main_device(hass, entry)

    triggers = await async_get_device_automations(hass, DeviceAutomationType.TRIGGER, device.id)
    types = {trigger["type"] for trigger in triggers}
    assert {"on_battery", "on_mains", "low_battery", "replace_battery", "ups_overload", "ups_alarm"} <= types
    assert "pdu_overload" not in types

    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": [
                {
                    "triggers": [{"platform": "device", "domain": DOMAIN, "device_id": device.id, "type": t}],
                    "actions": [{"event": f"test_{t}"}],
                }
                for t in ("on_battery", "on_mains")
            ]
        },
    )
    on_battery = async_capture_events(hass, "test_on_battery")
    on_mains = async_capture_events(hass, "test_on_mains")
    coordinator = entry.runtime_data
    assert coordinator.update_interval == timedelta(seconds=30)

    agent.values[UPS_FLAGS] = ON_BATTERY_FLAGS
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert len(on_battery) == 1
    assert coordinator.update_interval == timedelta(seconds=5)

    agent.values[UPS_FLAGS] = ON_LINE_FLAGS
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert len(on_mains) == 1
    assert coordinator.update_interval == timedelta(seconds=30)


async def test_pdu_triggers(hass: HomeAssistant, agent: FakeAgent) -> None:
    agent.use("pdu")
    entry = make_entry("PDU", host="192.0.2.11")
    await _setup(hass, entry)
    triggers = await async_get_device_automations(hass, DeviceAutomationType.TRIGGER, _main_device(hass, entry).id)
    types = {trigger["type"] for trigger in triggers}
    assert {"pdu_overload", "pdu_near_overload"} <= types
    assert "on_battery" not in types


async def test_remove_stale_chained_pdu(hass: HomeAssistant, agent: FakeAgent) -> None:
    """Only devices the PDU no longer reports can be deleted."""
    agent.use("pdu")
    _add_nps_guest(agent)
    entry = make_entry("PDU", host="192.0.2.11")
    await _setup(hass, entry)
    registry = dr.async_get(hass)
    devices = dr.async_entries_for_config_entry(registry, entry.entry_id)
    main = _main_device(hass, entry)
    guest = next(d for d in devices if d.id != main.id)
    stale = registry.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, f"{entry.entry_id}_module_7")}
    )
    assert not await async_remove_config_entry_device(hass, entry, main)
    assert not await async_remove_config_entry_device(hass, entry, guest)
    assert await async_remove_config_entry_device(hass, entry, stale)


async def test_setup_does_not_wait_for_table_discovery(hass: HomeAssistant, agent: FakeAgent) -> None:
    """Slow table walks run in the background: setup finishes first, outlets follow."""
    agent.use("pdu")
    gate = asyncio.Event()
    walk = agent.walk

    async def slow_walk(root: str, max_rows: int = 1024) -> dict:
        if not root.lstrip(".").startswith("1.3.6.1.2.1.2.2.1.6"):  # the MAC is read right away
            await gate.wait()
        return await walk(root, max_rows)

    agent.walk = slow_walk  # type: ignore[method-assign]
    entry = make_entry("PDU", host="192.0.2.11")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert entry.unique_id == "00:c0:b7:00:00:02"
    assert hass.states.async_all("switch") == []

    gate.set()
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(hass.states.async_all("switch")) == 24
