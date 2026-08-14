"""Verified recurring-food tools using Cronometer's confirmed GWT layout.

The pinned third-party ``cronometer-mcp==2.0.3`` has two recurring-item bugs:
its addRepeatItem field order is shifted, and its response parser drops meal/day
metadata and can miss the repeat-item ID.  This module replaces only the four
public recurring tools after the legacy modules have registered.
"""

from __future__ import annotations

import json

from . import hybrid_tools as hybrid
from . import server as core

mcp = core.mcp

_GWT_GET = (
    "7|0|7|https://cronometer.com/cronometer/|"
    "{gwt_header}|com.cronometer.shared.rpc.CronometerService|"
    "getRepeatedItems|java.lang.String/2004016611|I|{nonce}|"
    "1|2|3|4|2|5|6|7|{user_id}|"
)

_GWT_ADD = (
    "7|0|11|https://cronometer.com/cronometer/|"
    "{gwt_header}|com.cronometer.shared.rpc.CronometerService|"
    "addRepeatItem|java.lang.String/2004016611|"
    "I|com.cronometer.shared.repeatitems.RepeatItem/477684891|{nonce}|"
    "java.util.ArrayList/4159755760|java.lang.Integer/3438268394|"
    "{food_name}|1|2|3|4|3|5|6|7|8|{user_id}|7|{diary_group}|"
    "9|{day_count}|{day_entries}|0|11|{quantity}|0|{measure_id}|{food_id}|0|"
)

_GWT_DELETE = (
    "7|0|7|https://cronometer.com/cronometer/|"
    "{gwt_header}|com.cronometer.shared.rpc.CronometerService|"
    "deleteRepeatItem|java.lang.String/2004016611|I|{nonce}|"
    "1|2|3|4|3|5|6|6|7|{user_id}|{repeat_item_id}|"
)


def _replace_tool(name: str) -> None:
    """Remove an earlier registration so the corrected schema can replace it."""
    remover = getattr(mcp, "remove_tool", None)
    if callable(remover):
        try:
            remover(name)
            return
        except Exception:
            pass
    manager = getattr(mcp, "_tool_manager", None)
    tools = getattr(manager, "_tools", None)
    if isinstance(tools, dict):
        tools.pop(name, None)


for _tool_name in (
    "get_repeated_items",
    "add_repeat_item",
    "delete_repeat_item",
    "update_repeat_item",
):
    _replace_tool(_tool_name)


def _client():
    client = hybrid._get_web_client()
    client.authenticate()
    if not client.user_id or not client.nonce:
        raise RuntimeError(
            "Cronometer web authentication did not provide user_id/nonce"
        )
    return client


def _rpc(template: str, **values: object) -> str:
    client = _client()
    body = (
        template.replace("{gwt_header}", client.gwt_header)
        .replace("{nonce}", client.nonce or "")
        .replace("{user_id}", client.user_id or "")
    )
    for key, value in values.items():
        body = body.replace("{" + key + "}", str(value))
    return client._gwt_post(body)


