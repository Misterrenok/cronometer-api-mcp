"""Registration tests for the extended Cronometer MCP entrypoint."""

from __future__ import annotations

import asyncio


EXTRA_TOOLS = {
    "get_diary_raw",
    "get_food_details_batch",
    "get_nutrient_catalog",
    "get_daily_nutrition_range",
    "get_food_log_range",
    "get_macro_schedules",
    "list_macro_templates",
    "copy_day_between_dates",
    "get_account_info",
    "search_foods_with_details",
    "get_macro_targets_range",
}


def test_extended_server_registers_full_tool_set():
    from cronometer_api_mcp.server_ext import mcp

    tools = asyncio.run(mcp.list_tools())
    names = {tool.name for tool in tools}

    assert EXTRA_TOOLS <= names
    assert len(names) == 26
    for tool in tools:
        assert tool.description, f"{tool.name} has no description"


def test_extended_import_does_not_construct_client():
    from cronometer_api_mcp import server
    import cronometer_api_mcp.server_ext  # noqa: F401

    assert server._client is None
