"""Second temporary source probe focused on compiled RepeatItem symbols."""

from __future__ import annotations

import re

from . import repeat_v2_tools as repeat

mcp = repeat.mcp
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
    """Temporary diagnostic: inspect compiled RepeatItem class functions."""
    try:
        from cronometer_mcp import client as web_module

        client = repeat._client()
        client._discover_gwt_hashes()
        url = web_module.GWT_CACHE_JS_URL.replace(
            "{permutation}", client.gwt_permutation
        )
        response = client.session.get(url)
        response.raise_for_status()
        text = response.text

        terms = [
            "function ouj",
            "function euj",
            "function puj",
            "function quj",
            "new ouj",
            "hXm",
            "qvo",
            "Repeat Item",
            "Repeat Items",
            "RepeatItemNotFound",
            "getRepeatedItems",
            "addRepeatItem",
            "deleteRepeatItem",
        ]
        found: dict[str, list[dict]] = {}
        for term in terms:
            hits = [m.start() for m in re.finditer(re.escape(term), text)]
            if not hits:
                continue
            entries = []
            for pos in hits[:12]:
                start = max(0, pos - 1800)
                end = min(len(text), pos + len(term) + 1800)
                entries.append({"position": pos, "snippet": text[start:end]})
            found[term] = entries

        return repeat.core._ok(
            {
                "diagnostic": "temporary-repeat-class-source",
                "permutation": client.gwt_permutation,
                "cache_size": len(text),
                "terms_found": sorted(found),
                "matches": found,
            }
        )
    except Exception as exc:
        return repeat.core._err(exc)
