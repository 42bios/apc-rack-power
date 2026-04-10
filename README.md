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

## Installation
1. Add this repository URL in HACS as an `Integration` repository.
2. Install `APC Rack Power` from HACS.
3. Restart Home Assistant.
4. Add the integration via `Settings -> Devices & Services`.

## Repository Layout
- `custom_components/apc_enterprise` - integration source
- `hacs.json` - HACS metadata
- `.github/workflows/hacs-validate.yml` - HACS validation workflow
- `.github/workflows/hassfest.yml` - Home Assistant hassfest checks
- `.github/workflows/ci.yml` - basic lint/compile checks

## Support
- Issues: https://github.com/42bios/apc-rack-power/issues
