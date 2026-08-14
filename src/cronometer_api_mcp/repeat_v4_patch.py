"""Robust recurring-item update with in-place probe and rollback fallback."""

from __future__ import annotations

import json

from . import repeat_v2_tools as repeat
from . import repeat_v3_patch as _repeat_v3_patch  # noqa: F401

mcp = repeat.mcp

_GWT_SAVE_EXISTING = (
    "7|0|11|https://cronometer.com/cronometer/|"
    "{gwt_header}|com.cronometer.shared.rpc.CronometerService|"
    "addRepeatItem|java.lang.String/2004016611|"
    "I|com.cronometer.shared.repeatitems.RepeatItem/477684891|{nonce}|"
    "java.util.ArrayList/4159755760|java.lang.Integer/3438268394|"
    "{food_name}|1|2|3|4|3|5|6|7|8|{user_id}|7|{diary_group}|"
    "9|{day_count}|{day_entries}|0|11|{quantity}|0|{food_id}|{measure_id}|"
    "{repeat_item_id}|"
)


def _days(value: list[int] | None) -> list[int]:
    days = list(range(7)) if value is None else sorted(set(value))
    if not days or any(day not in range(7) for day in days):
        raise ValueError("days_of_week must contain values 0 through 6")
    return days


def _matches(
    item: dict | None,
    *,
    food_id: int,
    measure_id: int,
    quantity: float,
    diary_group: int,
    days_of_week: list[int],
) -> bool:
    if not isinstance(item, dict):
        return False
    return (
        item.get("food_id") == food_id
        and item.get("measure_id") == measure_id
        and abs(float(item.get("quantity", -1)) - float(quantity)) <= 1e-6
        and item.get("diary_group") == diary_group
        and item.get("days_of_week") == days_of_week
    )


def _serialize_quantity(quantity: float) -> str:
    return str(int(quantity)) if float(quantity).is_integer() else str(float(quantity))


def _save_existing(
    source: dict,
    *,
    food_id: int,
    measure_id: int,
    quantity: float,
    food_name: str,
    diary_group: int,
    days_of_week: list[int],
) -> dict | None:
    """Try addRepeatItem with a nonzero RepeatItem ID.

    Return the verified updated row when supported. If Cronometer treats the
    call as a no-op, return None. Any unexpected mutation is rolled back or
    raised as a hard error before the caller attempts another strategy.
    """
    repeat_item_id = int(source["repeat_item_id"])
    before = repeat._list()
    before_ids = {
        item["repeat_item_id"]
        for item in before
        if isinstance(item.get("repeat_item_id"), int)
        and item["repeat_item_id"] > 0
    }

    raw = repeat._rpc(
        _GWT_SAVE_EXISTING,
        food_name=food_name.strip() or source["food_name"],
        diary_group=diary_group,
        day_count=len(days_of_week),
        day_entries="|".join(f"10|{day}" for day in days_of_week),
        quantity=_serialize_quantity(quantity),
        food_id=food_id,
        measure_id=measure_id,
        repeat_item_id=repeat_item_id,
    )
    if not raw.startswith("//OK"):
        after_error = repeat._list()
        current = next(
            (
                item
                for item in after_error
                if item.get("repeat_item_id") == repeat_item_id
            ),
            None,
        )
        if current == source:
            return None
        raise RuntimeError(
            "in-place repeat update returned an error and source state changed: "
            f"response={raw[:300]}, source_after={current}"
        )

    after = repeat._list()
    current = next(
        (
            item
            for item in after
            if item.get("repeat_item_id") == repeat_item_id
        ),
        None,
    )
    if _matches(
        current,
        food_id=food_id,
        measure_id=measure_id,
        quantity=quantity,
        diary_group=diary_group,
        days_of_week=days_of_week,
    ):
        return current

    unexpected = [
        item
        for item in after
        if item.get("repeat_item_id", 0) > 0
        and item["repeat_item_id"] not in before_ids
    ]
    cleanup_errors: list[str] = []
    for item in unexpected:
        try:
            repeat._delete(item["repeat_item_id"])
        except Exception as exc:
            cleanup_errors.append(
                f'{item["repeat_item_id"]}: {type(exc).__name__}: {exc}'
            )

    after_cleanup = repeat._list()
    current = next(
        (
            item
            for item in after_cleanup
            if item.get("repeat_item_id") == repeat_item_id
        ),
        None,
    )
    if current == source and not cleanup_errors:
        return None

    # If the probe partially changed the source, restore the original values
    # using the same nonzero-ID path before giving up.
    restore_raw = repeat._rpc(
        _GWT_SAVE_EXISTING,
        food_name=source["food_name"],
        diary_group=int(source["diary_group"]),
        day_count=len(source["days_of_week"]),
        day_entries="|".join(f'10|{day}' for day in source["days_of_week"]),
        quantity=_serialize_quantity(float(source["quantity"])),
        food_id=int(source["food_id"]),
        measure_id=int(source["measure_id"]),
        repeat_item_id=repeat_item_id,
    )
    restored_list = repeat._list()
    restored = next(
        (
            item
            for item in restored_list
            if item.get("repeat_item_id") == repeat_item_id
        ),
        None,
    )
    if restore_raw.startswith("//OK") and restored == source and not cleanup_errors:
        return None

    raise RuntimeError(
        "in-place repeat update could not be safely verified or rolled back; "
        f"source_before={source}; source_after={current}; restored={restored}; "
        f"cleanup_errors={cleanup_errors}; restore_response={restore_raw[:300]}"
    )


