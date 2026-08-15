"""Correct RepeatItem response-list parsing and request field order.

Current RepeatItem fields are quantity, weekdays, optional Integer diary group,
food name, enabled, repeat-item id, food id, measure id, optional Time.  The
web service canonicalizes the four built-in diary groups to internal IDs
-3..-6 (Breakfast..Snacks).  The parser also accepts legacy/default rows where
the group field was null/zero.
"""

from __future__ import annotations

import json

from . import repeat_v2_tools as repeat
from . import repeat_v3_patch as _repeat_v3_patch  # noqa: F401
from . import repeat_v5_patch as _repeat_v5_patch  # noqa: F401


repeat._GWT_ADD = (
    "7|0|11|https://cronometer.com/cronometer/|"
    "{gwt_header}|com.cronometer.shared.rpc.CronometerService|"
    "addRepeatItem|java.lang.String/2004016611|"
    "I|com.cronometer.shared.repeatitems.RepeatItem/477684891|{nonce}|"
    "java.util.ArrayList/4159755760|java.lang.Integer/3438268394|"
    "{food_name}|1|2|3|4|3|5|6|7|8|{user_id}|7|{quantity}|"
    "9|{day_count}|{day_entries}|10|{diary_group_raw}|11|1|0|"
    "{food_id}|{measure_id}|0|"
)

_INTERNAL_GROUPS = {-3: 1, -4: 2, -5: 3, -6: 4}


def _public_group(raw_group: int, has_integer_type: bool) -> int | None:
    """Convert Cronometer's wire/internal group value to public 1..4."""
    if raw_group in _INTERNAL_GROUPS:
        return _INTERNAL_GROUPS[raw_group]
    # Older rows produced by the previous patch used null for the group.  A
    # bare zero therefore means Breakfast/default.  For non-null Integer rows
    # accept 0..3 too, which is useful if Cronometer stops canonicalizing IDs.
    if raw_group in range(4):
        return raw_group + 1
    return None


def _extract_string_table(raw: str) -> tuple[list[str], int] | None:
    suffix = "],0,7]"
    table_end = raw.rfind(suffix)
    if table_end < 0:
        return None

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
        return None

    try:
        table = json.loads(raw[table_start : table_end + 1])
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(table, list) or not all(isinstance(v, str) for v in table):
        return None
    return table, table_start


def _parse(raw: str) -> list[dict]:
    """Parse getRepeatedItems using type references as structural anchors."""
    if not raw.startswith("//OK["):
        return []
    extracted = _extract_string_table(raw)
    if extracted is None:
        return []
    strings, table_start = extracted

    if not any("RepeatItem/" in value for value in strings):
        return []

    array_ref = next(
        (
            index + 1
            for index, value in enumerate(strings)
            if value.startswith("java.util.ArrayList/")
        ),
        None,
    )
    integer_ref = next(
        (
            index + 1
            for index, value in enumerate(strings)
            if value.startswith("java.lang.Integer/")
        ),
        None,
    )
    if array_ref is None or integer_ref is None:
        return []

    names = {
        index + 1: value
        for index, value in enumerate(strings)
        if not value.startswith("java.") and not value.startswith("com.cronometer.")
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
    for name_pos, name_ref in enumerate(tokens):
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

        group_pos = name_pos + 1
        if group_pos >= len(tokens):
            continue
        raw_group = tokens[group_pos]
        if not isinstance(raw_group, int):
            continue

        has_integer_type = (
            group_pos + 1 < len(tokens) and tokens[group_pos + 1] == integer_ref
        )
        diary_group = _public_group(raw_group, has_integer_type)
        if diary_group is None:
            continue

        # A non-null java.lang.Integer is returned as ``value, type_ref``.
        # Rows created by older code may contain null here, represented only
        # by ``0``. Support both shapes while locating the weekday payload.
        possible_pair_starts = {group_pos + 1}
        if has_integer_type:
            possible_pair_starts.add(group_pos + 2)

        quantity_pos = None
        days: list[int] | None = None
        for qpos in range(group_pos + 5, min(len(tokens), group_pos + 22)):
            quantity = tokens[qpos]
            if not isinstance(quantity, (int, float)) or qpos < 2:
                continue
            if tokens[qpos - 1] != array_ref:
                continue
            count = tokens[qpos - 2]
            if not isinstance(count, int) or count not in range(1, 8):
                continue
            pair_start = qpos - 2 - (2 * count)
            if pair_start not in possible_pair_starts:
                continue
            pairs = tokens[pair_start : qpos - 2]
            parsed_days: list[int] = []
            valid = True
            for offset in range(0, len(pairs), 2):
                day = pairs[offset]
                type_ref = pairs[offset + 1]
                if not (
                    isinstance(day, int) and day in range(7) and type_ref == integer_ref
                ):
                    valid = False
                    break
                parsed_days.append(day)
            if valid:
                quantity_pos = qpos
                days = sorted(set(parsed_days))
                break

        if quantity_pos is None or days is None:
            continue

        items.append(
            {
                "repeat_item_id": int(repeat_id),
                "food_id": int(food_id),
                "measure_id": int(measure_id),
                "food_name": names[name_ref],
                "quantity": float(tokens[quantity_pos]),
                "diary_group": diary_group,
                "days_of_week": days,
            }
        )

    return items


repeat._parse = _parse
mcp = repeat.mcp
