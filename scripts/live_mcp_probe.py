#!/usr/bin/env python3
"""Small live probe for the Railway MCP deployment.

Only performs temporary writes and always tries to clean them up.
Intended for explicit [live-probe] commits in CI.
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

URLS = [
    u.strip()
    for u in os.getenv(
        "CRONOMETER_MCP_URLS",
        "https://cronometer-api-mcp-production-e87b.up.railway.app/mcp,"
        "https://cronometer-api-mcp-production.up.railway.app/mcp",
    ).split(",")
    if u.strip()
]


def text_payload(result: Any) -> dict:
    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        if isinstance(text, str):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"raw": text}
    return {"raw": repr(result)}


async def call(session: ClientSession, name: str, arguments: dict | None = None) -> dict:
    result = await session.call_tool(name, arguments or {})
    payload = text_payload(result)
    print(f"TOOL {name}: {json.dumps(payload, ensure_ascii=False, sort_keys=True)}")
    return payload


async def probe(url: str) -> bool:
    print(f"=== PROBE {url} ===")
    try:
        async with streamablehttp_client(url) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                tools = await session.list_tools()
                print(f"TOOLS {len(tools.tools)}")
                account = await call(session, "get_account_info")
                if account.get("status") != "success":
                    return False
                today = account["today"]

                # Read macro state without changing it.
                await call(session, "get_macro_targets", {"date": today})
                await call(session, "list_macro_templates_web")

                # Temporary weight write solely to capture the exact current mobile diary row.
                added = await call(
                    session,
                    "add_biometric",
                    {"metric_type": "weight", "value": 68.321, "date": today, "unit": "kg"},
                )
                bid = added.get("biometric_id") if added.get("status") == "success" else None
                try:
                    diary = await call(session, "get_diary_raw", {"date": today})
                    rows = [
                        row
                        for row in (diary.get("diary") or {}).get("diary", [])
                        if isinstance(row, dict) and row.get("type") == "Biometric"
                    ]
                    print("BIOMETRIC_ROWS " + json.dumps(rows, ensure_ascii=False, sort_keys=True))
                finally:
                    if bid:
                        await call(session, "remove_biometric", {"biometric_id": str(bid)})
                return True
    except Exception as exc:
        print(f"PROBE_ERROR {type(exc).__name__}: {exc}")
        return False


async def main() -> int:
    ok = False
    for url in URLS:
        ok = await probe(url) or ok
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
