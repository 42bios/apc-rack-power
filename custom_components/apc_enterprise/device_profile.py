"""Shared APC device profiling helpers."""

from __future__ import annotations

import re
from typing import Any

DEVICE_PDU = "pdu"
DEVICE_UPS = "ups"
DEVICE_MIXED = "mixed"

_MODEL_RE = re.compile(r"\bMN:\s*([A-Za-z0-9_-]+)")


def is_unavailable(value: Any) -> bool:
    """Return True for sentinel values that mean not available."""
    if value is None:
        return True
    if isinstance(value, (int, float)) and float(value) == -1:
        return True
    if isinstance(value, str) and value.strip().lower() in {"unknown", "unbekannt", "not available"}:
        return True
    return False


def extract_model_number(metrics: dict[str, Any]) -> str | None:
    """Extract APC model number from sysDescr (e.g. MN:AP9641)."""
    sys_descr = metrics.get("sys_descr")
    if not isinstance(sys_descr, str):
        return None
    match = _MODEL_RE.search(sys_descr)
    if not match:
        return None
    value = match.group(1).strip()
    return value or None


def detect_device_kind(metrics: dict[str, Any]) -> str:
    """Return detected device class: pdu, ups or mixed."""
    desc = str(metrics.get("sys_descr") or "").lower()
    model = str(metrics.get("ups_ident_model") or "").lower()
    ups_score = 0
    pdu_score = 0

    if "rack power distribution unit" in desc or "rpdu" in desc or "ap89" in desc:
        return DEVICE_PDU
    if "smart-ups" in model or ("ups" in model and "rack power" not in model):
        return DEVICE_UPS

    pdu_outlets = metrics.get("pdu_device_num_outlets")
    if isinstance(pdu_outlets, (int, float)) and int(pdu_outlets) > 0:
        pdu_score += 2

    for key in ("ups_output_voltage", "ups_output_current", "ups_charge_remaining", "ups_ident_model", "ups_sku"):
        if not is_unavailable(metrics.get(key)):
            ups_score += 1
    for key in (
        "pdu_phase_voltage",
        "pdu_phase_current",
        "pdu_device_load_percent",
        "pdu_model_number",
    ):
        if not is_unavailable(metrics.get(key)):
            pdu_score += 1

    if pdu_score > ups_score:
        return DEVICE_PDU
    if ups_score > pdu_score:
        return DEVICE_UPS
    return DEVICE_MIXED


def table_matches_device(device_kind: str, table_key: str) -> bool:
    """Whether a control table belongs to the detected device kind."""
    if device_kind == DEVICE_PDU:
        return table_key in {"rpdu2_outlet", "spdu_outlet"}
    if device_kind == DEVICE_UPS:
        return table_key == "ups_outlet_group"
    return True

