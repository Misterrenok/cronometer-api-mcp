"""Runtime fixes that prefer Cronometer's mobile REST API for biometric writes.

The old web-GWT addBiometric payload is stale for several metric types and can
silently create Weight instead.  This module replaces the internal composite
writer with a mobile-REST implementation that accepts a write only after the
mobile diary shows the expected metric ID. Unexpected writes are rolled back.
"""
from __future__ import annotations

from datetime import date

from . import hybrid_tools as hybrid
from . import server as core

_ORIGINAL_ADD = hybrid._add_biometric_verified

_UNIT_IDS = {
    "heart_rate": {"bpm": 5},
    "blood_glucose": {"mmol/l": 8, "mg/dl": 9},
    "body_fat": {"%": 13, "percent": 13},
}


def _unit_id(metric: str, unit: str | None) -> int:
    if metric == "heart_rate":
        chosen = (unit or "bpm").strip().lower()
    elif metric == "blood_glucose":
        chosen = (unit or "mg/dL").strip().lower()
    elif metric == "body_fat":
        chosen = (unit or "%").strip().lower()
    else:
        raise ValueError(f"mobile biometric writer does not handle {metric!r}")
    try:
        return _UNIT_IDS[metric][chosen]
    except KeyError as exc:
        allowed = ", ".join(sorted(_UNIT_IDS[metric]))
        raise ValueError(f"{metric} unit must be one of: {allowed}") from exc


def _new_rows(day: date, before_ids: set[str]) -> list[dict]:
    return [
        row
        for row in hybrid._mobile_biometric_rows(day)
        if str(row.get("biometricId")) not in before_ids
    ]


def _rollback(rows: list[dict]) -> None:
    ids = [
        str(row.get("biometricId"))
        for row in rows
        if row.get("biometricId") not in (None, "")
    ]
    if ids:
        hybrid._cleanup_new_biometric_ids(ids)


def _try_mobile_add(
    metric: str,
    metric_id: int,
    stored_value: float,
    day: date,
    unit_id: int,
) -> tuple[dict | None, list[str]]:
    """Try conservative current/mobile payload shapes, verifying each attempt."""
    mobile = core._get_client()
    before_ids = {
        str(row.get("biometricId")) for row in hybrid._mobile_biometric_rows(day)
    }
    biometric = {
        "amount": float(stored_value),
        "biometricId": None,
        "day": mobile._format_day(day),
        "meta": {},
        "metricId": metric_id,
        "order": 65539,
        "samplesVersion": 0,
        "type": "Biometric",
        "unitId": unit_id,
        "userId": mobile.user_id,
    }

    attempts = [
        ("/api/v2/add_biometric", {"biometric": biometric, "config": {"call_version": 2}}),
        ("/api/v2/add_biometric", {"data": biometric, "config": {"call_version": 2}}),
        ("/api/v2/add_biometric", {**biometric, "config": {"call_version": 2}}),
        ("/api/v2/add_measurement", {"biometric": biometric, "config": {"call_version": 2}}),
    ]
    errors: list[str] = []

    for endpoint, payload in attempts:
        try:
            response = mobile._request(endpoint, payload)
        except Exception as exc:
            errors.append(f"{endpoint}: {type(exc).__name__}: {exc}")
            continue

        rows = _new_rows(day, before_ids)
        matches = [row for row in rows if row.get("metricId") == metric_id]
        if matches:
            chosen = matches[-1]
            extras = [row for row in rows if row is not chosen]
            _rollback(extras)
            return chosen, errors

        if rows:
            _rollback(rows)
        errors.append(
            f"{endpoint}: response={response!r}; no verified metric_id={metric_id} row"
        )

    return None, errors


def add_biometric_verified(
    metric_type: str,
    value: float,
    day: date,
    unit: str | None = None,
) -> dict:
    metric, expected_metric_id, stored_value, stored_unit = hybrid._prepare_biometric(
        metric_type, value, unit
    )

    # Weight's web path is already confirmed live and handles kg->lbs correctly.
    if metric == "weight":
        return _ORIGINAL_ADD(metric_type, value, day, unit)

    unit_id = _unit_id(metric, unit)
    row, errors = _try_mobile_add(metric, expected_metric_id, stored_value, day, unit_id)
    if row is None:
        raise RuntimeError(
            "No verified mobile biometric write path succeeded for "
            f"{metric}; attempts={errors}"
        )

    biometric_id = str(row.get("biometricId"))
    return {
        "biometric_id": biometric_id,
        "transport_id": biometric_id,
        "wire_id": None,
        "metric_type": metric,
        "metric_id": expected_metric_id,
        "input_value": value,
        "input_unit": unit,
        "stored_value": round(float(row.get("amount", stored_value)), 4),
        "stored_unit": stored_unit,
        "unit_id": row.get("unitId"),
        "date": str(day),
        "write_transport": "mobile-rest",
    }


# Registered MCP functions resolve this module-global helper at call time, so
# replacing it here fixes both add_biometric and update_biometric without
# re-registering tools or changing the public schema.
hybrid._add_biometric_verified = add_biometric_verified
