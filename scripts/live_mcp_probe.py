#!/usr/bin/env python3
"""Read-only live probe used to capture current macro template wire data."""

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


async def call(
    session: ClientSession, name: str, arguments: dict | None = None
) -> dict:
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
                await call(session, "list_macro_templates_web")
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
