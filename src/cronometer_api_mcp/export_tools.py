"""Read-only export tools backed by the confirmed Cronometer web client."""

from __future__ import annotations

from datetime import date

from . import server as core
from .hybrid_tools import _get_web_client

mcp = core.mcp


def _parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _export(export_type: str, start_date: str | None, end_date: str | None) -> str:
    raw = _get_web_client().export_raw(
        export_type,
        _parse_date(start_date),
        _parse_date(end_date),
    )
    truncated = len(raw) > 50000
    return core._ok({
        "export_type": export_type,
        "start_date": start_date,
        "end_date": end_date,
        "truncated": truncated,
        "total_chars": len(raw),
        "data": raw[:50000] + ("\n... (truncated)" if truncated else ""),
        "backend": "web-gwt",
    })


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
def export_raw_csv_web(
    export_type: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> str:
    """Export raw Cronometer CSV data through the web backend.

    export_type must be one of: servings, daily_summary, exercises,
    biometrics, notes.
    """
    try:
        allowed = {"servings", "daily_summary", "exercises", "biometrics", "notes"}
        if export_type not in allowed:
            raise ValueError(f"export_type must be one of: {', '.join(sorted(allowed))}")
        return _export(export_type, start_date, end_date)
    except Exception as e:
        return core._err(e)


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
def get_exercises_export(start_date: str | None = None, end_date: str | None = None) -> str:
    """Export exercise rows for a date range as raw Cronometer CSV."""
    try:
        return _export("exercises", start_date, end_date)
    except Exception as e:
        return core._err(e)


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
def get_notes_export(start_date: str | None = None, end_date: str | None = None) -> str:
    """Export diary notes for a date range as raw Cronometer CSV."""
    try:
        return _export("notes", start_date, end_date)
    except Exception as e:
        return core._err(e)


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
def get_biometrics_export(start_date: str | None = None, end_date: str | None = None) -> str:
    """Export biometric rows for a date range as raw Cronometer CSV."""
    try:
        return _export("biometrics", start_date, end_date)
    except Exception as e:
        return core._err(e)
