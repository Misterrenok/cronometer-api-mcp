"""Temporary live probe for Cronometer RepeatItem field types and UI usage."""

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
    """Temporary diagnostic: inspect current RepeatItem field/UI type usage."""
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
            "function wuj",
            "function yuj",
            "Diary Group",
            "DiaryGroup",
            "diaryGroup",
            "Meal Group",
            "mealGroup",
            "Breakfast",
            "Lunch",
            "Dinner",
            "Snacks",
            "Include time",
            "Repeat Items",
            "repeatItem",
            "RepeatItem",
            "com.cronometer.shared.entries.models.Time",
            "com.cronometer.shared.entries.models.Diary",
        ]
        found: dict[str, list[str]] = {}
        for term in terms:
            hits = [m.start() for m in re.finditer(re.escape(term), text)]
            if not hits:
                continue
            snippets: list[str] = []
            for pos in hits[:20]:
                start = max(0, pos - 3500)
                end = min(len(text), pos + len(term) + 4500)
                snippets.append(text[start:end])
            found[term] = snippets

        return repeat.core._ok(
            {
                "diagnostic": "temporary-repeat-ui-field-types",
                "permutation": client.gwt_permutation,
                "cache_size": len(text),
                "terms_found": sorted(found),
                "matches": found,
            }
        )
    except Exception as exc:
        return repeat.core._err(exc)