def _parse(raw: str) -> list[dict]:
    """Parse the confirmed getRepeatedItems response layout."""
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
    except json.JSONDecodeError, TypeError:
        return []
    if not isinstance(strings, list):
        return []

    repeat_ref = next(
        (
            index + 1
            for index, value in enumerate(strings)
            if isinstance(value, str) and "RepeatItem/" in value
        ),
        None,
    )
    if repeat_ref is None:
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

    quantities = [
        index for index, value in enumerate(tokens) if isinstance(value, float)
    ]
    large = [
        (index, value)
        for index, value in enumerate(tokens)
        if isinstance(value, int) and value > 10000
    ]
    food_names = list(names.values())
    items: list[dict] = []

    for item_index, quantity_pos in enumerate(quantities):
        triple = large[item_index * 3 : item_index * 3 + 3]
        if len(triple) < 3:
            continue
        (_, food_id), (_, measure_id), (repeat_pos, repeat_id) = triple

        food_name = food_names[item_index] if item_index < len(food_names) else ""
        diary_group = None
        days: list[int] = []
        tail = tokens[repeat_pos + 1 : quantity_pos]
        name_offset = next(
            (
                offset
                for offset, value in enumerate(tail)
                if isinstance(value, int) and value in names
            ),
            None,
        )
        if name_offset is not None:
            name_ref = tail[name_offset]
            food_name = names.get(name_ref, food_name)
            group_pos = name_offset + 1
            if group_pos < len(tail):
                raw_group = tail[group_pos]
                if isinstance(raw_group, int) and raw_group in range(4):
                    diary_group = raw_group + 1

            count_pos = group_pos + 1
            if count_pos + 1 < len(tail):
                count = tail[count_pos]
                type_ref = tail[count_pos + 1]
                if (
                    isinstance(count, int)
                    and count in range(1, 8)
                    and integer_ref is not None
                    and type_ref == integer_ref
                ):
                    candidate = tail[count_pos + 2 : count_pos + 2 + count]
                    if len(candidate) == count and all(
                        isinstance(day, int) and day in range(7) for day in candidate
                    ):
                        days = [int(day) for day in candidate]

        items.append(
            {
                "repeat_item_id": int(repeat_id),
                "food_id": int(food_id),
                "measure_id": int(measure_id),
                "food_name": food_name,
                "quantity": float(tokens[quantity_pos]),
                "diary_group": diary_group,
                "days_of_week": days,
            }
        )
    return items


def _list() -> list[dict]:
    raw = _rpc(_GWT_GET)
    if not raw.startswith("//OK"):
        raise RuntimeError(f"getRepeatedItems failed: {raw[:300]}")
    items = _parse(raw)
    if "RepeatItem/" in raw and not items:
        raise RuntimeError(
            "getRepeatedItems returned repeat data that could not be parsed"
        )
    return items


def _delete_transport(repeat_item_id: int) -> None:
    raw = _rpc(_GWT_DELETE, repeat_item_id=repeat_item_id)
    if not raw.startswith("//OK"):
        raise RuntimeError(f"deleteRepeatItem failed: {raw[:300]}")


def _delete(repeat_item_id: int) -> bool:
    if repeat_item_id <= 0:
        raise ValueError("repeat_item_id must be greater than zero")
    before = _list()
    if not any(item["repeat_item_id"] == repeat_item_id for item in before):
        return True
    _delete_transport(repeat_item_id)
    after = _list()
    if any(item["repeat_item_id"] == repeat_item_id for item in after):
        raise RuntimeError(
            f"deleteRepeatItem returned OK but repeat_item_id={repeat_item_id} still exists"
        )
    return True


