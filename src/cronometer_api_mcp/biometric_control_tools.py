"""Composite CRUD controls for confirmed Cronometer biometric types."""

from __future__ import annotations

import json

from . import hybrid_tools as hybrid
from . import server as core

mcp = core.mcp

_SUPPORTED = {"weight", "blood_glucose", "heart_rate", "body_fat"}


def _prepare_value(metric_type: str, value: float, unit: str | None) -> tuple[float, str | None]:
    metric = metric_type.strip().lower()
    if metric not in _SUPPORTED:
        raise ValueError(
            f"metric_type must be one of: {', '.join(sorted(_SUPPORTED))}"
        )
    if value < 0:
        raise ValueError("value cannot be negative")

    stored_value = float(value)
    stored_unit = unit
    if metric == "weight":
        chosen = (unit or "kg").strip().lower()
        if chosen in ("kg", "kilogram", "kilograms"):
            stored_value *= 2.2046226218
            stored_unit = "lbs"
        elif chosen in ("lb", "lbs", "pound", "pounds"):
            stored_unit = "lbs"
        else:
            raise ValueError("weight unit must be kg or lbs")
    return stored_value, stored_unit


def _bio_id(entry: dict) -> str | None:
    value = entry.get("biometric_id")
    return value if isinstance(value, str) and value else None


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": True,
    }
)
def update_biometric(
    biometric_id: str,
    metric_type: str,
    value: float,
    date: str | None = None,
    unit: str | None = None,
) -> str:
    """Replace a recent biometric measurement with a corrected value/type/date.

    This tool is limited to the four biometric types already confirmed by the
    Cronometer web backend: weight, blood_glucose, heart_rate, and body_fat.
    Cronometer exposes recent-biometric read, add, and delete operations but no
    direct update call, so the edit is composed safely: verify the source ID,
    add the replacement first, re-read the list, then delete the source.

    A failed add leaves the original untouched. If deletion fails after the
    replacement is created, the response is marked ``partial`` and includes
    both the new ID/candidates and current biometric list so a duplicate is not
    hidden from the caller.

    Args:
        biometric_id: Existing ID from get_recent_biometrics.
        metric_type: weight, blood_glucose, heart_rate, or body_fat.
        value: Replacement value.
        date: Replacement date as YYYY-MM-DD; defaults to today.
        unit: For weight, kg or lbs. Other types use Cronometer's native unit.
    """
    try:
        source_id = biometric_id.strip()
        if not source_id:
            raise ValueError("biometric_id cannot be empty")

        metric = metric_type.strip().lower()
        stored_value, stored_unit = _prepare_value(metric, float(value), unit)
        target_date = hybrid._date(date)

        client = hybrid._get_web_client()
        before = client.get_recent_biometrics()
        source = next(
            (
                item
                for item in before
                if isinstance(item, dict) and _bio_id(item) == source_id
            ),
            None,
        )
        if source is None:
            raise ValueError(
                f"biometric_id {source_id!r} was not found in recent biometrics"
            )

        before_ids = {
            entry_id
            for item in before
            if isinstance(item, dict) and (entry_id := _bio_id(item)) is not None
        }

        replacement_id = client.add_biometric(metric, stored_value, target_date)
        after_add = client.get_recent_biometrics()
        replacement_candidates = [
            item
            for item in after_add
            if isinstance(item, dict)
            and (entry_id := _bio_id(item)) is not None
            and entry_id not in before_ids
        ]

        try:
            deleted = client.remove_biometric(source_id)
        except Exception as exc:
            current = client.get_recent_biometrics()
            return json.dumps(
                {
                    "status": "partial",
                    "message": (
                        "Replacement biometric was created, but deleting the source "
                        "raised an error. Both measurements may now exist."
                    ),
                    "source_biometric_id": source_id,
                    "source": source,
                    "replacement_biometric_id": replacement_id,
                    "replacement_candidates": replacement_candidates,
                    "current_biometrics": current,
                    "delete_error": f"{type(exc).__name__}: {exc}",
                    "backend": "web-gwt",
                },
                indent=2,
            )

        if not deleted:
            current = client.get_recent_biometrics()
            return json.dumps(
                {
                    "status": "partial",
                    "message": (
                        "Replacement biometric was created, but Cronometer did not "
                        "confirm deletion of the source. Both may now exist."
                    ),
                    "source_biometric_id": source_id,
                    "source": source,
                    "replacement_biometric_id": replacement_id,
                    "replacement_candidates": replacement_candidates,
                    "current_biometrics": current,
                    "backend": "web-gwt",
                },
                indent=2,
            )

        return core._ok(
            {
                "updated": True,
                "source_biometric_id": source_id,
                "replacement_biometric_id": replacement_id,
                "replacement_candidates": replacement_candidates,
                "metric_type": metric,
                "input_value": value,
                "input_unit": unit,
                "stored_value": round(stored_value, 4),
                "stored_unit": stored_unit,
                "date": str(target_date),
                "backend": "web-gwt",
            }
        )
    except Exception as e:
        return core._err(e)
