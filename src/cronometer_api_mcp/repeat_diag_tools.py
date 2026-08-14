"""Temporary read-only diagnostic for an unparseable legacy repeat item."""

from __future__ import annotations

from . import repeat_v2_tools as repeat
from . import server as core

mcp = core.mcp

repeat._replace_tool("get_repeated_items")


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
def get_repeated_items() -> str:
    """List recurring foods; include raw GWT only when a legacy row is unparseable."""
    try:
        raw = repeat._rpc(repeat._GWT_GET)
        items = repeat._parse(raw)
        payload = {
            "count": len(items),
            "items": items,
            "backend": "web-gwt-verified",
        }
        if "RepeatItem/" in raw and not items:
            payload["diagnostic_raw"] = raw
            payload["diagnostic"] = "repeat data present but parser returned no items"
        return core._ok(payload)
    except Exception as exc:
        return core._err(exc)
