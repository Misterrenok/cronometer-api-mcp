"""Final rollback-safe recurring-item update strategy.

Cronometer's web backend returns HTTP 500 when addRepeatItem is sent with a
nonzero RepeatItem ID, so same-food updates cannot be performed in place.
For the same food/measure this module uses verified delete-then-add with an
automatic restore of the original row if target creation fails. Updates that
change food or measure retain the safer add-first/delete-second strategy.
"""

from __future__ import annotations

import json

from . import repeat_v2_tools as repeat
from . import repeat_v3_patch as _repeat_v3_patch  # noqa: F401

mcp = repeat.mcp

repeat._replace_tool("update_repeat_item")


def _resolve_days(value: list[int] | None) -> list[int]:
    days = list(range(7)) if value is None else sorted(set(value))
    if not days or any(day not in range(7) for day in days):
        raise ValueError("days_of_week must contain values 0 through 6")
    return days


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
    """Update a recurring food with read-back verification and rollback.

    Prefer ``measure_id``. ``food_source_id`` is a backward-compatible alias
    for measure_id for clients that cached the old broken schema.
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
        target_days = _resolve_days(days_of_week)

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

        same_identity = (
            source.get("food_id") == food_id
            and source.get("measure_id") == resolved_measure
        )
        if not same_identity:
            return repeat.update_repeat_item(
                repeat_item_id=repeat_item_id,
                food_id=food_id,
                measure_id=resolved_measure,
                quantity=quantity,
                food_name=food_name,
                diary_group=diary_group,
                days_of_week=target_days,
            )

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
                            "Target update failed after deleting the source, and "
                            "automatic restoration also failed."
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
