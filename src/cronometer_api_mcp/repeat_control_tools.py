"""Composite write controls for recurring Cronometer food entries."""

from __future__ import annotations

import json

from . import hybrid_tools as hybrid
from . import server as core

mcp = core.mcp


def _repeat_id(item: dict) -> int | None:
    value = item.get("repeat_item_id")
    return value if isinstance(value, int) and value > 0 else None


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
    food_source_id: int,
    food_id: int,
    quantity: float,
    food_name: str,
    diary_group: int = 1,
    days_of_week: list[int] | None = None,
) -> str:
    """Replace an existing recurring food entry with updated settings.

    Cronometer's confirmed web backend exposes list/add/delete for repeat items
    but no direct update call. This tool composes those operations safely:
    verify the source exists, create the replacement first, re-read the list,
    then delete the old repeat item. A failed add leaves the source untouched.
    If deletion fails after creation, the response is marked partial and
    includes the current repeat-item list so the duplicate is visible.

    Args:
        repeat_item_id: Existing recurring-item ID from get_repeated_items.
        food_source_id: Web Cronometer food source ID for the replacement.
        food_id: Web Cronometer food ID for the replacement.
        quantity: Number of default servings; must be greater than zero.
        food_name: Replacement display name.
        diary_group: 1 breakfast, 2 lunch, 3 dinner, 4 snacks.
        days_of_week: 0=Sunday through 6=Saturday; defaults to every day.
    """
    try:
        if repeat_item_id <= 0:
            raise ValueError("repeat_item_id must be greater than zero")
        if food_source_id <= 0 or food_id <= 0:
            raise ValueError("food_source_id and food_id must be greater than zero")
        if quantity <= 0:
            raise ValueError("quantity must be greater than zero")
        if not food_name.strip():
            raise ValueError("food_name cannot be empty")
        if diary_group not in (1, 2, 3, 4):
            raise ValueError("diary_group must be 1, 2, 3, or 4")

        days = list(range(7)) if days_of_week is None else sorted(set(days_of_week))
        if not days or any(day not in range(7) for day in days):
            raise ValueError("days_of_week must contain values 0 through 6")

        client = hybrid._get_web_client()
        before = client.get_repeated_items()
        source = next(
            (
                item
                for item in before
                if isinstance(item, dict) and _repeat_id(item) == repeat_item_id
            ),
            None,
        )
        if source is None:
            raise ValueError(f"repeat_item_id {repeat_item_id} was not found")

        before_ids = {
            item_id
            for item in before
            if isinstance(item, dict) and (item_id := _repeat_id(item)) is not None
        }

        created = client.add_repeat_item(
            food_source_id=food_source_id,
            food_id=food_id,
            quantity=float(quantity),
            food_name=food_name.strip(),
            diary_group=diary_group,
            days_of_week=days,
        )
        if not created:
            raise RuntimeError("Cronometer did not confirm creation of the replacement")

        after_add = client.get_repeated_items()
        replacement_candidates = [
            item
            for item in after_add
            if isinstance(item, dict)
            and (item_id := _repeat_id(item)) is not None
            and item_id not in before_ids
        ]

        try:
            deleted = client.delete_repeat_item(repeat_item_id)
        except Exception as exc:
            current = client.get_repeated_items()
            return json.dumps(
                {
                    "status": "partial",
                    "message": (
                        "Replacement recurring item was created, but deleting the "
                        "source raised an error. Both may now exist."
                    ),
                    "source_repeat_item_id": repeat_item_id,
                    "source": source,
                    "replacement_candidates": replacement_candidates,
                    "current_items": current,
                    "delete_error": f"{type(exc).__name__}: {exc}",
                    "backend": "web-gwt",
                },
                indent=2,
            )

        if not deleted:
            current = client.get_repeated_items()
            return json.dumps(
                {
                    "status": "partial",
                    "message": (
                        "Replacement recurring item was created, but Cronometer did "
                        "not confirm deletion of the source. Both may now exist."
                    ),
                    "source_repeat_item_id": repeat_item_id,
                    "source": source,
                    "replacement_candidates": replacement_candidates,
                    "current_items": current,
                    "backend": "web-gwt",
                },
                indent=2,
            )

        return core._ok(
            {
                "updated": True,
                "source_repeat_item_id": repeat_item_id,
                "replacement_candidates": replacement_candidates,
                "replacement": {
                    "food_source_id": food_source_id,
                    "food_id": food_id,
                    "quantity": float(quantity),
                    "food_name": food_name.strip(),
                    "diary_group": diary_group,
                    "days_of_week": days,
                },
                "backend": "web-gwt",
            }
        )
    except Exception as e:
        return core._err(e)
