"""Registration tests for the full Cronometer MCP entrypoint."""

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

HYBRID_TOOLS = {
    "get_repeated_items",
    "add_repeat_item",
    "delete_repeat_item",
    "update_repeat_item",
    "list_macro_templates_web",
    "set_macro_targets",
    "create_macro_template",
    "delete_macro_template",
    "set_weekly_macro_schedule",
    "get_recent_biometrics",
    "add_biometric",
    "remove_biometric",
    "update_biometric",
    "delete_fast",
    "cancel_active_fast",
}

EXPORT_TOOLS = {
    "export_raw_csv_web",
    "get_exercises_export",
    "get_notes_export",
    "get_biometrics_export",
}

CONTROL_TOOLS = {
    "add_food_entry_by_measure",
    "copy_food_entry",
    "move_food_entry",
    "copy_meal_between_dates",
    "clear_food_entries",
    "update_food_entry",
}


def test_full_server_registers_all_tools():
    from cronometer_api_mcp.server_all import mcp

    tools = asyncio.run(mcp.list_tools())
    names = {tool.name for tool in tools}

    assert EXTRA_TOOLS <= names
    assert HYBRID_TOOLS <= names
    assert EXPORT_TOOLS <= names
    assert CONTROL_TOOLS <= names
    assert len(names) == 51
    for tool in tools:
        assert tool.description, f"{tool.name} has no description"


def test_full_import_does_not_construct_clients():
    from cronometer_api_mcp import hybrid_tools, server
    import cronometer_api_mcp.server_all  # noqa: F401

    assert server._client is None
    assert hybrid_tools._web_client is None
