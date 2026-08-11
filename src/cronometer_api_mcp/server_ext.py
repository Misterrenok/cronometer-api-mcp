"""Extended MCP tools built on top of the stable mobile REST client.

This module imports the core server (which registers the original tools), then
registers additional safe/compositional tools on the same FastMCP instance.
Keeping the extension separate lets us grow functionality without destabilizing
the proven core server implementation.
"""

from __future__ import annotations

from datetime import timedelta

from . import server as core

mcp = core.mcp


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
def get_diary_raw(date: str | None = None) -> str:
    """Get the complete raw Cronometer diary response for one date.

    Unlike get_food_log, this intentionally preserves all fields returned by
    Cronometer. Use it when compact diary output hides a field needed for
    debugging, exercises, biometrics, notes, ordering, or future API work.

    Args:
        date: Date as YYYY-MM-DD (defaults to today).
    """
    try:
        client = core._get_client()
        day = core._parse_date(date)
        data = client.get_diary(day)
        return core._ok({"date": date or str(client.today()), "diary": data})
    except Exception as e:
        return core._err(e)


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
def get_food_details_batch(food_ids: list[int]) -> str:
    """Get full details for multiple Cronometer foods in one API call.

    Returns each food's complete measures, default measure, source, category,
    and raw nutrient profile. This is the efficient way to resolve all foods
    from a diary without calling get_food_details repeatedly.

    Args:
        food_ids: Cronometer food IDs. Maximum 100 IDs per request.
    """
    try:
        if not food_ids:
            return core._ok({"count": 0, "foods": []})
        if len(food_ids) > 100:
            raise ValueError("food_ids is capped at 100 items per request")
        client = core._get_client()
        foods = client.get_foods(list(dict.fromkeys(food_ids)))
        return core._ok({"count": len(foods), "foods": foods})
    except Exception as e:
        return core._err(e)


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
def get_nutrient_catalog() -> str:
    """List Cronometer nutrient IDs with names, units, and categories.

    Useful for interpreting the raw nutrient arrays returned by food details
    and for seeing which numeric nutrient ID corresponds to each nutrient.
    """
    try:
        client = core._get_client()
        definitions = client.get_nutrient_definitions()
        nutrients = [
            {"id": nutrient_id, **metadata}
            for nutrient_id, metadata in sorted(definitions.items())
        ]
        return core._ok({"count": len(nutrients), "nutrients": nutrients})
    except Exception as e:
        return core._err(e)


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
def get_daily_nutrition_range(
    start_date: str,
    end_date: str,
    max_days: int = 31,
) -> str:
    """Get consumed macro/micronutrient totals for a date range.

    Calls the same server-computed nutrition logic as get_daily_nutrition for
    each day, preserving tracked nutrient IDs, names, units and confidence.

    Args:
        start_date: First date as YYYY-MM-DD.
        end_date: Last date as YYYY-MM-DD, inclusive.
        max_days: Safety cap for response size, default 31 and maximum 90.
    """
    try:
        client = core._get_client()
        start = core._parse_date(start_date)
        end = core._parse_date(end_date)
        if start is None or end is None:
            raise ValueError("start_date and end_date are required")
        if end < start:
            raise ValueError("end_date must be on or after start_date")
        max_days = max(1, min(max_days, 90))
        total_days = (end - start).days + 1
        if total_days > max_days:
            raise ValueError(
                f"Requested {total_days} days; max_days is {max_days}. "
                "Increase max_days up to 90 or use a smaller range."
            )

        days = []
        cursor = start
        while cursor <= end:
            data = client.get_consumed_nutrients(cursor)
            days.append(
                {
                    "date": str(cursor),
                    "summary": data["macros"],
                    "nutrients": data["nutrients"],
                }
            )
            cursor += timedelta(days=1)
        return core._ok(
            {
                "start_date": start_date,
                "end_date": end_date,
                "count": len(days),
                "days": days,
            }
        )
    except Exception as e:
        return core._err(e)


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
def get_food_log_range(
    start_date: str,
    end_date: str,
    max_days: int = 31,
) -> str:
    """Get compact enriched food logs for multiple dates.

    Each day contains resolved food names, food/measure IDs, grams, servings,
    serving measure metadata, meal group and entry IDs suitable for deletion.

    Args:
        start_date: First date as YYYY-MM-DD.
        end_date: Last date as YYYY-MM-DD, inclusive.
        max_days: Safety cap, default 31 and maximum 90.
    """
    try:
        client = core._get_client()
        start = core._parse_date(start_date)
        end = core._parse_date(end_date)
        if start is None or end is None:
            raise ValueError("start_date and end_date are required")
        if end < start:
            raise ValueError("end_date must be on or after start_date")
        max_days = max(1, min(max_days, 90))
        total_days = (end - start).days + 1
        if total_days > max_days:
            raise ValueError(
                f"Requested {total_days} days; max_days is {max_days}. "
                "Increase max_days up to 90 or use a smaller range."
            )

        days = []
        cursor = start
        while cursor <= end:
            raw = client.get_diary(cursor)
            enriched = client.enrich_diary_servings(raw, include_nutrients=False)
            entries = core._compact_diary_entries(enriched)
            days.append(
                {"date": str(cursor), "count": len(entries), "entries": entries}
            )
            cursor += timedelta(days=1)
        return core._ok(
            {
                "start_date": start_date,
                "end_date": end_date,
                "count": len(days),
                "days": days,
            }
        )
    except Exception as e:
        return core._err(e)


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
def get_macro_schedules() -> str:
    """Get the raw weekly macro schedule response from Cronometer."""
    try:
        client = core._get_client()
        return core._ok({"schedules": client.get_macro_schedules()})
    except Exception as e:
        return core._err(e)


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
def list_macro_templates() -> str:
    """Get the raw saved macro target templates from Cronometer."""
    try:
        client = core._get_client()
        return core._ok({"templates": client.get_macro_target_templates()})
    except Exception as e:
        return core._err(e)


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    }
)
def copy_day_between_dates(source_date: str, destination_date: str) -> str:
    """Copy all diary entries from an explicit source date to destination date.

    This is additive and does not remove entries already present on the
    destination date.

    Args:
        source_date: Source as YYYY-MM-DD.
        destination_date: Destination as YYYY-MM-DD.
    """
    try:
        client = core._get_client()
        source = core._parse_date(source_date)
        destination = core._parse_date(destination_date)
        if source is None or destination is None:
            raise ValueError("source_date and destination_date are required")
        result = client.copy_day(from_day=source, to_day=destination)
        return core._ok(
            {
                "source_date": source_date,
                "destination_date": destination_date,
                "result": result,
            }
        )
    except Exception as e:
        return core._err(e)


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
def get_account_info() -> str:
    """Get MCP-relevant Cronometer account/session metadata.

    Returns the authenticated user ID, resolved account timezone, and today's
    date in that timezone. It never returns the password or session token.
    """
    try:
        client = core._get_client()
        return core._ok(
            {
                "user_id": client.user_id,
                "timezone": str(client._tzinfo().key),
                "today": str(client.today()),
            }
        )
    except Exception as e:
        return core._err(e)


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
def search_foods_with_details(query: str, limit: int = 5) -> str:
    """Search foods and immediately resolve full measure/nutrient details.

    This combines search_foods and get_food_details for the best matches so an
    assistant can see the exact measure IDs, gram weights and nutrient profile
    before logging anything.

    Args:
        query: Food name or search phrase.
        limit: Number of top matches to resolve, default 5 and maximum 10.
    """
    try:
        client = core._get_client()
        limit = max(1, min(limit, 10))
        matches = client.search_food(query)[:limit]
        ids = [f.get("id") for f in matches if isinstance(f.get("id"), int)]
        details = client.get_foods(ids)
        details_by_id = {f.get("id"): f for f in details if isinstance(f, dict)}
        results = []
        for match in matches:
            food_id = match.get("id")
            results.append(
                {
                    "search": {
                        "food_id": food_id,
                        "name": match.get("name"),
                        "source": match.get("source"),
                        "measure_id": match.get("measureId"),
                        "translation_id": match.get("translationId"),
                        "measure_display": match.get("measureDisplayName"),
                        "score": match.get("score"),
                    },
                    "details": details_by_id.get(food_id),
                }
            )
        return core._ok({"query": query, "count": len(results), "foods": results})
    except Exception as e:
        return core._err(e)


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
def get_macro_targets_range(
    start_date: str,
    end_date: str,
    max_days: int = 31,
) -> str:
    """Get effective daily macro targets across a date range.

    Uses each day's diary summary, which reflects the target Cronometer actually
    applies that day even when schedule/template endpoints are empty.

    Args:
        start_date: First date as YYYY-MM-DD.
        end_date: Last date as YYYY-MM-DD, inclusive.
        max_days: Safety cap, default 31 and maximum 90.
    """
    try:
        client = core._get_client()
        start = core._parse_date(start_date)
        end = core._parse_date(end_date)
        if start is None or end is None:
            raise ValueError("start_date and end_date are required")
        if end < start:
            raise ValueError("end_date must be on or after start_date")
        max_days = max(1, min(max_days, 90))
        total_days = (end - start).days + 1
        if total_days > max_days:
            raise ValueError(
                f"Requested {total_days} days; max_days is {max_days}. "
                "Increase max_days up to 90 or use a smaller range."
            )

        days = []
        cursor = start
        while cursor <= end:
            diary = client.get_diary(cursor)
            summary = (diary or {}).get("summary") or {}
            days.append(
                {
                    "date": str(cursor),
                    "targets": core._normalise_daily_macro_targets(summary),
                }
            )
            cursor += timedelta(days=1)
        return core._ok(
            {
                "start_date": start_date,
                "end_date": end_date,
                "count": len(days),
                "days": days,
            }
        )
    except Exception as e:
        return core._err(e)


def main() -> None:
    """Run the extended server over the same Streamable HTTP transport."""
    core.main()