repeat._replace_tool("update_repeat_item")


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
    """Update a recurring food with verification and rollback protection.

    Prefer ``measure_id``. ``food_source_id`` is a backward-compatible alias
    for measure_id for clients that cached the old schema.
    """
    try:
        if repeat_item_id <= 0:
            raise ValueError("repeat_item_id must be greater than zero")
        resolved_measure = measure_id if measure_id is not None else food_source_id
        if resolved_measure is None or resolved_measure <= 0 or food_id <= 0:
            raise ValueError("food_id and measure_id must be greater than zero")
        if quantity <= 0:
            raise ValueError("quantity must be greater than zero")
        if diary_group not in (1, 2, 3, 4):
            raise ValueError("diary_group must be 1, 2, 3, or 4")
        target_days = _days(days_of_week)

        before = repeat._list()
        source = next(
            (
                item
                for item in before
                if item.get("repeat_item_id") == repeat_item_id
            ),
            None,
        )
        if source is None:
            raise ValueError(f"repeat_item_id {repeat_item_id} was not found")

        in_place = _save_existing(
            source,
            food_id=food_id,
            measure_id=resolved_measure,
            quantity=quantity,
            food_name=food_name,
            diary_group=diary_group,
            days_of_week=target_days,
        )
        if in_place is not None:
            return repeat.core._ok(
                {
                    "updated": True,
                    "source_repeat_item_id": repeat_item_id,
                    "replacement": in_place,
                    "mode": "in-place-gwt",
                    "backend": "web-gwt-verified",
                }
            )

        same_identity = (
            source.get("food_id") == food_id
            and source.get("measure_id") == resolved_measure
        )
        if not same_identity:
            # Different foods can use add-first/delete-second safely.
            return repeat.update_repeat_item(
                repeat_item_id=repeat_item_id,
                food_id=food_id,
                measure_id=resolved_measure,
                quantity=quantity,
                food_name=food_name,
                diary_group=diary_group,
                days_of_week=target_days,
            )

        # Cronometer may suppress duplicate recurring rows for the same
        # food/measure. For that case, delete the verified source, add the
        # replacement, and restore the source if creation fails.
        repeat._delete(repeat_item_id)
        try:
            replacement = repeat._add(
                food_id,
                resolved_measure,
                quantity,
                food_name,
                diary_group,
                target_days,
            )
        except Exception as target_exc:
            try:
                restored = repeat._add(
                    int(source["food_id"]),
                    int(source["measure_id"]),
                    float(source["quantity"]),
                    str(source["food_name"]),
                    int(source["diary_group"]),
                    list(source["days_of_week"]),
                )
            except Exception as restore_exc:
                return json.dumps(
                    {
                        "status": "partial",
                        "message": (
                            "Updating the recurring item failed after deleting the "
                            "source, and automatic restoration also failed."
                        ),
                        "source": source,
                        "target_error": f"{type(target_exc).__name__}: {target_exc}",
                        "restore_error": (
                            f"{type(restore_exc).__name__}: {restore_exc}"
                        ),
                        "current_items": repeat._list(),
                        "backend": "web-gwt-verified",
                    },
                    indent=2,
                )
            return json.dumps(
                {
                    "status": "error",
                    "message": (
                        "Target update failed, but the original recurring item "
                        "was automatically restored."
                    ),
                    "source": source,
                    "restored": restored,
                    "target_error": f"{type(target_exc).__name__}: {target_exc}",
                    "backend": "web-gwt-verified",
                },
                indent=2,
            )

        return repeat.core._ok(
            {
                "updated": True,
                "source_repeat_item_id": repeat_item_id,
                "replacement": replacement,
                "mode": "delete-add-with-rollback",
                "backend": "web-gwt-verified",
            }
        )
    except Exception as exc:
        return repeat.core._err(exc)
