"""Device triggers for APC Rack Power (UPS on battery, overload, card messages ...)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.device_automation import DEVICE_TRIGGER_BASE_SCHEMA
from homeassistant.components.homeassistant.triggers import state as state_trigger
from homeassistant.const import (
    CONF_DEVICE_ID,
    CONF_DOMAIN,
    CONF_ENTITY_ID,
    CONF_PLATFORM,
    CONF_TYPE,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.exceptions import InvalidDeviceAutomationConfig
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.trigger import TriggerActionType, TriggerInfo
from homeassistant.helpers.typing import ConfigType
import voluptuous as vol

from .const import DOMAIN

# trigger type -> (entity domain, entity key, target state; None = every new event)
TRIGGERS: dict[str, tuple[str, str, str | None]] = {
    "on_battery": ("binary_sensor", "ups_on_battery", "on"),
    "on_mains": ("binary_sensor", "ups_on_battery", "off"),
    "low_battery": ("binary_sensor", "ups_low_battery", "on"),
    "replace_battery": ("binary_sensor", "ups_replace_battery", "on"),
    "ups_overload": ("binary_sensor", "ups_overload", "on"),
    "ups_alarm": ("binary_sensor", "ups_alarm", "on"),
    "pdu_overload": ("binary_sensor", "pdu_overload", "on"),
    "pdu_near_overload": ("binary_sensor", "pdu_near_overload", "on"),
    "card_message": ("event", "card_message", None),
}

TRIGGER_SCHEMA = DEVICE_TRIGGER_BASE_SCHEMA.extend({vol.Required(CONF_TYPE): vol.In(TRIGGERS)})


def _entity_key(entry: er.RegistryEntry) -> str | None:
    """Key part of our unique ids ("<entry_id>_<key>")."""
    if entry.platform != DOMAIN or not entry.unique_id or entry.config_entry_id is None:
        return None
    return entry.unique_id.removeprefix(f"{entry.config_entry_id}_")


def _find_entity(hass: HomeAssistant, device_id: str, domain: str, key: str) -> str | None:
    for entry in er.async_entries_for_device(er.async_get(hass), device_id):
        if entry.domain == domain and _entity_key(entry) == key:
            return entry.entity_id
    return None


async def async_get_triggers(hass: HomeAssistant, device_id: str) -> list[dict[str, Any]]:
    """List the triggers the device supports."""
    available = {
        (entry.domain, _entity_key(entry)) for entry in er.async_entries_for_device(er.async_get(hass), device_id)
    }
    return [
        {CONF_PLATFORM: "device", CONF_DOMAIN: DOMAIN, CONF_DEVICE_ID: device_id, CONF_TYPE: trigger_type}
        for trigger_type, (domain, key, _to) in TRIGGERS.items()
        if (domain, key) in available
    ]


async def async_attach_trigger(
    hass: HomeAssistant,
    config: ConfigType,
    action: TriggerActionType,
    trigger_info: TriggerInfo,
) -> CALLBACK_TYPE:
    """Attach a trigger as a state trigger of the matching entity."""
    domain, key, to_state = TRIGGERS[config[CONF_TYPE]]
    entity_id = _find_entity(hass, config[CONF_DEVICE_ID], domain, key)
    if entity_id is None:
        raise InvalidDeviceAutomationConfig(f"No {key} entity for device {config[CONF_DEVICE_ID]}")
    state_config: dict[str, Any] = {CONF_PLATFORM: "state", CONF_ENTITY_ID: entity_id}
    if to_state is None:
        state_config[state_trigger.CONF_NOT_TO] = [STATE_UNAVAILABLE, STATE_UNKNOWN]
    else:
        state_config[state_trigger.CONF_TO] = to_state
    state_config = await state_trigger.async_validate_trigger_config(hass, state_config)
    return await state_trigger.async_attach_trigger(hass, state_config, action, trigger_info, platform_type="device")
