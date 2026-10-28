"""Other APC models, built from the PowerNet-MIB (no hardware at hand)."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .conftest import FakeAgent, make_entry

RPDU2 = "1.3.6.1.4.1.318.1.1.26"
RPDU = "1.3.6.1.4.1.318.1.1.12"
SPDU = "1.3.6.1.4.1.318.1.1.4"
EPDU = "1.3.6.1.4.1.318.1.1.30"
RFC = "1.3.6.1.2.1.33.1"


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)


def _state(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    assert state is not None, f"{entity_id} missing"
    return state.state


def _drop(agent: FakeAgent, *prefixes: str) -> None:
    agent.values = {oid: value for oid, value in agent.values.items() if not oid.startswith(prefixes)}


async def test_legacy_rpdu(hass: HomeAssistant, agent: FakeAgent) -> None:
    """Older Rack PDU firmware without rPDU2: rPDU outlets and phase load."""
    agent.use("pdu")
    _drop(agent, f"{RPDU2}.")
    await _setup(hass, make_entry("PDU", host="192.0.2.11"))

    assert len(hass.states.async_all("switch")) == 24
    assert _state(hass, "switch.pdu_outlet_5") == "on"
    state = hass.states.get("sensor.pdu_phase_current")
    assert state.state == "1.2"
    assert state.attributes["overload_threshold"] == 16

    await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.pdu_outlet_5"}, blocking=True)
    assert (f"{RPDU}.3.3.1.1.4.5", 2) in agent.writes


async def test_masterswitch_spdu(hass: HomeAssistant, agent: FakeAgent) -> None:
    """MasterSwitch (sPDU) outlets: state and command share one OID."""
    agent.use("pdu")
    _drop(agent, f"{RPDU2}.", f"{RPDU}.")
    await _setup(hass, make_entry("PDU", host="192.0.2.11"))

    assert len(hass.states.async_all("switch")) == 24
    await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.pdu_outlet_7"}, blocking=True)
    await hass.services.async_call("button", "press", {"entity_id": "button.pdu_outlet_7_reboot"}, blocking=True)
    assert agent.writes == [(f"{SPDU}.4.2.1.3.7", 2), (f"{SPDU}.4.2.1.3.7", 3)]


async def test_easy_pdu(hass: HomeAssistant, agent: FakeAgent) -> None:
    """ePDU (Easy PDU): device and phase values, outlets without reboot or names."""
    agent.values = {
        "1.3.6.1.2.1.1.1.0": "APC Easy PDU",
        "1.3.6.1.2.1.1.5.0": "epdu",
        f"{EPDU}.2.1.1.4.1": "EPDU1016S",
        f"{EPDU}.2.1.1.5.1": "ES0000000001",
        f"{EPDU}.2.1.1.6.1": 1,
        f"{EPDU}.2.1.1.7.1": 450,
        f"{EPDU}.2.1.1.9.1": 480,
        f"{EPDU}.2.1.1.10.1": 937,
        f"{EPDU}.2.1.1.11.1": 1234567,
        f"{EPDU}.4.2.1.2.1": 1,
        f"{EPDU}.4.2.1.3.1": 1,
        f"{EPDU}.4.2.1.4.1": 2301,
        f"{EPDU}.4.2.1.5.1": 196,
        f"{EPDU}.4.2.1.6.1": 450,
        f"{EPDU}.4.2.1.9.1": 937,
    }
    for outlet in range(1, 5):
        agent.values[f"{EPDU}.6.1.1.2.{outlet}"] = 1
        agent.values[f"{EPDU}.6.1.1.3.{outlet}"] = outlet
        agent.values[f"{EPDU}.6.1.1.4.{outlet}"] = 2 if outlet != 4 else 1
        agent.values[f"{EPDU}.6.2.1.4.{outlet}"] = 1
    await _setup(hass, make_entry("ePDU", host="192.0.2.12"))

    assert _state(hass, "sensor.epdu_power") == "450"
    assert _state(hass, "sensor.epdu_apparent_power") == "480"
    assert _state(hass, "sensor.epdu_energy") == "1234.6"
    assert _state(hass, "sensor.epdu_power_factor") == "0.94"
    assert _state(hass, "sensor.epdu_phase_current") == "1.96"
    assert _state(hass, "sensor.epdu_phase_voltage") == "230.1"
    assert hass.states.get("sensor.epdu_phase_load_state") is None
    assert [s.state for s in sorted(hass.states.async_all("switch"), key=lambda s: s.entity_id)] == [
        "on",
        "on",
        "on",
        "off",
    ]
    assert hass.states.get("switch.epdu_outlet_1").attributes["friendly_name"] == "ePDU Outlet 1"
    assert hass.states.async_all("button") == []
    assert hass.states.async_all("text") == []

    await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.epdu_outlet_2"}, blocking=True)
    assert (f"{EPDU}.6.2.1.4.2", 2) in agent.writes


async def test_three_phase_ups(hass: HomeAssistant, agent: FakeAgent) -> None:
    """A UPS with three input and output lines gets per-line sensors."""
    agent.use("ups")
    for line, voltage in ((2, 231), (3, 232)):
        for column, value in ((2, 500), (3, voltage), (4, 15), (5, 340)):
            agent.values[f"{RFC}.3.3.1.{column}.{line}"] = value
        for column, value in ((2, voltage), (3, 12), (4, 280), (5, 11)):
            agent.values[f"{RFC}.4.4.1.{column}.{line}"] = value
    await _setup(hass, make_entry("UPS"))

    assert _state(hass, "sensor.ups_input_l1_voltage") == "229"
    assert _state(hass, "sensor.ups_input_l3_voltage") == "232"
    assert _state(hass, "sensor.ups_input_l2_current") == "1.5"
    assert _state(hass, "sensor.ups_output_l2_power") == "280"
    assert _state(hass, "sensor.ups_output_l3_current") == "1.2"


async def test_single_phase_ups_has_no_line_sensors(hass: HomeAssistant, agent: FakeAgent) -> None:
    agent.use("ups")
    await _setup(hass, make_entry("UPS"))
    assert hass.states.get("sensor.ups_input_l1_voltage") is None


async def test_metered_outlets_and_banks(hass: HomeAssistant, agent: FakeAgent) -> None:
    """Metered-by-outlet values and bank currents with thresholds."""
    agent.use("pdu")
    agent.values.update(
        {
            f"{RPDU2}.9.4.3.1.2.1": 1,
            f"{RPDU2}.9.4.3.1.3.1": "Server",
            f"{RPDU2}.9.4.3.1.5.1": 2,
            f"{RPDU2}.9.4.3.1.6.1": 12,
            f"{RPDU2}.9.4.3.1.7.1": 250,
            f"{RPDU2}.9.4.3.1.11.1": 5000,
            f"{RPDU2}.8.3.1.2.1": 1,
            f"{RPDU2}.8.3.1.3.1": 1,
            f"{RPDU2}.8.3.1.4.1": 2,
            f"{RPDU2}.8.3.1.5.1": 64,
            f"{RPDU2}.8.3.1.6.1": 80,
            f"{RPDU2}.8.1.1.5.1": 0,
            f"{RPDU2}.8.1.1.6.1": 13,
            f"{RPDU2}.8.1.1.7.1": 16,
        }
    )
    await _setup(hass, make_entry("PDU", host="192.0.2.11"))

    assert _state(hass, "sensor.pdu_server_power") == "250"
    assert _state(hass, "sensor.pdu_server_current") == "1.2"
    assert _state(hass, "sensor.pdu_server_energy") == "500.0"
    bank = hass.states.get("sensor.pdu_bank_1_current")
    assert bank.state == "6.4"
    assert bank.attributes["near_overload_threshold"] == 13
    assert _state(hass, "sensor.pdu_bank_1_load_state") == "normal"


async def test_environment_monitors(hass: HomeAssistant, agent: FakeAgent) -> None:
    """Integrated (iem, Fahrenheit) and modular (mem) environment sensors."""
    agent.use("ups")
    iem = "1.3.6.1.4.1.318.1.1.10.2.3.2.1"
    mem = "1.3.6.1.4.1.318.1.1.10.4.2"
    agent.values.update(
        {
            f"{iem}.2.1": "Rack Top",
            f"{iem}.3.1": 2,
            f"{iem}.4.1": 77,
            f"{iem}.5.1": 2,
            f"{iem}.6.1": 40,
            f"{mem}.1.0": 1,
            f"{mem}.3.1.3.1.1": "Rack Bottom",
            f"{mem}.3.1.5.1.1": 21,
            f"{mem}.3.1.6.1.1": 35,
            f"{mem}.3.1.7.1.1": 2,
            f"{mem}.3.1.8.1.1": 1,
        }
    )
    await _setup(hass, make_entry("UPS"))

    assert _state(hass, "sensor.ups_rack_top_temperature") == "25.0"
    assert _state(hass, "sensor.ups_rack_top_humidity") == "40"
    assert _state(hass, "sensor.ups_rack_bottom_temperature") == "21"
    assert _state(hass, "sensor.ups_rack_bottom_humidity") == "35"
