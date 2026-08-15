"""Temporary live probe for Cronometer RepeatItem serializer/deserializer."""

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
    """Temporary diagnostic: inspect the current RepeatItem GWT bundle code."""
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
            "function wuj",
            "function yuj",
            "function xuj",
            "function buj",
            "function cuj",
            "writeDouble",
            "addRepeatItem",
            "RepeatItem/477684891",
        ]
        found: dict[str, list[str]] = {}
        for term in terms:
            hits = [m.start() for m in re.finditer(re.escape(term), text)]
            if not hits:
                continue
            snippets: list[str] = []
            for pos in hits[:8]:
                start = max(0, pos - 1600)
                end = min(len(text), pos + len(term) + 2000)
                snippets.append(text[start:end])
            found[term] = snippets

        return repeat.core._ok(
            {
                "diagnostic": "temporary-repeat-live-bundle",
                "permutation": client.gwt_permutation,
                "cache_size": len(text),
                "terms_found": sorted(found),
                "matches": found,
            }
        )
    except Exception as exc:
        return repeat.core._err(exc)
