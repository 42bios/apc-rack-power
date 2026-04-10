# APC Rack Power

Home Assistant custom integration for APC UPS and Rack PDU devices via SNMP.

## Features
- Auto-detect APC device type (UPS vs PDU)
- UPS telemetry, battery and runtime sensors
- PDU metering sensors (load, power, energy, phase values)
- Outlet and outlet-group control via switch entities
- Custom OID support for advanced users
- Config flow + options flow (no YAML required)

## Tested Hardware
- APC Smart-UPS SRT3000UXI-NCLI
- APC External Battery Pack XBP48RM1U2-LI (connected to SRT3000UXI-NCLI)
- APC Switched Rack PDU AP8959EU3

## Installation (HACS Custom Repository)
1. Add this repository URL in HACS as an `Integration` repository.
2. Install `APC Rack Power` from HACS.
3. Restart Home Assistant.
4. Add the integration in `Settings -> Devices & Services`.

## Repository Layout
- `custom_components/apc_enterprise` - integration code
- `hacs.json` - HACS metadata
- `.github/workflows/hacs-validate.yml` - HACS validation action
- `.github/workflows/hassfest.yml` - Home Assistant manifest checks

## Support
- Issues: https://github.com/42bios/apc-rack-power/issues
