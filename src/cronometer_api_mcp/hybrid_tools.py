"""Hybrid Cronometer tools for operations not exposed by the mobile REST client.

The primary MCP remains backed by the mobile REST API.  This module lazily uses
``cronometer-mcp`` (cphoskins, MIT) for a small set of confirmed web GWT-RPC
operations that are currently missing from the mobile client: recurring foods,
macro writes, fasting deletion/cancellation, and biometric writes.

The dependency is imported only when one of these tools is called, so server
startup and all REST-backed tools remain independent of the web backend.
"""

from __future__ import annotations

from datetime import date

from . import server as core

mcp = core.mcp
_web_client = None


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
        ok = client.update_daily_targets(day=day, template_name=template_name, **values)
        return core._ok({"updated": bool(ok), "date": str(day), "targets": values, "backend": "web-gwt"})
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
    """Create a saved macro target template and return its template ID."""
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
        return core._ok({"template_id": template_id, "template_name": template_name, "backend": "web-gwt"})
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
        return core._ok({"template_id": template_id, "days_of_week": updated, "backend": "web-gwt"})
    except Exception as e:
        return core._err(e)


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
def get_recent_biometrics() -> str:
    """Get recent biometric entries including removable biometric IDs."""
    try:
        entries = _get_web_client().get_recent_biometrics()
        return core._ok({"count": len(entries), "biometrics": entries, "backend": "web-gwt"})
    except Exception as e:
        return core._err(e)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
def add_biometric(
    metric_type: str,
    value: float,
    date: str | None = None,
    unit: str | None = None,
) -> str:
    """Log weight, blood glucose, heart rate, or body fat.

    Supported metric_type values: weight, blood_glucose, heart_rate, body_fat.
    Weight may be supplied as kg or lbs; the web backend stores weight through
    its lbs payload, so kg is converted automatically. Other expected units are
    mg/dL, bpm, and percent respectively.
    """
    try:
        metric = metric_type.strip().lower()
        stored_value = float(value)
        stored_unit = unit
        if metric == "weight":
            chosen = (unit or "kg").strip().lower()
            if chosen in ("kg", "kilogram", "kilograms"):
                stored_value = stored_value * 2.2046226218
                stored_unit = "lbs"
            elif chosen in ("lb", "lbs", "pound", "pounds"):
                stored_unit = "lbs"
            else:
                raise ValueError("weight unit must be kg or lbs")
        biometric_id = _get_web_client().add_biometric(metric, stored_value, _date(date))
        return core._ok({
            "biometric_id": biometric_id,
            "metric_type": metric,
            "input_value": value,
            "input_unit": unit,
            "stored_value": round(stored_value, 4),
            "stored_unit": stored_unit,
            "date": str(_date(date)),
            "backend": "web-gwt",
        })
    except Exception as e:
        return core._err(e)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True, "openWorldHint": True})
def remove_biometric(biometric_id: str) -> str:
    """Remove a biometric measurement by its biometric ID."""
    try:
        ok = _get_web_client().remove_biometric(biometric_id)
        return core._ok({"deleted": bool(ok), "biometric_id": biometric_id, "backend": "web-gwt"})
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
        return core._ok({"cancelled": bool(ok), "fast_id": fast_id, "series_preserved": True, "backend": "web-gwt"})
    except Exception as e:
        return core._err(e)
