"""Correct recurring GWT field semantics after cross-checking mobile IDs.

A captured Wasa response is ``1055762,461776,658384``. The current mobile
search identifies 1055762 as the measure ID and 461776 as the food ID.
Therefore getRepeatedItems is measure_id, food_id, repeat_item_id, while
addRepeatItem serializes food_id before measure_id.
"""

from __future__ import annotations

import json

from . import repeat_v2_tools as repeat

repeat._GWT_ADD = (
    "7|0|11|https://cronometer.com/cronometer/|"
    "{gwt_header}|com.cronometer.shared.rpc.CronometerService|"
    "addRepeatItem|java.lang.String/2004016611|"
    "I|com.cronometer.shared.repeatitems.RepeatItem/477684891|{nonce}|"
    "java.util.ArrayList/4159755760|java.lang.Integer/3438268394|"
    "{food_name}|1|2|3|4|3|5|6|7|8|{user_id}|7|{diary_group}|"
    "9|{day_count}|{day_entries}|0|11|{quantity}|0|{food_id}|{measure_id}|0|"
)


def _parse_corrected(raw: str) -> list[dict]:
    """Parse RepeatItem records by their name-reference anchor.

    This handles valid positive IDs as well as legacy malformed rows whose
    repeat_item_id may be small or zero; the older parser only considered
    integers greater than 10000 and therefore lost such IDs.
    """
    if not raw.startswith("//OK["):
        return []

    suffix = "],0,7]"
    table_end = raw.rfind(suffix)
    if table_end < 0:
        return []

    depth = 0
    in_string = False
    escaped = False
    table_start = None
    for pos in range(table_end, -1, -1):
        ch = raw[pos]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "]":
            depth += 1
        elif ch == "[":
            depth -= 1
            if depth == 0:
                table_start = pos
                break
    if table_start is None:
        return []

    try:
        strings = json.loads(raw[table_start : table_end + 1])
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(strings, list):
        return []

    if not any(
        isinstance(value, str) and "RepeatItem/" in value for value in strings
    ):
        return []

    integer_ref = next(
        (
            index + 1
            for index, value in enumerate(strings)
            if isinstance(value, str) and value.startswith("java.lang.Integer/")
        ),
        None,
    )
    names = {
        index + 1: value
        for index, value in enumerate(strings)
        if isinstance(value, str)
        and not value.startswith("java.")
        and not value.startswith("com.cronometer.")
    }

    tokens: list[int | float | None] = []
    for part in raw[5:table_start].rstrip(",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            tokens.append(float(part) if "." in part else int(part))
        except ValueError:
            tokens.append(None)

    items: list[dict] = []
    used_name_positions: set[int] = set()
    for name_pos, name_ref in enumerate(tokens):
        if name_pos in used_name_positions:
            continue
        if not isinstance(name_ref, int) or name_ref not in names or name_pos < 4:
            continue

        measure_id = tokens[name_pos - 4]
        food_id = tokens[name_pos - 3]
        repeat_id = tokens[name_pos - 2]
        recurrence = tokens[name_pos - 1]
        if not (
            isinstance(measure_id, int)
            and measure_id > 0
            and isinstance(food_id, int)
            and food_id > 0
            and isinstance(repeat_id, int)
            and repeat_id >= 0
            and isinstance(recurrence, int)
            and recurrence in range(6)
        ):
            continue

        if name_pos + 3 >= len(tokens):
            continue
        raw_group = tokens[name_pos + 1]
        day_count = tokens[name_pos + 2]
        int_ref = tokens[name_pos + 3]
        if not (
            isinstance(raw_group, int)
            and raw_group in range(4)
            and isinstance(day_count, int)
            and day_count in range(1, 8)
            and integer_ref is not None
            and int_ref == integer_ref
        ):
            continue

        day_start = name_pos + 4
        days = tokens[day_start : day_start + day_count]
        if (
            len(days) != day_count
            or not all(isinstance(day, int) and day in range(7) for day in days)
        ):
            continue

        quantity_pos = day_start + day_count + 1
        if quantity_pos >= len(tokens):
            continue
        quantity = tokens[quantity_pos]
        if not isinstance(quantity, (int, float)):
            continue

        items.append(
            {
                "repeat_item_id": int(repeat_id),
                "food_id": int(food_id),
                "measure_id": int(measure_id),
                "food_name": names[name_ref],
                "quantity": float(quantity),
                "diary_group": raw_group + 1,
                "days_of_week": [int(day) for day in days],
            }
        )
        used_name_positions.add(name_pos)

    return items


repeat._parse = _parse_corrected

mcp = repeat.mcp

repeat._replace_tool("add_repeat_item")
repeat._replace_tool("update_repeat_item")


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    }
)
def add_repeat_item(
    food_id: int,
    quantity: float,
    food_name: str,
    food_source_id: int | None = None,
    diary_group: int = 1,
    days_of_week: list[int] | None = None,
    measure_id: int | None = None,
) -> str:
    """Create and verify a recurring food.

    Prefer ``measure_id`` from search_foods/get_food_details. ``food_source_id``
    is accepted only as a backward-compatible alias for measure_id so clients
    that cached the old broken schema continue to work.
    """
    resolved_measure = measure_id if measure_id is not None else food_source_id
    if resolved_measure is None:
        return repeat.core._err(
            ValueError("measure_id is required (legacy food_source_id is an alias)")
        )
    return repeat.add_repeat_item(
        food_id=food_id,
        measure_id=resolved_measure,
        quantity=quantity,
        food_name=food_name,
        diary_group=diary_group,
        days_of_week=days_of_week,
    )


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": True,
    }
)
def update_repeat_item(
    repeat_item_id: int,
    food_id: int,
    quantity: float,
    food_name: str,
    food_source_id: int | None = None,
    diary_group: int = 1,
    days_of_week: list[int] | None = None,
    measure_id: int | None = None,
) -> str:
    """Replace a recurring food using verified add-first/delete-second logic.

    Prefer ``measure_id``. ``food_source_id`` remains a compatibility alias for
    clients that cached the old schema.
    """
    resolved_measure = measure_id if measure_id is not None else food_source_id
    if resolved_measure is None:
        return repeat.core._err(
            ValueError("measure_id is required (legacy food_source_id is an alias)")
        )
    return repeat.update_repeat_item(
        repeat_item_id=repeat_item_id,
        food_id=food_id,
        measure_id=resolved_measure,
        quantity=quantity,
        food_name=food_name,
        diary_group=diary_group,
        days_of_week=days_of_week,
    )
