"""Composite CRUD controls for Cronometer biometric measurements."""

from __future__ import annotations

import json

from . import hybrid_tools as hybrid
from . import server as core
from .biometric_ids import normalize_biometric_id

mcp = core.mcp


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

    Cronometer has no confirmed direct biometric-update call, so this operation
    is add-first/delete-second. Both the replacement metric/ID and final source
    deletion are verified against the mobile diary. A failed replacement leaves
    the original untouched. If replacement succeeds but deletion fails, the
    response is ``partial`` and includes the replacement numeric ID.
    """
    try:
        source_id = normalize_biometric_id(biometric_id)
        source_found = hybrid._find_recent_biometric(source_id)
        if source_found is None:
            raise ValueError(
                f"biometric_id {source_id!r} was not found in recent biometrics"
            )
        source_day, source = source_found
        target_date = hybrid._date(date)

        replacement = hybrid._add_biometric_verified(
            metric_type=metric_type,
            value=float(value),
            day=target_date,
            unit=unit,
        )

        try:
            deleted = hybrid._remove_biometric_verified(source_id)
        except Exception as exc:
            return json.dumps(
                {
                    "status": "partial",
                    "message": (
                        "Replacement biometric was verified, but deleting the "
                        "source failed. Both measurements may now exist."
                    ),
                    "source_biometric_id": source_id,
                    "source_date": str(source_day),
                    "source": source,
                    "replacement_biometric_id": replacement["biometric_id"],
                    "replacement": replacement,
                    "delete_error": f"{type(exc).__name__}: {exc}",
                    "backend": "web-gwt+mobile-verify",
                },
                indent=2,
            )

        return core._ok(
            {
                "updated": True,
                "source_biometric_id": source_id,
                "source_date": str(source_day),
                "replacement_biometric_id": replacement["biometric_id"],
                "replacement": replacement,
                "delete": deleted,
                "backend": "web-gwt+mobile-verify",
            }
        )
    except Exception as e:
        return core._err(e)
