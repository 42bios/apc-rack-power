# APC Rack Power

[![CI](https://github.com/42bios/apc-rack-power/actions/workflows/ci.yml/badge.svg)](https://github.com/42bios/apc-rack-power/actions/workflows/ci.yml)
[![HACS](https://github.com/42bios/apc-rack-power/actions/workflows/hacs-validate.yml/badge.svg)](https://github.com/42bios/apc-rack-power/actions/workflows/hacs-validate.yml)
[![Hassfest](https://github.com/42bios/apc-rack-power/actions/workflows/hassfest.yml/badge.svg)](https://github.com/42bios/apc-rack-power/actions/workflows/hassfest.yml)
![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange)
[![Release](https://img.shields.io/github/v/release/42bios/apc-rack-power)](https://github.com/42bios/apc-rack-power/releases)

Home Assistant custom integration for APC UPS and Rack PDU devices via SNMP (v2c/v3).

<img src="https://raw.githubusercontent.com/42bios/apc-rack-power/main/custom_components/apc_rack_power/brand/logo.png" alt="APC Rack Power Logo" width="160">

## Highlights
- Auto-detect APC device type (UPS vs PDU)
- UPS telemetry: battery, runtime, input/output, alarms
- PDU telemetry: load, watts, energy, phase voltage/current/power factor
- Switching support for PDU outlets and UPS outlet groups (when supported)
- Config flow and options flow (no YAML required)
- Advanced custom OID polling
- SNMPv3 support (`noAuthNoPriv`, `authNoPriv`, `authPriv`)

## Background
APC Rack Power was created to provide one practical integration for mixed APC installations where both UPS and Rack PDU devices are present.

The design goal is simple:
- Keep setup easy
- Read as much useful local data as possible
- Expose control points only where they actually exist
- Stay vendor-focused and reliable for APC SNMP implementations

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
1. Copy `custom_components/apc_rack_power` into your Home Assistant config folder.
2. Restart Home Assistant.
3. Add integration in `Settings -> Devices & Services -> Add Integration`.

## How It Works
- Polls APC devices via SNMP (`v2c` or `v3`)
- Reads RFC1628 and APC enterprise OIDs with fallback handling
- Detects whether the device behaves like UPS or PDU
- Filters entities by detected device kind
- Discovers controllable outlets/groups and creates switch entities dynamically
- Hides unavailable/sentinel values instead of showing noisy placeholders

## SNMP Security Modes
- `v2c`: read community + optional write community
- `v3 noAuthNoPriv`: username only
- `v3 authNoPriv`: username + auth protocol/passphrase
- `v3 authPriv`: username + auth + privacy protocol/passphrase

## Tested Hardware
- APC Smart-UPS SRT3000UXI-NCLI
- APC External Battery Pack XBP48RM1U2-LI (connected to SRT3000UXI-NCLI)
- APC Switched Rack PDU AP8959EU3

## Provided Services
- `apc_rack_power.set_oid`
- `apc_rack_power.control_action`

## Repository Layout
- `custom_components/apc_rack_power` - integration source
- `hacs.json` - HACS metadata
- `.github/workflows/hacs-validate.yml` - HACS validation workflow
- `.github/workflows/hassfest.yml` - Home Assistant hassfest checks
- `.github/workflows/ci.yml` - basic lint/compile checks

## Support
- Issues: https://github.com/42bios/apc-rack-power/issues
- Releases: https://github.com/42bios/apc-rack-power/releases

## License
MIT - see [LICENSE](LICENSE).

