# APC Rack Power (Home Assistant Custom Integration)

APC Rack Power integrates APC UPS and APC Rack PDU devices through SNMP.

## What It Supports
- APC UPS devices with Network Management Card
- APC Rack PDU devices (switched/metered)
- Automatic device-type filtering (UPS entities on UPS, PDU entities on PDU)

## Key Capabilities
- UPS metrics (battery, runtime, input/output power data)
- PDU metrics (load %, watts, energy, phase voltage/current/power)
- PDU outlet switching
- UPS outlet-group switching (if provided by device)
- Custom OID polling

## Tested Hardware
- APC Smart-UPS SRT3000UXI-NCLI
- APC External Battery Pack XBP48RM1U2-LI (connected to SRT3000UXI-NCLI)
- APC Switched Rack PDU AP8959EU3

## Configuration
Required:
- Host/IP
- SNMP read community

Optional:
- SNMP write community (for control features)
- Scan interval / timeout / retries
- PDU nominal watts (for % -> W conversion)
- Temperature scale
- Custom OIDs (`key=oid` per line)

## Services
- `apc_rack_power.set_oid`
- `apc_rack_power.control_action`

## Notes
- Ensure SNMP is enabled on APC devices.
- For control actions, SNMP write access must be configured on the APC side.

