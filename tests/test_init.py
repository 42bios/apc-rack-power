"""Setup, entities and commands of APC Rack Power."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.apc_rack_power.const import DOMAIN
from custom_components.apc_rack_power.snmp_client import ApcSnmpAuthError, ApcSnmpError

from .conftest import FakeAgent, make_entry


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _state(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    assert state is not None, f"{entity_id} missing"
    return state.state


async def test_ups_entities(hass: HomeAssistant, agent: FakeAgent) -> None:
    """A Smart-UPS SRT with AP9641 card and two temperature probes."""
    agent.use("ups")
    entry = make_entry("UPS")
    await _setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED

    assert _state(hass, "sensor.ups_output_power") == "228"
    assert _state(hass, "sensor.ups_output_apparent_power") == "279"
    assert _state(hass, "sensor.ups_output_energy") == "1286.82"
    assert _state(hass, "sensor.ups_output_current") == "1.2"
    assert _state(hass, "sensor.ups_battery_charge") == "100"
    assert _state(hass, "sensor.ups_output_source") == "normal"
    assert _state(hass, "sensor.ups_output_status") == "on_line"
    assert _state(hass, "sensor.ups_battery_status") == "normal"
    assert _state(hass, "sensor.ups_self_test_result") == "passed"
    assert _state(hass, "sensor.ups_last_transfer_cause") == "self_test"
    assert _state(hass, "sensor.ups_battery_installed") == "2024-07-12"
    assert _state(hass, "sensor.ups_battery_replacement_due") == "2030-07-11"
    assert _state(hass, "sensor.ups_external_battery_model") == "XBP48RM1U2-LI"
    assert _state(hass, "sensor.ups_port_1_temp_1_temperature") == "25"
    assert _state(hass, "sensor.ups_port_2_temp_2_temperature") == "27"
    assert hass.states.get("sensor.ups_port_1_temp_1_humidity") is None

    assert _state(hass, "binary_sensor.ups_on_battery") == STATE_OFF
    assert _state(hass, "binary_sensor.ups_replace_battery") == STATE_OFF
    assert _state(hass, "binary_sensor.ups_overload") == STATE_OFF
    assert _state(hass, "binary_sensor.ups_ups_communication") == STATE_ON

    assert _state(hass, "switch.ups_outlet_group_1") == STATE_ON
    assert _state(hass, "switch.ups_outlet_group_2") == STATE_OFF
    assert hass.states.get("button.ups_start_self_test") is not None
    assert hass.states.get("button.ups_outlet_group_1_reboot") is not None
    assert _state(hass, "select.ups_alarm_beeper") == "timed"
    # No PDU entities on a UPS
    assert hass.states.get("sensor.ups_phase_current") is None


async def test_pdu_entities(hass: HomeAssistant, agent: FakeAgent) -> None:
    """A switched Rack PDU AP8959EU3 (rPDU2)."""
    agent.use("pdu")
    entry = make_entry("PDU", host="192.0.2.11")
    await _setup(hass, entry)

    assert _state(hass, "sensor.pdu_phase_current") == "1.2"
    assert _state(hass, "sensor.pdu_phase_voltage") == "230"
    assert _state(hass, "sensor.pdu_power") == "220"
    assert _state(hass, "sensor.pdu_energy") == "4801.5"
    assert _state(hass, "sensor.pdu_load") == "5.9"
    assert _state(hass, "sensor.pdu_power_factor") == "0.8"
    assert _state(hass, "sensor.pdu_load_state") == "normal"
    assert _state(hass, "binary_sensor.pdu_overload") == STATE_OFF

    outlets = [state for state in hass.states.async_all("switch")]
    assert len(outlets) == 24
    assert all(state.state == STATE_ON for state in outlets)
    # The UPS-only entities and the legacy tables are not used
    assert hass.states.get("sensor.pdu_output_power") is None
    assert hass.states.get("switch.pdu_outlet_group_1") is None


async def test_outlet_commands(hass: HomeAssistant, agent: FakeAgent) -> None:
    """Switching and rebooting write rPDU2OutletSwitchedControlCommand."""
    agent.use("pdu")
    await _setup(hass, make_entry("PDU", host="192.0.2.11"))

    await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.pdu_outlet_3"}, blocking=True)
    await hass.services.async_call("switch", "turn_on", {"entity_id": "switch.pdu_outlet_3"}, blocking=True)
    await hass.services.async_call("button", "press", {"entity_id": "button.pdu_outlet_3_reboot"}, blocking=True)
    command = "1.3.6.1.4.1.318.1.1.26.9.2.4.1.5.3"
    assert agent.writes == [(command, 2), (command, 1), (command, 3)]


async def test_ups_commands(hass: HomeAssistant, agent: FakeAgent) -> None:
    """Self test and beeper write the PowerNet control OIDs."""
    agent.use("ups")
    await _setup(hass, make_entry("UPS"))

    await hass.services.async_call("button", "press", {"entity_id": "button.ups_start_self_test"}, blocking=True)
    await hass.services.async_call(
        "select", "select_option", {"entity_id": "select.ups_alarm_beeper", "option": "mute"}, blocking=True
    )
    assert agent.writes == [("1.3.6.1.4.1.318.1.1.1.7.2.2.0", 2), ("1.3.6.1.4.1.318.1.1.1.5.2.4.0", 4)]


async def test_write_failure_creates_issue(hass: HomeAssistant, agent: FakeAgent) -> None:
    """A rejected command raises and creates a repair issue."""
    agent.use("pdu")
    entry = make_entry("PDU", host="192.0.2.11")
    await _setup(hass, entry)
    agent.set_error = ApcSnmpError("timeout")

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.pdu_outlet_1"}, blocking=True)
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"write_failed_{entry.entry_id}")


async def test_battery_replace_issue(hass: HomeAssistant, agent: FakeAgent) -> None:
    """upsAdvBatteryReplaceIndicator = 2 raises a repair issue."""
    agent.use("ups")
    agent.values["1.3.6.1.4.1.318.1.1.1.2.2.4.0"] = 2
    entry = make_entry("UPS")
    await _setup(hass, entry)
    assert _state(hass, "binary_sensor.ups_replace_battery") == STATE_ON
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"battery_replace_{entry.entry_id}")


async def test_unreachable_device_retries(hass: HomeAssistant, agent: FakeAgent) -> None:
    """No answer -> setup is retried."""
    agent.get_error = ApcSnmpError("timeout")
    entry = make_entry("UPS")
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_auth_error_starts_reauth(hass: HomeAssistant, agent: FakeAgent) -> None:
    """Rejected SNMPv3 credentials start a reauth flow."""
    agent.get_error = ApcSnmpAuthError("wrong digest")
    entry = make_entry("UPS", snmp_version="v3", v3_username="ha")
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert any(flow["context"]["source"] == "reauth" for flow in hass.config_entries.flow.async_progress())


async def test_migration_moves_credentials(hass: HomeAssistant, agent: FakeAgent) -> None:
    """Entries of 0.3.x kept credentials in the options."""
    agent.use("ups")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="UPS",
        unique_id="192.0.2.10",
        version=1,
        minor_version=1,
        data={
            "host": "192.0.2.10",
            "port": 161,
            "name": "UPS",
            "snmp_version": "v2c",
            "community": "old",
            "scan_interval": 30,
            "pdu_nominal_watts": 0,
        },
        options={"community": "new", "write_community": "private", "scan_interval": 60, "temperature_scale": "celsius"},
    )
    await _setup(hass, entry)
    assert entry.minor_version == 2
    assert entry.data["community"] == "new"
    assert entry.data["write_community"] == "private"
    assert "scan_interval" not in entry.data
    assert entry.options == {"scan_interval": 60}


async def test_unload(hass: HomeAssistant, agent: FakeAgent) -> None:
    """The entry unloads cleanly."""
    agent.use("ups")
    entry = make_entry("UPS")
    await _setup(hass, entry)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED
