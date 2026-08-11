"""Hybrid Cronometer tools for operations not exposed by the mobile REST client.

The primary MCP remains backed by the mobile REST API. This module lazily uses
``cronometer-mcp`` (cphoskins, MIT) for confirmed web GWT-RPC operations that
are currently missing from the mobile client: recurring foods, macro writes,
fasting deletion/cancellation, and biometric writes.
"""

from __future__ import annotations

from datetime import date, timedelta

from . import server as core
from .biometric_ids import normalize_biometric_id, web_biometric_id

mcp = core.mcp
_web_client = None

_BIOMETRIC_METRIC_IDS = {
    "weight": 1,
    "heart_rate": 3,
    "blood_glucose": 6,
    "body_fat": 8,
}


def _get_web_client():
    global _web_client
    if _web_client is None:
        try:
            from cronometer_mcp.client import CronometerClient as WebCronometerClient
        except ImportError as exc:
            raise RuntimeError(
                "Hybrid Cronometer web backend is not installed. "
                "Install cronometer-mcp==2.0.3."
            ) from exc
        _web_client = WebCronometerClient()
    return _web_client


def _date(value: str | None) -> date:
    return date.fromisoformat(value) if value else core._get_client().today()


def _mobile_biometric_rows(day: date) -> list[dict]:
    diary = core._get_client().get_diary(day) or {}
    return [
        row
        for row in diary.get("diary") or []
        if isinstance(row, dict)
        and row.get("type") == "Biometric"
        and row.get("biometricId") not in (None, "")
    ]


def _find_recent_biometric(biometric_id: int | str) -> tuple[date, dict] | None:
    wanted = normalize_biometric_id(biometric_id)
    mobile = core._get_client()
    today = mobile.today()
    for offset in range(31):
        day = today - timedelta(days=offset)
        for row in _mobile_biometric_rows(day):
            if str(row.get("biometricId")) == wanted:
                return day, row
    return None


def _prepare_biometric(
    metric_type: str,
    value: float,
    unit: str | None,
) -> tuple[str, int, float, str]:
    metric = str(metric_type).strip().lower()
    if metric not in _BIOMETRIC_METRIC_IDS:
        raise ValueError(
            "metric_type must be one of: body_fat, blood_glucose, "
            "heart_rate, weight"
        )

    stored_value = float(value)
    if metric == "weight":
        chosen = (unit or "kg").strip().lower()
        if chosen in ("kg", "kilogram", "kilograms"):
            stored_value *= 2.2046226218
            stored_unit = "lbs"
        elif chosen in ("lb", "lbs", "pound", "pounds"):
            stored_unit = "lbs"
        else:
            raise ValueError("weight unit must be kg or lbs")
    elif metric == "blood_glucose":
        stored_unit = unit or "mg/dL"
    elif metric == "heart_rate":
        stored_unit = unit or "bpm"
    else:
        stored_unit = unit or "%"

    return metric, _BIOMETRIC_METRIC_IDS[metric], stored_value, stored_unit


def _cleanup_new_biometric_ids(ids: list[str]) -> None:
    web = _get_web_client()
    for biometric_id in ids:
        try:
            web.remove_biometric(web_biometric_id(biometric_id))
        except Exception:
            # This is only rollback after a failed verification. The caller
            # still reports the write as failed and includes the unexpected IDs.
            pass


def _add_biometric_verified(
    metric_type: str,
    value: float,
    day: date,
    unit: str | None = None,
) -> dict:
    metric, expected_metric_id, stored_value, stored_unit = _prepare_biometric(
        metric_type, value, unit
    )
    before_ids = {
        str(row.get("biometricId")) for row in _mobile_biometric_rows(day)
    }

    web = _get_web_client()
    wire_id = str(web.add_biometric(metric, stored_value, day) or "")
    transport_id = None
    if wire_id:
        try:
            transport_id = normalize_biometric_id(wire_id)
        except ValueError:
            transport_id = None

    candidates = [
        row
        for row in _mobile_biometric_rows(day)
        if str(row.get("biometricId")) not in before_ids
    ]
    matches = [
        row for row in candidates if row.get("metricId") == expected_metric_id
    ]

    if not matches:
        unexpected_ids = [str(row.get("biometricId")) for row in candidates]
        actual_metric_ids = sorted(
            {
                row.get("metricId")
                for row in candidates
                if row.get("metricId") is not None
            }
        )
        _cleanup_new_biometric_ids(unexpected_ids)
        raise RuntimeError(
            "addBiometric was not verified: expected metric_id "
            f"{expected_metric_id} ({metric}), got metric_ids={actual_metric_ids}; "
            f"unexpected_ids={unexpected_ids}. Any detected wrong write was rolled back."
        )

    chosen = None
    if transport_id:
        chosen = next(
            (
                row
                for row in matches
                if str(row.get("biometricId")) == transport_id
            ),
            None,
        )
    chosen = chosen or matches[0]
    biometric_id = str(chosen.get("biometricId"))

    return {
        "biometric_id": biometric_id,
        "transport_id": transport_id,
        "wire_id": wire_id or None,
        "metric_type": metric,
        "metric_id": expected_metric_id,
        "input_value": value,
        "input_unit": unit,
        "stored_value": round(stored_value, 4),
        "stored_unit": stored_unit,
        "date": str(day),
    }


def _remove_biometric_verified(biometric_id: int | str) -> dict:
    canonical_id = normalize_biometric_id(biometric_id)
    found = _find_recent_biometric(canonical_id)
    if found is None:
        raise ValueError(
            f"biometric_id {canonical_id!r} was not found in the recent mobile diary"
        )
    day, _row = found

    web = _get_web_client()
    wire_id = web_biometric_id(canonical_id)
    ok = web.remove_biometric(wire_id)
    if not ok:
        raise RuntimeError(f"removeMeasurement did not confirm biometric {canonical_id}")

    remaining = {
        str(row.get("biometricId")) for row in _mobile_biometric_rows(day)
    }
    if canonical_id in remaining:
        raise RuntimeError(
            "removeMeasurement returned success but the biometric still exists: "
            f"biometric_id={canonical_id}, wire_id={wire_id}"
        )
    return {
        "deleted": True,
        "biometric_id": canonical_id,
        "wire_id": wire_id,
        "date": str(day),
    }


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
def get_repeated_items() -> str:
    """List recurring Cronometer food entries using the web backend."""
    try:
        items = _get_web_client().get_repeated_items()
        return core._ok({"count": len(items), "items": items, "backend": "web-gwt"})
    except Exception as e:
        return core._err(e)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
def add_repeat_item(
    food_source_id: int,
    food_id: int,
    quantity: float,
    food_name: str,
    diary_group: int = 1,
    days_of_week: list[int] | None = None,
) -> str:
    """Create a recurring food entry.

    Args:
        food_source_id: Web Cronometer food source ID.
        food_id: Web Cronometer food ID.
        quantity: Number of default servings.
        food_name: Display name.
        diary_group: 1 breakfast, 2 lunch, 3 dinner, 4 snacks.
        days_of_week: 0=Sunday through 6=Saturday; defaults to every day.
    """
    try:
        days = days_of_week or list(range(7))
        if diary_group not in (1, 2, 3, 4):
            raise ValueError("diary_group must be 1, 2, 3, or 4")
        if not days or any(d not in range(7) for d in days):
            raise ValueError("days_of_week must contain values 0 through 6")
        ok = _get_web_client().add_repeat_item(
            food_source_id=food_source_id,
            food_id=food_id,
            quantity=quantity,
            food_name=food_name,
            diary_group=diary_group,
            days_of_week=days,
        )
        return core._ok({"created": bool(ok), "backend": "web-gwt"})
    except Exception as e:
        return core._err(e)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True, "openWorldHint": True})
def delete_repeat_item(repeat_item_id: int) -> str:
    """Delete a recurring food entry by repeat-item ID."""
    try:
        ok = _get_web_client().delete_repeat_item(repeat_item_id)
        return core._ok({"deleted": bool(ok), "repeat_item_id": repeat_item_id, "backend": "web-gwt"})
    except Exception as e:
        return core._err(e)


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
def list_macro_templates_web() -> str:
    """List saved macro templates via the web backend, including template IDs."""
    try:
        templates = _get_web_client().get_macro_target_templates()
        return core._ok({"count": len(templates), "templates": templates, "backend": "web-gwt"})
    except Exception as e:
        return core._err(e)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
def set_macro_targets(
    target_date: str,
    protein_g: float | None = None,
    fat_g: float | None = None,
    carbs_g: float | None = None,
    calories: float | None = None,
    template_name: str = "Custom Targets",
) -> str:
    """Update macro targets for a specific date, preserving omitted values."""
    try:
        day = _date(target_date)
        client = _get_web_client()
        current = client.get_daily_macro_targets(day)
        values = {
            "protein_g": protein_g if protein_g is not None else current.get("protein_g", 0.0),
            "fat_g": fat_g if fat_g is not None else current.get("fat_g", 0.0),
            "carbs_g": carbs_g if carbs_g is not None else current.get("carbs_g", 0.0),
            "calories": calories if calories is not None else current.get("calories", 0.0),
        }
        if any(float(v) < 0 for v in values.values()):
            raise ValueError("macro targets cannot be negative")
        ok = client.update_daily_targets(
            day=day, template_name=template_name, **values
        )
        return core._ok(
            {"updated": bool(ok), "date": str(day), "targets": values, "backend": "web-gwt"}
        )
    except Exception as e:
        return core._err(e)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
def create_macro_template(
    template_name: str,
    protein_g: float,
    fat_g: float,
    carbs_g: float,
    calories: float,
) -> str:
    """Create a saved macro target template and return its verified template ID."""
    try:
        if min(protein_g, fat_g, carbs_g, calories) < 0:
            raise ValueError("macro targets cannot be negative")
        template_id = _get_web_client().save_macro_target_template(
            template_name=template_name,
            protein_g=protein_g,
            fat_g=fat_g,
            carbs_g=carbs_g,
            calories=calories,
        )
        if not template_id:
            raise RuntimeError("macro template write did not return a verified template ID")
        return core._ok(
            {"template_id": template_id, "template_name": template_name, "backend": "web-gwt"}
        )
    except Exception as e:
        return core._err(e)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True, "openWorldHint": True})
def delete_macro_template(template_id: int) -> str:
    """Delete a saved macro target template by ID."""
    try:
        ok = _get_web_client().delete_macro_target_template(template_id)
        return core._ok({"deleted": bool(ok), "template_id": template_id, "backend": "web-gwt"})
    except Exception as e:
        return core._err(e)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
def set_weekly_macro_schedule(template_id: int, days_of_week: list[int]) -> str:
    """Assign a saved macro template to selected weekdays.

    days_of_week uses 0=Sunday through 6=Saturday.
    """
    try:
        days = sorted(set(days_of_week))
        if not days or any(d not in range(7) for d in days):
            raise ValueError("days_of_week must contain values 0 through 6")
        client = _get_web_client()
        updated = []
        for day in days:
            client.save_macro_schedule(day, template_id)
            updated.append(day)
        return core._ok(
            {"template_id": template_id, "days_of_week": updated, "backend": "web-gwt"}
        )
    except Exception as e:
        return core._err(e)


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
def get_recent_biometrics() -> str:
    """Get recent biometric entries with canonical decimal biometric IDs."""
    try:
        mobile = core._get_client()
        today = mobile.today()
        records: list[dict] = []
        for offset in range(31):
            day = today - timedelta(days=offset)
            for row in _mobile_biometric_rows(day):
                records.append(
                    {
                        "biometric_id": str(row.get("biometricId")),
                        "value": row.get("amount", row.get("value")),
                        "metric_id": row.get("metricId"),
                        "unit_id": row.get("unitId"),
                        "date": str(row.get("day") or day),
                    }
                )
        records.sort(
            key=lambda row: (str(row.get("date") or ""), row.get("biometric_id") or ""),
            reverse=True,
        )
        return core._ok(
            {"count": len(records), "biometrics": records, "backend": "mobile-diary"}
        )
    except Exception as e:
        return core._err(e)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
def add_biometric(
    metric_type: str,
    value: float,
    date: str | None = None,
    unit: str | None = None,
) -> str:
    """Log a biometric and verify its numeric ID and metric in the mobile diary.

    Supported metric_type values are weight, blood_glucose, heart_rate and
    body_fat. If Cronometer's web endpoint writes the wrong metric, the MCP
    rolls that new row back and reports an error instead of claiming success.
    """
    try:
        result = _add_biometric_verified(metric_type, value, _date(date), unit)
        return core._ok({**result, "backend": "web-gwt+mobile-verify"})
    except Exception as e:
        return core._err(e)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True, "openWorldHint": True})
def remove_biometric(biometric_id: str) -> str:
    """Remove a biometric by decimal ID (or its equivalent GWT wire token)."""
    try:
        result = _remove_biometric_verified(biometric_id)
        return core._ok({**result, "backend": "web-gwt+mobile-verify"})
    except Exception as e:
        return core._err(e)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True, "openWorldHint": True})
def delete_fast(fast_id: int) -> str:
    """Permanently delete a fasting entry by ID."""
    try:
        ok = _get_web_client().delete_fast(fast_id)
        return core._ok({"deleted": bool(ok), "fast_id": fast_id, "backend": "web-gwt"})
    except Exception as e:
        return core._err(e)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True, "openWorldHint": True})
def cancel_active_fast(fast_id: int) -> str:
    """Cancel an active fast while keeping its recurring series/schedule."""
    try:
        ok = _get_web_client().cancel_fast_keep_series(fast_id)
        return core._ok(
            {
                "cancelled": bool(ok),
                "fast_id": fast_id,
                "series_preserved": True,
                "backend": "web-gwt",
            }
        )
    except Exception as e:
        return core._err(e)
