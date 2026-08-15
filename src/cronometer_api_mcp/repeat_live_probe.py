"""Temporary live probe for Cronometer DiaryGroup internals."""

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
    """Temporary diagnostic: inspect current DiaryGroup constructors/usages."""
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
            "function dHi",
            "new dHi",
            "function bHi",
            "bHi()",
            "aHi=",
            "aHi =",
            "DiaryGroup",
            "getDiaryGroup",
            "getDiaryGroups",
            "diaryGroups",
            "Uncategorized",
            "Group 6",
            "Group 7",
            "Group 8",
        ]
        found: dict[str, list[str]] = {}
        for term in terms:
            hits = [m.start() for m in re.finditer(re.escape(term), text)]
            if not hits:
                continue
            snippets: list[str] = []
            for pos in hits[:30]:
                start = max(0, pos - 5000)
                end = min(len(text), pos + len(term) + 6000)
                snippets.append(text[start:end])
            found[term] = snippets

        return repeat.core._ok(
            {
                "diagnostic": "temporary-diary-group-internals",
                "permutation": client.gwt_permutation,
                "terms_found": sorted(found),
                "matches": found,
            }
        )
    except Exception as exc:
        return repeat.core._err(exc)
