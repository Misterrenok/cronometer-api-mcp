"""Composite Cronometer control tools built from confirmed diary APIs.

These tools do not invent new Cronometer endpoints. They compose the proven
mobile REST operations already used by the core server to make common diary
mutations safer and easier for MCP clients.
"""

from __future__ import annotations

import json
from datetime import date

from . import server as core

mcp = core.mcp

_MEAL_GROUPS = {
    "auto": 0,
    "breakfast": 1,
    "lunch": 2,
    "dinner": 3,
    "snacks": 4,
}


def _meal_group(value: str, *, allow_auto: bool = True) -> int:
    key = value.strip().lower()
    group = _MEAL_GROUPS.get(key)
    if group is None or (group == 0 and not allow_auto):
        allowed = "auto, breakfast, lunch, dinner, snacks" if allow_auto else (
            "breakfast, lunch, dinner, snacks"
        )
        raise ValueError(f"Invalid diary_group {value!r}. Must be one of: {allowed}.")
    return group


def _entry_meal_group(entry: dict) -> int:
    order = entry.get("order")
    if isinstance(order, int):
        group = order >> 16
        if group in (1, 2, 3, 4):
            return group
    return 0


def _find_serving(client, entry_id: str, day: date) -> dict:
    diary = client.get_diary(day)
    for entry in (diary or {}).get("diary", []):
        if (
            isinstance(entry, dict)
            and entry.get("type") == "Serving"
            and str(entry.get("servingId")) == str(entry_id)
        ):
            return entry
    raise ValueError(f"Food entry {entry_id!r} was not found on {day.isoformat()}.")