def _add(
    food_id: int,
    measure_id: int,
    quantity: float,
    food_name: str,
    diary_group: int,
    days_of_week: list[int] | None,
) -> dict:
    if food_id <= 0 or measure_id <= 0:
        raise ValueError("food_id and measure_id must be greater than zero")
    if quantity <= 0:
        raise ValueError("quantity must be greater than zero")
    if diary_group not in (1, 2, 3, 4):
        raise ValueError("diary_group must be 1, 2, 3, or 4")

    name = food_name.strip()
    if not name:
        raise ValueError("food_name cannot be empty")
    if "|" in name or "\\" in name:
        raise ValueError("food_name contains unsupported GWT control characters")

    days = list(range(7)) if days_of_week is None else sorted(set(days_of_week))
    if not days or any(day not in range(7) for day in days):
        raise ValueError("days_of_week must contain values 0 through 6")

    before = _list()
    before_ids = {
        item["repeat_item_id"]
        for item in before
        if isinstance(item.get("repeat_item_id"), int) and item["repeat_item_id"] > 0
    }

    raw = _rpc(
        _GWT_ADD,
        food_name=name,
        diary_group=diary_group,
        day_count=len(days),
        day_entries="|".join(f"10|{day}" for day in days),
        quantity=(
            str(int(quantity)) if float(quantity).is_integer() else str(float(quantity))
        ),
        measure_id=measure_id,
        food_id=food_id,
    )
    if not raw.startswith("//OK"):
        raise RuntimeError(f"addRepeatItem failed: {raw[:300]}")

    after = _list()
    candidates = [
        item
        for item in after
        if item.get("repeat_item_id", 0) > 0
        and item["repeat_item_id"] not in before_ids
    ]
    matches = [
        item
        for item in candidates
        if item.get("food_id") == food_id
        and item.get("measure_id") == measure_id
        and abs(float(item.get("quantity", -1)) - float(quantity)) <= 1e-6
        and item.get("diary_group") in (None, diary_group)
        and (not item.get("days_of_week") or item["days_of_week"] == days)
    ]
    if len(matches) != 1:
        rollback_errors = []
        for item in candidates:
            try:
                _delete_transport(item["repeat_item_id"])
            except Exception as exc:
                rollback_errors.append(
                    f"{item['repeat_item_id']}: {type(exc).__name__}: {exc}"
                )
        raise RuntimeError(
            "addRepeatItem returned OK but the write was not uniquely verified; "
            f"candidates={candidates}; rollback_errors={rollback_errors}"
        )
    return matches[0]


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
def get_repeated_items() -> str:
    """List recurring foods with verified IDs, meal groups, and weekdays."""
    try:
        items = _list()
        return core._ok(
            {"count": len(items), "items": items, "backend": "web-gwt-verified"}
        )
    except Exception as exc:
        return core._err(exc)


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
    measure_id: int,
    quantity: float,
    food_name: str,
    diary_group: int = 1,
    days_of_week: list[int] | None = None,
) -> str:
    """Create a recurring food and verify the persisted record.

    food_id comes from search_foods; measure_id comes from search_foods or
    get_food_details. diary_group is 1 breakfast, 2 lunch, 3 dinner, 4 snacks.
    Weekdays are 0 Sunday through 6 Saturday.
    """
    try:
        item = _add(
            food_id,
            measure_id,
            quantity,
            food_name,
            diary_group,
            days_of_week,
        )
        return core._ok({"created": True, "item": item, "backend": "web-gwt-verified"})
    except Exception as exc:
        return core._err(exc)


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
def delete_repeat_item(repeat_item_id: int) -> str:
    """Delete a recurring food by ID and verify that it disappeared."""
    try:
        return core._ok(
            {
                "deleted": _delete(repeat_item_id),
                "repeat_item_id": repeat_item_id,
                "backend": "web-gwt-verified",
            }
        )
    except Exception as exc:
        return core._err(exc)


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
    measure_id: int,
    quantity: float,
    food_name: str,
    diary_group: int = 1,
    days_of_week: list[int] | None = None,
) -> str:
    """Replace a recurring food using verified add-first/delete-second logic."""
    try:
        if repeat_item_id <= 0:
            raise ValueError("repeat_item_id must be greater than zero")
        days = list(range(7)) if days_of_week is None else sorted(set(days_of_week))
        if not days or any(day not in range(7) for day in days):
            raise ValueError("days_of_week must contain values 0 through 6")

        before = _list()
        source = next(
            (item for item in before if item.get("repeat_item_id") == repeat_item_id),
            None,
        )
        if source is None:
            raise ValueError(f"repeat_item_id {repeat_item_id} was not found")

        replacement = _add(
            food_id,
            measure_id,
            quantity,
            food_name,
            diary_group,
            days,
        )
        try:
            _delete(repeat_item_id)
        except Exception as exc:
            return json.dumps(
                {
                    "status": "partial",
                    "message": (
                        "Replacement was created and verified, but deleting the "
                        "source failed. Both may now exist."
                    ),
                    "source": source,
                    "replacement": replacement,
                    "current_items": _list(),
                    "delete_error": f"{type(exc).__name__}: {exc}",
                    "backend": "web-gwt-verified",
                },
                indent=2,
            )

        return core._ok(
            {
                "updated": True,
                "source_repeat_item_id": repeat_item_id,
                "replacement": replacement,
                "backend": "web-gwt-verified",
            }
        )
    except Exception as exc:
        return core._err(exc)
