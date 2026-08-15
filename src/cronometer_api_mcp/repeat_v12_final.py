"""Final verified recurring-food GWT wire patch.

Cronometer's current compiled RepeatItem serializer is:

    writeDouble(a)   # quantity
    writeObject(b)   # weekday list
    writeObject(c)   # java.lang.Integer packed DiaryGroup sort key
    writeString(d)   # food name
    writeBoolean(e)  # enabled
    writeInt(f)      # repeat item id (0 for create)
    writeInt(g)      # food id
    writeInt(i)      # measure id
    writeObject(j)   # optional Time (null when omitted)

The current DiaryGroup constructor stores ``group_index << 16`` in that sort
key. Index 0 is Uncategorized and the standard meal groups are 1..4:
Breakfast, Lunch, Dinner, Snacks.

A create is accepted only after getRepeatedItems read-back matches the
requested food, measure, amount, meal group and weekdays. Mismatched new rows
are rolled back automatically.
"""

from __future__ import annotations

from . import repeat_v2_tools as repeat
from . import repeat_v3_patch as _repeat_v3_patch  # noqa: F401
from . import repeat_v5_patch as _repeat_v5_patch  # noqa: F401
from . import repeat_v6_patch as _repeat_v6_patch  # noqa: F401


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

    before = repeat._list()
    before_ids = {
        item["repeat_item_id"]
        for item in before
        if isinstance(item.get("repeat_item_id"), int) and item["repeat_item_id"] > 0
    }

    raw = repeat._rpc(
        repeat._GWT_ADD,
        food_name=name,
        quantity=(
            str(int(quantity)) if float(quantity).is_integer() else str(float(quantity))
        ),
        day_count=len(days),
        day_entries="|".join(f"10|{day}" for day in days),
        diary_group_raw=diary_group << 16,
        food_id=food_id,
        measure_id=measure_id,
    )
    if not raw.startswith("//OK"):
        raise RuntimeError(f"addRepeatItem failed: {raw[:300]}")

    after_raw = repeat._rpc(repeat._GWT_GET)
    if not after_raw.startswith("//OK"):
        raise RuntimeError(f"getRepeatedItems verification failed: {after_raw[:300]}")
    after = repeat._parse(after_raw)
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
        and item.get("diary_group") == diary_group
        and item.get("days_of_week") == days
    ]
    if len(matches) != 1:
        rollback_errors: list[str] = []
        for item in candidates:
            try:
                repeat._delete_transport(item["repeat_item_id"])
            except Exception as exc:
                rollback_errors.append(
                    f"{item['repeat_item_id']}: {type(exc).__name__}: {exc}"
                )
        message = (
            "addRepeatItem returned OK but the write was not uniquely verified; "
            f"candidate_count={len(candidates)}"
        )
        if rollback_errors:
            message += f"; rollback_errors={rollback_errors}"
        raise RuntimeError(message)
    return matches[0]


repeat._add = _add
mcp = repeat.mcp

repeat._replace_tool("get_repeated_items")


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
        items = repeat._list()
        return repeat.core._ok(
            {"count": len(items), "items": items, "backend": "web-gwt-verified"}
        )
    except Exception as exc:
        return repeat.core._err(exc)
