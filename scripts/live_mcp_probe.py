#!/usr/bin/env python3
"""Safe one-shot production sweep for every exposed Cronometer MCP tool."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

URL = os.getenv(
    "CRONOMETER_MCP_URL",
    "https://cronometer-api-mcp-production-e87b.up.railway.app/mcp",
).strip()

EXPECTED_TOOLS = {
    "get_food_log",
    "add_food_entry",
    "remove_food_entry",
    "mark_day_complete",
    "copy_day",
    "get_daily_nutrition",
    "get_nutrition_scores",
    "search_foods",
    "get_food_details",
    "add_custom_food",
    "get_macro_targets",
    "get_fasting_history",
    "get_fasting_stats",
    "list_biometrics",
    "get_biometrics",
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
    "get_repeated_items",
    "add_repeat_item",
    "delete_repeat_item",
    "list_macro_templates_web",
    "set_macro_targets",
    "create_macro_template",
    "delete_macro_template",
    "set_weekly_macro_schedule",
    "get_recent_biometrics",
    "add_biometric",
    "remove_biometric",
    "delete_fast",
    "cancel_active_fast",
    "update_biometric",
    "add_food_entry_by_measure",
    "copy_food_entry",
    "move_food_entry",
    "copy_meal_between_dates",
    "clear_food_entries",
    "update_food_entry",
    "update_repeat_item",
    "export_raw_csv_web",
    "get_exercises_export",
    "get_notes_export",
    "get_biometrics_export",
}

TEST_DATES = [f"2099-12-{day:02d}" for day in range(20, 26)]
D1, D2, D3, D4, D5, D6 = TEST_DATES
FAKE_ID = 2_147_483_647


def payload_from_result(result: Any) -> dict:
    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        if isinstance(text, str):
            try:
                value = json.loads(text)
                return value if isinstance(value, dict) else {"value": value}
            except json.JSONDecodeError:
                return {"raw": text}
    return {"raw": repr(result)}


def compact(value: Any, limit: int = 900) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return text if len(text) <= limit else text[:limit] + "…"


def first_food(payload: dict) -> dict | None:
    foods = payload.get("foods")
    if not isinstance(foods, list):
        return None
    return next(
        (
            item
            for item in foods
            if isinstance(item, dict)
            and isinstance(item.get("food_id"), int)
            and item.get("food_id", 0) > 0
        ),
        None,
    )


def usable_measure(payload: dict) -> int | None:
    measures = payload.get("measures")
    if isinstance(measures, list):
        for item in measures:
            if (
                isinstance(item, dict)
                and isinstance(item.get("measure_id"), int)
                and item.get("measure_id", 0) > 0
                and isinstance(item.get("grams"), (int, float))
                and item.get("grams", 0) > 0
            ):
                return item["measure_id"]
    value = payload.get("default_measure_id")
    return value if isinstance(value, int) and value > 0 else None


def food_entry_id(payload: dict, *, meal: str | None = None) -> str | None:
    entries = payload.get("entries")
    if not isinstance(entries, list):
        return None
    for item in entries:
        if not isinstance(item, dict) or item.get("type") != "Serving":
            continue
        if meal is not None and item.get("meal") != meal:
            continue
        value = item.get("entry_id")
        if value is not None:
            return str(value)
    return None


class Sweep:
    def __init__(self, session: ClientSession) -> None:
        self.session = session
        self.results: list[dict[str, Any]] = []
        self.invoked: set[str] = set()
        self.biometric_cleanup: set[str] = set()

    async def call(
        self,
        name: str,
        args: dict | None = None,
        *,
        expectation: str = "success",
        note: str = "",
    ) -> dict:
        self.invoked.add(name)
        payload: dict = {}
        is_error = False
        exception: str | None = None
        try:
            result = await self.session.call_tool(name, args or {})
            is_error = bool(getattr(result, "isError", False))
            payload = payload_from_result(result)
        except Exception as exc:  # MCP input validation can raise client-side.
            exception = f"{type(exc).__name__}: {exc}"
            is_error = True
            payload = {"exception": exception}

        status = payload.get("status")
        if expectation == "success":
            passed = not is_error and status == "success"
            label = "PASS" if passed else "FAIL"
        elif expectation == "error":
            passed = is_error or status == "error"
            label = "EXPECTED" if passed else "FAIL"
        elif expectation == "responsive":
            passed = exception is None
            label = "PASS/NOOP" if passed else "FAIL"
        else:
            raise ValueError(f"unknown expectation {expectation}")

        row = {
            "tool": name,
            "result": label,
            "status": status,
            "is_error": is_error,
            "note": note,
        }
        if exception:
            row["exception"] = exception
        self.results.append(row)
        print(f"{label:10} {name:30} {note} :: {compact(payload)}")
        return payload

    async def cleanup_food_dates(self) -> None:
        for day in TEST_DATES:
            try:
                await self.call(
                    "clear_food_entries",
                    {"date": day, "diary_group": "all"},
                    expectation="responsive",
                    note=f"cleanup {day}",
                )
            except Exception as exc:
                print(f"CLEANUP_FOOD_ERROR {day}: {exc}")

    async def cleanup_biometrics(self) -> None:
        for biometric_id in list(self.biometric_cleanup):
            try:
                payload = await self.call(
                    "remove_biometric",
                    {"biometric_id": biometric_id},
                    expectation="responsive",
                    note="cleanup temporary biometric",
                )
                if payload.get("status") == "success":
                    self.biometric_cleanup.discard(biometric_id)
            except Exception as exc:
                print(f"CLEANUP_BIOMETRIC_ERROR {biometric_id}: {exc}")


async def run_sweep(session: ClientSession) -> int:
    sweep = Sweep(session)
    listed = await session.list_tools()
    tool_names = {tool.name for tool in listed.tools}
    print(f"TOOLS_LISTED {len(tool_names)}")
    print(f"MISSING_TOOLS {sorted(EXPECTED_TOOLS - tool_names)}")
    print(f"EXTRA_TOOLS {sorted(tool_names - EXPECTED_TOOLS)}")

    if tool_names != EXPECTED_TOOLS:
        print("FAIL tool registry does not match expected 51-tool surface")

    account = await sweep.call("get_account_info")
    today = (
        account.get("today") if isinstance(account.get("today"), str) else "2026-08-11"
    )

    # Read-only core and catalog surface.
    await sweep.call("get_food_log", {"date": today, "include_nutrition": False})
    await sweep.call("get_daily_nutrition", {"date": today})
    await sweep.call("get_nutrition_scores", {"date": today})
    search = await sweep.call("search_foods", {"query": "banana", "limit": 5})
    food = first_food(search)
    food_id = food.get("food_id") if food else None
    search_measure_id = food.get("measure_id") if food else None

    details: dict = {}
    if isinstance(food_id, int):
        details = await sweep.call("get_food_details", {"food_id": food_id})
        await sweep.call("get_food_details_batch", {"food_ids": [food_id]})
    else:
        await sweep.call(
            "get_food_details",
            {"food_id": FAKE_ID},
            expectation="responsive",
            note="search did not yield a usable food id",
        )
        await sweep.call(
            "get_food_details_batch",
            {"food_ids": [FAKE_ID]},
            expectation="responsive",
            note="search did not yield a usable food id",
        )

    await sweep.call("get_nutrient_catalog")
    await sweep.call("search_foods_with_details", {"query": "banana", "limit": 2})
    await sweep.call("get_diary_raw", {"date": today})
    await sweep.call(
        "get_daily_nutrition_range",
        {"start_date": today, "end_date": today, "max_days": 1},
    )
    await sweep.call(
        "get_food_log_range",
        {"start_date": today, "end_date": today, "max_days": 1},
    )

    # No delete-custom-food tool exists. Invoke it through MCP validation only;
    # this tests registration/schema without leaving permanent junk in the account.
    await sweep.call(
        "add_custom_food",
        {},
        expectation="error",
        note="validation-only: irreversible custom-food creation has no delete tool",
    )

    # Macros: same-value daily write is reversible by definition; saved templates
    # and scheduler are Gold-gated for this account and must fail cleanly.
    await sweep.call("get_macro_targets", {"date": today})
    await sweep.call("get_macro_schedules")
    await sweep.call("list_macro_templates")
    await sweep.call("list_macro_templates_web")
    await sweep.call(
        "get_macro_targets_range",
        {"start_date": today, "end_date": today, "max_days": 1},
    )
    await sweep.call(
        "set_macro_targets",
        {"target_date": today},
        note="same-value write; omitted macros are read and preserved",
    )
    await sweep.call(
        "create_macro_template",
        {
            "template_name": "MCP Gold Gate Probe 20260811",
            "protein_g": 100.0,
            "fat_g": 50.0,
            "carbs_g": 200.0,
            "calories": 1650.0,
        },
        expectation="error",
        note="expected: saved macro templates require Cronometer Gold",
    )
    await sweep.call(
        "delete_macro_template",
        {"template_id": FAKE_ID},
        expectation="responsive",
        note="safe nonexistent-id no-op",
    )
    await sweep.call(
        "set_weekly_macro_schedule",
        {"template_id": FAKE_ID, "days_of_week": []},
        expectation="error",
        note="safe validation path; scheduler is Gold-only",
    )

    # Fasting reads plus safe nonexistent-id destructive calls.
    await sweep.call("get_fasting_history", {"start_date": today, "end_date": today})
    await sweep.call("get_fasting_stats")
    await sweep.call(
        "delete_fast",
        {"fast_id": FAKE_ID},
        expectation="responsive",
        note="safe nonexistent-id no-op",
    )
    await sweep.call(
        "cancel_active_fast",
        {"fast_id": FAKE_ID},
        expectation="responsive",
        note="safe nonexistent-id no-op",
    )

    # Repeat items: read backend, then exercise safe validation/not-found paths.
    await sweep.call("get_repeated_items")
    await sweep.call(
        "add_repeat_item",
        {
            "food_source_id": 1,
            "food_id": 1,
            "quantity": 1.0,
            "food_name": "MCP Validation Probe",
            "diary_group": 99,
            "days_of_week": [1],
        },
        expectation="error",
        note="validation-only to avoid creating a recurring diary rule",
    )
    await sweep.call(
        "delete_repeat_item",
        {"repeat_item_id": FAKE_ID},
        expectation="responsive",
        note="safe nonexistent-id no-op",
    )
    await sweep.call(
        "update_repeat_item",
        {
            "repeat_item_id": FAKE_ID,
            "food_source_id": 1,
            "food_id": 1,
            "quantity": 1.0,
            "food_name": "MCP Not Found Probe",
            "diary_group": 1,
            "days_of_week": [1],
        },
        expectation="error",
        note="safe not-found path before any replacement is created",
    )

    # Biometrics: create -> update -> delete a temporary heart-rate measurement.
    await sweep.call("list_biometrics")
    await sweep.call(
        "get_biometrics",
        {
            "metric_id": 3,
            "unit_id": 5,
            "start_date": today,
            "end_date": today,
        },
    )
    await sweep.call("get_recent_biometrics")
    added = await sweep.call(
        "add_biometric",
        {"metric_type": "heart_rate", "value": 77.0, "date": today, "unit": "bpm"},
    )
    added_id = added.get("biometric_id")
    if added.get("status") == "success" and added_id is not None:
        sweep.biometric_cleanup.add(str(added_id))
        updated = await sweep.call(
            "update_biometric",
            {
                "biometric_id": str(added_id),
                "metric_type": "heart_rate",
                "value": 78.0,
                "date": today,
                "unit": "bpm",
            },
        )
        replacement_id = updated.get("replacement_biometric_id")
        if updated.get("status") == "success":
            sweep.biometric_cleanup.discard(str(added_id))
            if replacement_id is not None:
                sweep.biometric_cleanup.add(str(replacement_id))
                removed = await sweep.call(
                    "remove_biometric", {"biometric_id": str(replacement_id)}
                )
                if removed.get("status") == "success":
                    sweep.biometric_cleanup.discard(str(replacement_id))
        else:
            await sweep.call(
                "remove_biometric",
                {"biometric_id": str(added_id)},
                expectation="responsive",
                note="cleanup after update failure",
            )
            sweep.biometric_cleanup.discard(str(added_id))
    else:
        await sweep.call(
            "update_biometric",
            {
                "biometric_id": str(FAKE_ID),
                "metric_type": "heart_rate",
                "value": 78.0,
                "date": today,
                "unit": "bpm",
            },
            expectation="error",
            note="add failed; exercised safe not-found update path",
        )
        await sweep.call(
            "remove_biometric",
            {"biometric_id": str(FAKE_ID)},
            expectation="responsive",
            note="add failed; safe nonexistent-id remove",
        )

    # Food CRUD/composite operations use isolated future dates and are fully cleaned.
    measure_id = usable_measure(details)
    if measure_id is None and isinstance(search_measure_id, int):
        measure_id = search_measure_id

    try:
        if isinstance(food_id, int) and isinstance(measure_id, int):
            await sweep.call(
                "add_food_entry",
                {
                    "food_id": food_id,
                    "measure_id": measure_id,
                    "grams": 10.0,
                    "date": D1,
                    "diary_group": "breakfast",
                },
            )
            await sweep.call(
                "add_food_entry_by_measure",
                {
                    "food_id": food_id,
                    "measure_id": measure_id,
                    "quantity": 0.25,
                    "date": D1,
                    "diary_group": "lunch",
                },
            )
            d1_log = await sweep.call("get_food_log", {"date": D1})
            breakfast_id = food_entry_id(d1_log, meal="breakfast")

            if breakfast_id:
                await sweep.call(
                    "update_food_entry",
                    {
                        "entry_id": breakfast_id,
                        "source_date": D1,
                        "grams": 12.0,
                        "diary_group": "dinner",
                    },
                )
            else:
                await sweep.call(
                    "update_food_entry",
                    {
                        "entry_id": str(FAKE_ID),
                        "source_date": D1,
                        "grams": 12.0,
                    },
                    expectation="error",
                    note="setup entry missing",
                )

            d1_after = await sweep.call("get_food_log", {"date": D1})
            dinner_id = food_entry_id(d1_after, meal="dinner")
            lunch_id = food_entry_id(d1_after, meal="lunch")

            if dinner_id:
                await sweep.call(
                    "copy_food_entry",
                    {
                        "entry_id": dinner_id,
                        "source_date": D1,
                        "destination_date": D2,
                        "diary_group": "snacks",
                    },
                )
                d2_log = await sweep.call("get_food_log", {"date": D2})
                copied_id = food_entry_id(d2_log, meal="snacks")
                if copied_id:
                    await sweep.call(
                        "move_food_entry",
                        {
                            "entry_id": copied_id,
                            "source_date": D2,
                            "destination_date": D3,
                            "diary_group": "breakfast",
                        },
                    )
                else:
                    await sweep.call(
                        "move_food_entry",
                        {
                            "entry_id": str(FAKE_ID),
                            "source_date": D2,
                            "destination_date": D3,
                        },
                        expectation="error",
                        note="copy read-back missing",
                    )
            else:
                await sweep.call(
                    "copy_food_entry",
                    {
                        "entry_id": str(FAKE_ID),
                        "source_date": D1,
                        "destination_date": D2,
                    },
                    expectation="error",
                    note="updated entry missing",
                )
                await sweep.call(
                    "move_food_entry",
                    {
                        "entry_id": str(FAKE_ID),
                        "source_date": D2,
                        "destination_date": D3,
                    },
                    expectation="error",
                    note="copy setup missing",
                )

            await sweep.call(
                "copy_meal_between_dates",
                {"source_date": D1, "destination_date": D4, "diary_group": "lunch"},
            )
            await sweep.call(
                "copy_day_between_dates",
                {"source_date": D1, "destination_date": D5},
            )
            await sweep.call("copy_day", {"date": D6})
            await sweep.call("mark_day_complete", {"date": D6, "complete": True})
            await sweep.call("mark_day_complete", {"date": D6, "complete": False})
            await sweep.call("get_diary_raw", {"date": D6})
            await sweep.call(
                "get_food_log_range",
                {"start_date": D1, "end_date": D6, "max_days": 6},
            )
            await sweep.call(
                "get_daily_nutrition_range",
                {"start_date": D1, "end_date": D6, "max_days": 6},
            )

            if lunch_id:
                await sweep.call(
                    "remove_food_entry", {"entry_ids": [lunch_id], "date": D1}
                )
            else:
                await sweep.call(
                    "remove_food_entry",
                    {"entry_ids": [str(FAKE_ID)], "date": D1},
                    expectation="responsive",
                    note="setup lunch entry missing",
                )
            await sweep.call("clear_food_entries", {"date": D4, "diary_group": "all"})
        else:
            # Still invoke every write tool if food setup unexpectedly fails.
            print(
                "FOOD_SETUP_UNAVAILABLE: invoking dependent tools on safe not-found paths"
            )
            await sweep.call(
                "add_food_entry",
                {"food_id": FAKE_ID, "measure_id": FAKE_ID, "grams": 1.0, "date": D1},
                expectation="error",
            )
            await sweep.call(
                "add_food_entry_by_measure",
                {
                    "food_id": FAKE_ID,
                    "measure_id": FAKE_ID,
                    "quantity": 1.0,
                    "date": D1,
                },
                expectation="error",
            )
            for name, args in (
                ("update_food_entry", {"entry_id": str(FAKE_ID), "source_date": D1}),
                (
                    "copy_food_entry",
                    {
                        "entry_id": str(FAKE_ID),
                        "source_date": D1,
                        "destination_date": D2,
                    },
                ),
                (
                    "move_food_entry",
                    {
                        "entry_id": str(FAKE_ID),
                        "source_date": D1,
                        "destination_date": D2,
                    },
                ),
            ):
                await sweep.call(name, args, expectation="error")
            await sweep.call(
                "copy_meal_between_dates",
                {"source_date": D1, "destination_date": D4, "diary_group": "lunch"},
                expectation="responsive",
            )
            await sweep.call(
                "copy_day_between_dates",
                {"source_date": D1, "destination_date": D5},
                expectation="responsive",
            )
            await sweep.call("copy_day", {"date": D6}, expectation="responsive")
            await sweep.call(
                "mark_day_complete",
                {"date": D6, "complete": True},
                expectation="responsive",
            )
            await sweep.call(
                "mark_day_complete",
                {"date": D6, "complete": False},
                expectation="responsive",
            )
            await sweep.call(
                "remove_food_entry",
                {"entry_ids": [str(FAKE_ID)], "date": D1},
                expectation="responsive",
            )
            await sweep.call(
                "clear_food_entries",
                {"date": D4, "diary_group": "all"},
                expectation="responsive",
            )
    finally:
        await sweep.cleanup_food_dates()

    # Web CSV export surface, including UTF-8 path used by the original hotfix.
    await sweep.call(
        "export_raw_csv_web",
        {"export_type": "servings", "start_date": today, "end_date": today},
    )
    await sweep.call("get_exercises_export", {"start_date": today, "end_date": today})
    await sweep.call("get_notes_export", {"start_date": today, "end_date": today})
    await sweep.call("get_biometrics_export", {"start_date": today, "end_date": today})

    await sweep.cleanup_biometrics()

    missing_invocations = EXPECTED_TOOLS - sweep.invoked
    failures = [row for row in sweep.results if row["result"] == "FAIL"]
    print("=== SUMMARY ===")
    print(f"EXPECTED_TOOL_COUNT {len(EXPECTED_TOOLS)}")
    print(f"REGISTERED_TOOL_COUNT {len(tool_names)}")
    print(f"INVOKED_UNIQUE_COUNT {len(sweep.invoked)}")
    print(f"MISSING_INVOCATIONS {sorted(missing_invocations)}")
    print(f"FAILURE_COUNT {len(failures)}")
    for row in failures:
        print(f"FAILURE {compact(row)}")
    print(f"BIOMETRIC_CLEANUP_REMAINING {sorted(sweep.biometric_cleanup)}")

    registry_ok = tool_names == EXPECTED_TOOLS
    invoked_ok = not missing_invocations
    cleanup_ok = not sweep.biometric_cleanup
    return 0 if registry_ok and invoked_ok and not failures and cleanup_ok else 1


async def main() -> int:
    if not URL:
        print("No MCP URL configured")
        return 1
    print(f"=== FULL 51-TOOL SWEEP {URL} ===")
    async with streamablehttp_client(URL) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            return await run_sweep(session)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