def _copy_serving(
    client,
    entry: dict,
    destination: date,
    diary_group: int,
) -> dict:
    food_id = entry.get("foodId")
    grams = entry.get("grams")
    if not isinstance(food_id, int):
        raise ValueError("Source diary entry is missing a numeric foodId.")
    if not isinstance(grams, (int, float)):
        raise ValueError("Source diary entry is missing a numeric grams value.")

    measure_id = entry.get("measureId")
    if measure_id is not None and not isinstance(measure_id, int):
        raise ValueError("Source diary entry has an invalid measureId.")

    translation_id = entry.get("translationId", 0)
    if not isinstance(translation_id, int):
        translation_id = 0

    return client.add_serving(
        food_id=food_id,
        measure_id=measure_id,
        grams=float(grams),
        translation_id=translation_id,
        day=destination,
        diary_group=diary_group,
    )


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    }
)
def add_food_entry_by_measure(
    food_id: int,
    measure_id: int,
    quantity: float,
    date: str | None = None,
    translation_id: int = 0,
    diary_group: str = "auto",
) -> str:
    """Log a food using a Cronometer serving measure instead of manual grams.

    This resolves the chosen measure from get_food_details and converts a
    human-sized quantity such as 2 eggs or 1.5 cups into the value expected by
    Cronometer. Weight/Atomic measures use quantity * grams_per_unit. Recipe
    measures use quantity directly because Cronometer stores their diary amount
    as a serving count.

    Args:
        food_id: Cronometer food ID.
        measure_id: Serving measure ID from get_food_details.
        quantity: Number of the selected serving units.
        date: Date as YYYY-MM-DD (defaults to today).
        translation_id: Translation ID from food search (usually 0).
        diary_group: auto, breakfast, lunch, dinner, or snacks.
    """
    try:
        if quantity <= 0:
            raise ValueError("quantity must be greater than zero")

        client = core._get_client()
        food = client.get_food(food_id)
        measures = [m for m in food.get("measures", []) if isinstance(m, dict)]
        measure = next((m for m in measures if m.get("id") == measure_id), None)
        if measure is None:
            available = [
                {"measure_id": m.get("id"), "name": m.get("name"), "value": m.get("value")}
                for m in measures
            ]
            raise ValueError(
                f"measure_id {measure_id} is not available for food_id {food_id}. "
                f"Available measures: {available}"
            )

        measure_type = measure.get("type")
        grams_per_unit = measure.get("value")
        if measure_type == "Recipe":
            api_amount = float(quantity)
        else:
            if not isinstance(grams_per_unit, (int, float)) or grams_per_unit <= 0:
                raise ValueError(
                    f"Measure {measure_id} has no usable gram weight: {grams_per_unit!r}"
                )
            api_amount = float(quantity) * float(grams_per_unit)

        result = client.add_serving(
            food_id=food_id,
            measure_id=measure_id,
            grams=api_amount,
            translation_id=translation_id,
            day=core._parse_date(date),
            diary_group=_meal_group(diary_group),
        )
        return core._ok(
            {
                "entry": result,
                "food_id": food_id,
                "food_name": food.get("name"),
                "measure": {
                    "measure_id": measure_id,
                    "name": measure.get("name"),
                    "type": measure_type,
                    "grams_per_unit": grams_per_unit,
                },
                "quantity": quantity,
                "api_amount": api_amount,
                "date": date or str(client.today()),
                "diary_group": diary_group.strip().lower(),
            }
        )
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
def copy_food_entry(
    entry_id: str,
    source_date: str,
    destination_date: str,
    diary_group: str = "preserve",
) -> str:
    """Copy one food entry to another date or meal slot.

    The source entry remains untouched. Food ID, measure ID, amount, and
    translation ID are preserved. Set diary_group to "preserve" to keep the
    source meal slot, or choose breakfast/lunch/dinner/snacks.

    Args:
        entry_id: Serving ID from get_food_log or get_diary_raw.
        source_date: Date containing the source entry, YYYY-MM-DD.
        destination_date: Date to copy the entry to, YYYY-MM-DD.
        diary_group: preserve, breakfast, lunch, dinner, or snacks.
    """
    try:
        source = core._parse_date(source_date)
        destination = core._parse_date(destination_date)
        if source is None or destination is None:
            raise ValueError("source_date and destination_date are required")

        client = core._get_client()
        entry = _find_serving(client, entry_id, source)
        if diary_group.strip().lower() == "preserve":
            group = _entry_meal_group(entry)
        else:
            group = _meal_group(diary_group, allow_auto=False)

        result = _copy_serving(client, entry, destination, group)
        return core._ok(
            {
                "source_entry_id": str(entry_id),
                "source_date": source_date,
                "destination_date": destination_date,
                "destination_meal_group": group,
                "entry": result,
            }
        )
    except Exception as e:
        return core._err(e)


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": True,
    }
)
def move_food_entry(
    entry_id: str,
    source_date: str,
    destination_date: str,
    diary_group: str = "preserve",
) -> str:
    """Move one food entry to another date or meal slot.

    Safety behavior is add-first, delete-second: the destination entry is
    created before the source is removed so a failed add cannot lose the food
    record. If deletion fails after a successful add, the response is marked
    partial and includes the newly created entry so the duplicate can be fixed.

    Args:
        entry_id: Serving ID from get_food_log or get_diary_raw.
        source_date: Date containing the source entry, YYYY-MM-DD.
        destination_date: Destination date, YYYY-MM-DD.
        diary_group: preserve, breakfast, lunch, dinner, or snacks.
    """
    try:
        source = core._parse_date(source_date)
        destination = core._parse_date(destination_date)
        if source is None or destination is None:
            raise ValueError("source_date and destination_date are required")

        client = core._get_client()
        entry = _find_serving(client, entry_id, source)
        source_group = _entry_meal_group(entry)
        if diary_group.strip().lower() == "preserve":
            destination_group = source_group
        else:
            destination_group = _meal_group(diary_group, allow_auto=False)

        if source == destination and source_group == destination_group:
            return core._ok(
                {
                    "moved": False,
                    "no_op": True,
                    "entry_id": str(entry_id),
                    "date": source_date,
                    "meal_group": source_group,
                }
            )

        created = _copy_serving(client, entry, destination, destination_group)
        removed = client.delete_entries([str(entry_id)], source)
        removed_ids = [str(value) for value in removed.get("removed", [])]
        if str(entry_id) not in removed_ids:
            return json.dumps(
                {
                    "status": "partial",
                    "message": (
                        "Destination entry was created, but the source entry "
                        "could not be removed. Both entries may now exist."
                    ),
                    "source_entry_id": str(entry_id),
                    "source_date": source_date,
                    "destination_date": destination_date,
                    "destination_entry": created,
                    "remove_result": removed,
                },
                indent=2,
            )

        return core._ok(
            {
                "moved": True,
                "source_entry_id": str(entry_id),
                "source_date": source_date,
                "destination_date": destination_date,
                "destination_meal_group": destination_group,
                "destination_entry": created,
            }
        )
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
def copy_meal_between_dates(
    source_date: str,
    destination_date: str,
    diary_group: str,
) -> str:
    """Copy one complete meal group from one day to another.

    Uses Cronometer's confirmed /api/v2/copy operation with diaryGroupNumber,
    so only Breakfast, Lunch, Dinner, or Snacks is copied. The operation is
    additive and does not remove entries already on the destination date.

    Args:
        source_date: Source date as YYYY-MM-DD.
        destination_date: Destination date as YYYY-MM-DD.
        diary_group: breakfast, lunch, dinner, or snacks.
    """
    try:
        source = core._parse_date(source_date)
        destination = core._parse_date(destination_date)
        if source is None or destination is None:
            raise ValueError("source_date and destination_date are required")
        if source == destination:
            raise ValueError("source_date and destination_date must be different")

        group = _meal_group(diary_group, allow_auto=False)
        client = core._get_client()
        result = client._request(
            "/api/v2/copy",
            {
                "from": client._format_day(source),
                "to": client._format_day(destination),
                "diaryGroupNumber": group,
                "config": {"call_version": 1},
            },
        )
        return core._ok(
            {
                "source_date": source_date,
                "destination_date": destination_date,
                "diary_group": diary_group.strip().lower(),
                "diary_group_number": group,
                "result": result,
            }
        )
    except Exception as e:
        return core._err(e)


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
def clear_food_entries(
    date: str,
    diary_group: str = "all",
) -> str:
    """Remove all food entries from a day, optionally limited to one meal.

    Non-food diary rows such as exercises, biometrics, and notes are never
    selected. Use diary_group="all" for every food serving, or choose one of
    breakfast/lunch/dinner/snacks.

    Args:
        date: Diary date as YYYY-MM-DD.
        diary_group: all, breakfast, lunch, dinner, or snacks.
    """
    try:
        day = core._parse_date(date)
        if day is None:
            raise ValueError("date is required")

        group_key = diary_group.strip().lower()
        group = None if group_key == "all" else _meal_group(
            diary_group, allow_auto=False
        )

        client = core._get_client()
        diary = client.get_diary(day)
        entry_ids: list[str] = []
        for entry in (diary or {}).get("diary", []):
            if not isinstance(entry, dict) or entry.get("type") != "Serving":
                continue
            if group is not None and _entry_meal_group(entry) != group:
                continue
            serving_id = entry.get("servingId")
            if serving_id is not None:
                entry_ids.append(str(serving_id))

        if not entry_ids:
            return core._ok(
                {
                    "date": date,
                    "diary_group": group_key,
                    "removed": [],
                    "count": 0,
                }
            )

        result = client.delete_entries(entry_ids, day)
        return core._ok(
            {
                "date": date,
                "diary_group": group_key,
                "removed": result.get("removed", []),
                "count": result.get("count", 0),
            }
        )
    except Exception as e:
        return core._err(e)
