"""Shared APC device profiling helpers."""

from __future__ import annotations

from datetime import date
import re
from typing import Any

from .const import DEVICE_MIXED, DEVICE_PDU, DEVICE_UPS

_MODEL_RE = re.compile(r"\bMN:\s*([A-Za-z0-9_-]+)")
_DATE_RE = re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})\s*$")
_UNAVAILABLE_TEXT = {"", "unknown", "unbekannt", "not available", "not supported", "n/a"}

# sysObjectID prefixes of APC products (PowerNet-MIB "products" branch)
_OID_UPS = ("1.3.6.1.4.1.318.1.3.2.", "1.3.6.1.4.1.318.1.3.27")
_OID_PDU = ("1.3.6.1.4.1.318.1.3.4.", "1.3.6.1.4.1.318.1.3.32.")


def is_unavailable(value: Any) -> bool:
    """Return True for values that mean "not available"."""
    if value is None:
        return True
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return float(value) == -1
    return isinstance(value, str) and value.strip().lower() in _UNAVAILABLE_TEXT


def extract_model_number(metrics: dict[str, Any]) -> str | None:
    """Extract the network card model from sysDescr (e.g. MN:AP9641)."""
    sys_descr = metrics.get("sys_descr")
    if not isinstance(sys_descr, str):
        return None
    match = _MODEL_RE.search(sys_descr)
    return match.group(1).strip() if match else None


def detect_device_kind(metrics: dict[str, Any]) -> str:
    """Return the device class: pdu, ups or mixed."""
    has_pdu = not is_unavailable(metrics.get("pdu_model_number")) or not is_unavailable(
        metrics.get("pdu_device_num_outlets")
    )
    has_ups = any(
        not is_unavailable(metrics.get(key))
        for key in ("ups_ident_model", "ups_sku", "rfc_output_source", "apc_output_status")
    )
    if has_pdu and not has_ups:
        return DEVICE_PDU
    if has_ups and not has_pdu:
        return DEVICE_UPS
    object_id = str(metrics.get("sys_object_id") or "")
    if object_id.startswith(_OID_PDU):
        return DEVICE_PDU
    if object_id.startswith(_OID_UPS):
        return DEVICE_UPS
    desc = str(metrics.get("sys_descr") or "").lower()
    if "rack power distribution unit" in desc or "rpdu" in desc:
        return DEVICE_PDU
    if has_ups:
        return DEVICE_UPS
    return DEVICE_MIXED


def kind_matches(device_kind: str, kind: str | None) -> bool:
    """Whether something that belongs to `kind` applies to the device."""
    return kind is None or device_kind in (kind, DEVICE_MIXED)


def parse_flags(value: Any) -> str | None:
    """Return the 0/1 flag string of upsBasicStateOutputState, if valid."""
    if isinstance(value, str) and len(value) >= 30 and set(value) <= {"0", "1"}:
        return value
    return None


def flag(flags: str | None, position: int) -> bool | None:
    """Read one flag (1-based)."""
    if flags is None or len(flags) < position:
        return None
    return flags[position - 1] == "1"


def parse_apc_date(value: Any) -> date | None:
    """Parse APC dates in mm/dd/yy or mm/dd/yyyy format."""
    if not isinstance(value, str):
        return None
    match = _DATE_RE.match(value)
    if not match:
        return None
    month, day, year = (int(part) for part in match.groups())
    if year < 100:
        year += 2000
    try:
        return date(year, month, day)
    except ValueError:
        return None
