# APC Rack Power

[![CI](https://github.com/42bios/apc-rack-power/actions/workflows/ci.yml/badge.svg)](https://github.com/42bios/apc-rack-power/actions/workflows/ci.yml)
[![HACS](https://github.com/42bios/apc-rack-power/actions/workflows/hacs-validate.yml/badge.svg)](https://github.com/42bios/apc-rack-power/actions/workflows/hacs-validate.yml)
[![Hassfest](https://github.com/42bios/apc-rack-power/actions/workflows/hassfest.yml/badge.svg)](https://github.com/42bios/apc-rack-power/actions/workflows/hassfest.yml)
![HACS Custom](https://img.shields.io/badge/HACS-Custom-blue)
[![Release](https://img.shields.io/github/v/release/42bios/apc-rack-power?color=blue)](https://github.com/42bios/apc-rack-power/releases)
[![buy me a coffee – donate](https://img.shields.io/badge/buy%20me%20a%20coffee-donate-yellow?style=flat)](https://buymeacoffee.com/42bios)

Home Assistant custom integration for APC UPS and Rack PDU devices via SNMP (v1/v2c/v3).

<img src="https://raw.githubusercontent.com/42bios/apc-rack-power/main/custom_components/apc_rack_power/brand/logo.png" alt="APC Rack Power Logo" width="160">

[![Open in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=42bios&repository=apc-rack-power&category=integration)

> **Disclaimer:** This is an unofficial, community-maintained integration and is not affiliated with, endorsed by, or supported by APC or Schneider Electric. All product names, logos, and brands are property of their respective owners and are used for identification purposes only.

## Highlights
- One integration for APC UPS and Rack PDU devices with a Network Management Card (NMC)
- Automatic detection of the device type; only entities the device actually supports are created
- **UPS:** battery, runtime, input/output, output power (W/VA), energy counter (kWh) for the Energy dashboard, last transfer cause, battery install/replacement dates, external battery packs, self test and runtime calibration results
- **UPS binary sensors:** on battery, low battery, replace battery, overload, bypass, alarm, self test running
- **UPS controls:** start self test, start/cancel runtime calibration, flash and beep, alarm beeper mode, outlet groups on/off/reboot
- **Rack PDU:** power, apparent power, energy, load and load state, phases and banks with their warning/overload thresholds, per-outlet metering on metered-by-outlet models
- **PDU controls:** outlets on/off and reboot (off and on again with the delay configured on the PDU)
- **Temperature/humidity probes** (AP9335T/TH and similar) on rPDU2 sensor ports, NMC2/NMC3 universal I/O ports and older environmental monitors
- **SNMP traps (optional):** the card reports events immediately; Home Assistant polls at once and fires an `apc_rack_power_trap` event
- **Setup:** DHCP discovery of APC cards, reconfigure (address, SNMP version, credentials), re-authentication, repair issues (battery replacement, rejected commands, trap port)
- SNMPv1, SNMPv2c and SNMPv3 (MD5, SHA-1, SHA-224/256/384/512; DES, 3DES, AES-128/192/256)
- Custom OID polling for anything not covered

## Background
APC Rack Power was created to provide one practical integration for mixed APC installations where both UPS and Rack PDU devices are present.

The design goal is simple:
- Keep setup easy
- Read as much useful local data as possible
- Expose control points only where they actually exist
- Stay vendor-focused and reliable for APC SNMP implementations

## HACS Installation (Recommended)

1. Open HACS in Home Assistant.
2. Go to `Integrations`.
3. Open menu (three dots) -> `Custom repositories`.
4. Repository URL: `https://github.com/42bios/apc-rack-power`
5. Category: `Integration`
6. Install `APC Rack Power` and restart Home Assistant.
7. Add integration in `Settings -> Devices & Services -> Add Integration`.

Requires Home Assistant 2025.7 or newer.

## Manual Installation
1. Copy `custom_components/apc_rack_power` into your Home Assistant config folder.
2. Restart Home Assistant.
3. Add integration in `Settings -> Devices & Services -> Add Integration`.

## Setup
1. Enable SNMP on the network card (`Configuration -> Network -> SNMPv3` or `SNMPv1`) and allow the Home Assistant host in the card's access control list.
2. Add the integration, enter the address and choose the SNMP version.
3. Enter the credentials:
   - **SNMPv3 (recommended):** user name, authentication and privacy protocol with their passphrases. They must match the user configured on the card.
   - **SNMPv1/v2c:** read community and, for switching and tests, a write community.

APC cards that request an address via DHCP are discovered automatically and show up under `Settings -> Devices & Services`.

### Why SNMPv3?
SNMPv1 and SNMPv2c send the community string and all values in plain text. Anyone on the network who sees one request knows the community, and the write community allows switching outlets off. SNMPv3 with `authPriv` authenticates every request and encrypts the traffic. Most APC cards (including the AP9641 tested here) offer only SHA (SHA-1) or MD5 and AES (AES-128) or DES: choose SHA and AES. Use the SHA-2 and AES-192/256 options only if your card lists them.

For AES-192/256 two key formats exist. The default entries use the Blumenthal format (net-snmp). If the card rejects them, try the "Cisco/Reeder" variants.

You can move an existing entry to SNMPv3 at any time via `Reconfigure`.

### SNMP traps (optional)
1. In the integration options enable `Receive SNMP traps` and keep port 162, or choose a port above 1024 if Home Assistant cannot open port 162.
2. On the card, add Home Assistant as trap receiver (`Configuration -> Notification -> SNMP Traps -> Trap Receivers`) with the same port and community (SNMPv1 or v2c traps).
3. Each trap triggers an immediate update and an `apc_rack_power_trap` event with the trap OID and its values, which you can use in automations.

## Supported Devices
The integration reads the standard UPS-MIB (RFC 1628) and the APC PowerNet-MIB and creates entities for what the device answers:

| Device family | Tables used |
|---|---|
| Smart-UPS / Symmetra with NMC2 or NMC3 (AP9630/31/40/41 ...) | UPS-MIB, `upsBasic`/`upsAdv`/`upsHighPrec`, outlet groups, universal I/O probes |
| Switched/metered Rack PDU, current firmware (AP79xx, AP86xx, AP88xx, AP89xx) | `rPDU2` device, phases, banks, switched and metered outlets, sensor port |
| Rack PDU with older firmware | `rPDU` load and outlets, MasterSwitch `sPDU` outlets |
| Older environmental monitors | integrated environmental monitor (`iem`), modular sensors (`mem`) |

### Tested Hardware
- APC Smart-UPS SRT3000UXI-NCLI with AP9641 (two temperature probes)
- APC External Battery Pack XBP48RM1U2-LI (connected to SRT3000UXI-NCLI)
- APC Switched Rack PDU AP8959EU3

Other models are covered by the same MIB tables but not tested yet. Diagnostics downloads (credentials and serial numbers are redacted) help to add support for them.

## Provided Services
- `apc_rack_power.set_oid`: write an integer to any writable OID
- `apc_rack_power.control_action`: switch an outlet or outlet group on/off or reboot it

## Upgrading from 0.3.x
- Credentials move from the options into the entry automatically; change them via `Reconfigure`.
- Battery status, output source and self test result are now text states (for example `normal`, `battery`, `passed`) instead of numbers. Update automations or templates that compared the numbers.
- PDU values that were wrong before are fixed: outlet states, phase current and power, PDU load.
- The options "PDU nominal watts" and "Temperature scale" are gone: power is read from the PDU, and temperatures are reported in °C and converted by Home Assistant.

## Repository Layout
- `custom_components/apc_rack_power` - integration source
- `tests` - pytest suite with anonymised SNMP walks of the tested devices
- `hacs.json` - HACS metadata
- `.github/workflows/hacs-validate.yml` - HACS validation workflow
- `.github/workflows/hassfest.yml` - Home Assistant hassfest checks
- `.github/workflows/ci.yml` - lint and tests

## Support

If you find this project useful, you can [buy me a coffee](https://buymeacoffee.com/42bios) to support development and testing.

- Issues: https://github.com/42bios/apc-rack-power/issues
- Releases: https://github.com/42bios/apc-rack-power/releases

## License
MIT - see [LICENSE](LICENSE).

