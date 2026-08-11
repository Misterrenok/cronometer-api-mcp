#!/usr/bin/env python3
"""Safe live probe for the Railway Cronometer MCP deployment.

Temporary writes are removed in finally blocks. The workflow runs only for
commits whose message contains [live-probe].
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


async def call(
    session: ClientSession, name: str, arguments: dict | None = None
) -> dict:
    result = await session.call_tool(name, arguments or {})
    payload = text_payload(result)
    print(f"TOOL {name}: {json.dumps(payload, ensure_ascii=False, sort_keys=True)}")
    return payload


async def temporary_biometric(
    session: ClientSession,
    *,
    metric_type: str,
    value: float,
    unit: str,
    day: str,
) -> bool:
    added = await call(
        session,
        "add_biometric",
        {"metric_type": metric_type, "value": value, "date": day, "unit": unit},
    )
    bid = added.get("biometric_id") if added.get("status") == "success" else None
    try:
        diary = await call(session, "get_diary_raw", {"date": day})
        rows = [
            row
            for row in (diary.get("diary") or {}).get("diary", [])
            if isinstance(row, dict) and row.get("type") == "Biometric"
        ]
        print(
            f"BIOMETRIC_ROWS {metric_type} "
            + json.dumps(rows, ensure_ascii=False, sort_keys=True)
        )
        return bool(bid)
    finally:
        if bid:
            await call(session, "remove_biometric", {"biometric_id": str(bid)})


async def temporary_macro_template(session: ClientSession) -> bool:
    name = "MCP Temporary Probe 2026-08-11"
    created = await call(
        session,
        "create_macro_template",
        {
            "template_name": name,
            "protein_g": 123.4,
            "fat_g": 67.8,
            "carbs_g": 234.5,
            "calories": 2042.0,
        },
    )
    template_id = (
        created.get("template_id") if created.get("status") == "success" else None
    )
    try:
        mobile = await call(session, "list_macro_templates")
        web = await call(session, "list_macro_templates_web")
        print("MACRO_MOBILE " + json.dumps(mobile, ensure_ascii=False, sort_keys=True))
        print("MACRO_WEB " + json.dumps(web, ensure_ascii=False, sort_keys=True))
        return bool(template_id)
    finally:
        if template_id:
            await call(session, "delete_macro_template", {"template_id": template_id})
            await call(session, "list_macro_templates")


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

                # Remove only the exact temporary record left by a prior aborted probe.
                recent = await call(session, "get_recent_biometrics")
                if any(
                    str(item.get("biometric_id")) == "1754710557"
                    for item in recent.get("biometrics", [])
                    if isinstance(item, dict)
                ):
                    await call(
                        session,
                        "remove_biometric",
                        {"biometric_id": "1754710557"},
                    )

                targets = await call(session, "get_macro_targets", {"date": today})
                daily = targets.get("daily_targets") or {}
                await call(
                    session,
                    "set_macro_targets",
                    {
                        "target_date": today,
                        "protein_g": daily.get("protein_g"),
                        "fat_g": daily.get("fat_g"),
                        "carbs_g": daily.get("carbs_g"),
                        "calories": daily.get("energy_kcal"),
                        "template_name": "Custom Targets",
                    },
                )

                results = [await temporary_macro_template(session)]

                # Restore the exact pre-probe daily targets even if a candidate
                # macro-template endpoint unexpectedly touched today's template.
                await call(
                    session,
                    "set_macro_targets",
                    {
                        "target_date": today,
                        "protein_g": daily.get("protein_g"),
                        "fat_g": daily.get("fat_g"),
                        "carbs_g": daily.get("carbs_g"),
                        "calories": daily.get("energy_kcal"),
                        "template_name": "Custom Targets",
                    },
                )

                results.append(
                    await temporary_biometric(
                        session,
                        metric_type="heart_rate",
                        value=77,
                        unit="bpm",
                        day=today,
                    )
                )
                results.append(
                    await temporary_biometric(
                        session,
                        metric_type="blood_glucose",
                        value=90,
                        unit="mg/dL",
                        day=today,
                    )
                )
                results.append(
                    await temporary_biometric(
                        session, metric_type="body_fat", value=12.3, unit="%", day=today
                    )
                )

                final_recent = await call(session, "get_recent_biometrics")
                print("TEMP_SUCCESS " + json.dumps(results))
                print("FINAL_RECENT_COUNT " + str(final_recent.get("count")))
                return all(results)
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
