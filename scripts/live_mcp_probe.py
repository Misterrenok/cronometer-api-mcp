#!/usr/bin/env python3
"""One-shot live verification for saved macro-template create/read-back/delete."""

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

TEST_NAME = "MCP GWT Serializer Verify 20260811 v2"
TEST_MACROS = {
    "protein_g": 123.4,
    "fat_g": 67.8,
    "carbs_g": 234.5,
    "calories": 2042.0,
}


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


def templates(payload: dict) -> list[dict]:
    value = payload.get("templates", [])
    return [item for item in value if isinstance(item, dict)]


def template_name(item: dict) -> str:
    for key in ("name", "templateName", "template_name"):
        value = item.get(key)
        if isinstance(value, str):
            return value
    return ""


async def probe(url: str) -> bool:
    print(f"=== WRITE PROBE {url} ===")
    template_id: int | None = None
    try:
        async with streamablehttp_client(url) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                before = await call(session, "list_macro_templates_web")
                if before.get("status") != "success":
                    return False
                if any(template_name(item) == TEST_NAME for item in templates(before)):
                    print("REFUSING: test template name already exists")
                    return False

                created = await call(
                    session,
                    "create_macro_template",
                    {"template_name": TEST_NAME, **TEST_MACROS},
                )
                if created.get("status") != "success":
                    return False
                raw_id = created.get("template_id")
                if not isinstance(raw_id, int) or raw_id <= 0:
                    print(f"INVALID_TEMPLATE_ID {raw_id!r}")
                    return False
                template_id = raw_id

                after_create = await call(session, "list_macro_templates_web")
                if after_create.get("status") != "success":
                    return False
                if not any(
                    template_name(item) == TEST_NAME for item in templates(after_create)
                ):
                    print("READBACK_FAILED: saved template is absent from list")
                    return False

                deleted = await call(
                    session,
                    "delete_macro_template",
                    {"template_id": template_id},
                )
                if deleted.get("status") != "success" or not deleted.get("deleted"):
                    return False
                template_id = None

                after_delete = await call(session, "list_macro_templates_web")
                if after_delete.get("status") != "success":
                    return False
                if any(
                    template_name(item) == TEST_NAME for item in templates(after_delete)
                ):
                    print("DELETE_READBACK_FAILED: test template still exists")
                    return False

                print("LIVE_MACRO_TEMPLATE_OK")
                return True
    except Exception as exc:
        print(f"PROBE_ERROR {type(exc).__name__}: {exc}")
        return False
    finally:
        if template_id is not None:
            print(f"CLEANUP_REQUIRED template_id={template_id}")
            try:
                async with streamablehttp_client(url) as (
                    read_stream,
                    write_stream,
                    _,
                ):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        cleanup = await call(
                            session,
                            "delete_macro_template",
                            {"template_id": template_id},
                        )
                        print(f"CLEANUP_RESULT {cleanup!r}")
            except Exception as exc:
                print(f"CLEANUP_ERROR {type(exc).__name__}: {exc}")


async def main() -> int:
    if not URLS:
        print("No MCP URL configured")
        return 1
    return 0 if await probe(URLS[0]) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
