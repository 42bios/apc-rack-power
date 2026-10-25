# APC Rack Power (Home Assistant Custom Integration)

APC Rack Power integrates APC UPS and APC Rack PDU devices through the SNMP interface of their Network Management Card.

## What It Supports
- APC UPS devices with Network Management Card (NMC2/NMC3)
- APC Rack PDU devices (switched, metered, metered-by-outlet)
- Temperature/humidity probes on the card or PDU
- SNMPv1, SNMPv2c and SNMPv3 (SHA-2 and AES-256 where the card supports it)

## Key Capabilities
- UPS: battery, runtime, input/output, power, energy, transfer cause, battery dates, tests
- PDU: power, energy, load, phases/banks with thresholds, metered outlets
- Switching and rebooting of PDU outlets and UPS outlet groups
- Self test, runtime calibration, flash and beep, alarm beeper mode
- Optional SNMP trap receiver for immediate updates
- DHCP discovery, reconfigure, re-authentication, repair issues
- Custom OID polling

SNMPv3 with authentication and encryption is recommended. SNMPv1/v2c transmit the community string in plain text.

See the repository README for setup details: https://github.com/42bios/apc-rack-power
