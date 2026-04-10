# APC Rack Power

[![CI](https://github.com/42bios/apc-rack-power/actions/workflows/ci.yml/badge.svg)](https://github.com/42bios/apc-rack-power/actions/workflows/ci.yml)
![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange)
[![Release](https://img.shields.io/github/v/release/42bios/apc-rack-power)](https://github.com/42bios/apc-rack-power/releases)
[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Home Assistant custom integration for APC UPS and Rack PDU devices via SNMP.

<img src="https://raw.githubusercontent.com/42bios/apc-rack-power/main/custom_components/apc_enterprise/brand/logo.png" alt="APC Rack Power Logo" width="220">

## Highlights
- Auto-detect APC device type (UPS vs PDU)
- UPS telemetry: battery status, runtime, input/output metrics
- PDU telemetry: load, watts, energy, phase voltage/current/power
- Switching control for PDU outlets and UPS outlet groups (when supported)
- Config flow and options flow (no YAML required)
- Advanced custom OID polling support

## Tested Hardware
- APC Smart-UPS SRT3000UXI-NCLI
- APC External Battery Pack XBP48RM1U2-LI (connected to SRT3000UXI-NCLI)
- APC Switched Rack PDU AP8959EU3

## HACS Installation (Recommended)

[![Open your Home Assistant instance and open the APC Rack Power repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=42bios&repository=apc-rack-power&category=integration)

1. Open HACS in Home Assistant.
2. Go to `Integrations`.
3. Open menu (three dots) -> `Custom repositories`.
4. Repository URL: `https://github.com/42bios/apc-rack-power`
5. Category: `Integration`
6. Install `APC Rack Power` and restart Home Assistant.
7. Add integration in `Settings -> Devices & Services -> Add Integration`.

## Manual Installation
1. Copy `custom_components/apc_enterprise` into your Home Assistant config folder.
2. Restart Home Assistant.
3. Add integration in `Settings -> Devices & Services -> Add Integration`.

## Repository Layout
- `custom_components/apc_enterprise` - integration source
- `hacs.json` - HACS metadata
- `.github/workflows/hacs-validate.yml` - HACS validation workflow
- `.github/workflows/hassfest.yml` - Home Assistant hassfest checks
- `.github/workflows/ci.yml` - basic lint/compile checks

## Support
- Issues: https://github.com/42bios/apc-rack-power/issues
