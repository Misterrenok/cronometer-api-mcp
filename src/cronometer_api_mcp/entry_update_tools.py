"""Safe edit operations for existing Cronometer food diary entries."""

from __future__ import annotations

import json

from . import server as core
from .control_tools import (
    _entry_meal_group,
    _find_serving,
    _meal_group,
    _measure_quantity_to_api_amount,
)

mcp = core.mcp


def _resolve_measure(client, food_id: int, measure_id: int) -> dict:
    """Resolve one measure from a food and require a usable positive value."""
    food = client.get_food(food_id)
    measures = [m for m in food.get("measures", []) if isinstance(m, dict)]
    measure = next((m for m in measures if m.get("id") == measure_id), None)
    if measure is None:
        available = [
            {
                "measure_id": m.get("id"),
                "name": m.get("name"),
                "value": m.get("value"),
            }
            for m in measures
        ]
        raise ValueError(
            f"measure_id {measure_id} is not available for food_id {food_id}. "
            f"Available measures: {available}"
        )

    value = measure.get("value")
    if not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(
            f"Measure {measure_id} has no usable value: {value!r}"
        )
    return measure


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": True,
    }
)
def update_food_entry(
    entry_id: str,
    source_date: str,
    destination_date: str | None = None,
    grams: float | None = None,
    measure_id: int | None = None,
    quantity: float | None = None,
    diary_group: str = "preserve",
) -> str:
    """Edit an existing food entry's amount, serving measure, date, or meal.

    The edit is implemented with confirmed Cronometer operations only: create
    the replacement first, then delete the original. That means a failed create
    cannot lose the source entry. If deletion fails after creation, the response
    is marked partial and includes the replacement entry so a retry does not
    silently create duplicates.

    Amount rules:
    - grams sets an exact physical gram weight for Weight/Atomic measures.
      Recipe entries do not use physical grams in Cronometer's diary payload;
      use quantity with the reference Recipe serving measure instead.
    - quantity uses the selected serving measure. Weight/Atomic measures are
      converted through grams-per-unit. Confirmed reference Recipe measures
      (value=1) pass quantity directly as Cronometer's serving-count field.
    - grams and quantity are mutually exclusive.
    - if both are omitted, the source raw amount is preserved, which is safe
      for moving an existing Recipe entry without changing its amount.

    Args:
        entry_id: Existing serving ID from get_food_log/get_diary_raw.
        source_date: Date containing the source entry, YYYY-MM-DD.
        destination_date: Optional new date; defaults to source_date.
        grams: Optional exact physical grams for Weight/Atomic entries.
        measure_id: Optional new serving measure ID.
        quantity: Optional number of selected serving units.
        diary_group: preserve, breakfast, lunch, dinner, or snacks.
    """
    try:
        if grams is not None and quantity is not None:
            raise ValueError("grams and quantity are mutually exclusive")
        if grams is not None and grams <= 0:
            raise ValueError("grams must be greater than zero")
        if quantity is not None and quantity <= 0:
            raise ValueError("quantity must be greater than zero")

        source = core._parse_date(source_date)
        destination = core._parse_date(destination_date or source_date)
        if source is None or destination is None:
            raise ValueError("source_date is required")

        client = core._get_client()
        entry = _find_serving(client, entry_id, source)

        food_id = entry.get("foodId")
        if not isinstance(food_id, int):
            raise ValueError("Source diary entry is missing a numeric foodId.")

        source_amount = entry.get("grams")
        if not isinstance(source_amount, (int, float)):
            raise ValueError("Source diary entry is missing a numeric amount value.")

        source_measure_id = entry.get("measureId")
        if source_measure_id is not None and not isinstance(source_measure_id, int):
            raise ValueError("Source diary entry has an invalid measureId.")
        target_measure_id = measure_id if measure_id is not None else source_measure_id

        measure = None
        should_resolve_measure = (
            isinstance(target_measure_id, int)
            and target_measure_id > 0
            and (quantity is not None or grams is not None or measure_id is not None)
        )
        if should_resolve_measure:
            measure = _resolve_measure(client, food_id, target_measure_id)

        if quantity is not None:
            if measure is None:
                raise ValueError(
                    "quantity requires a valid positive measure_id on the source "
                    "entry or in the request"
                )
            target_amount = _measure_quantity_to_api_amount(measure, quantity)
        elif grams is not None:
            if measure is not None and measure.get("type") == "Recipe":
                raise ValueError(
                    "Recipe diary entries store a serving count rather than physical "
                    "grams. Use quantity with the reference Recipe serving measure."
                )
            target_amount = float(grams)
        else:
            target_amount = float(source_amount)
            if (
                measure_id is not None
                and measure is not None
                and measure.get("type") == "Recipe"
                and target_measure_id != source_measure_id
            ):
                raise ValueError(
                    "Changing to a Recipe measure requires quantity so the replacement "
                    "amount is explicit."
                )

        source_group = _entry_meal_group(entry)
        if diary_group.strip().lower() == "preserve":
            target_group = source_group
        else:
            target_group = _meal_group(diary_group, allow_auto=False)

        if (
            destination == source
            and target_group == source_group
            and target_measure_id == source_measure_id
            and target_amount == float(source_amount)
        ):
            return core._ok(
                {
                    "updated": False,
                    "no_op": True,
                    "entry_id": str(entry_id),
                    "date": source_date,
                }
            )

        translation_id = entry.get("translationId", 0)
        if not isinstance(translation_id, int):
            translation_id = 0

        created = client.add_serving(
            food_id=food_id,
            measure_id=target_measure_id,
            grams=target_amount,
            translation_id=translation_id,
            day=destination,
            diary_group=target_group,
        )

        try:
            removed = client.delete_entries([str(entry_id)], source)
        except Exception as exc:
            return json.dumps(
                {
                    "status": "partial",
                    "message": (
                        "Replacement entry was created, but removing the source entry "
                        "raised an error. Both entries may now exist."
                    ),
                    "source_entry_id": str(entry_id),
                    "source_date": source_date,
                    "destination_date": destination.isoformat(),
                    "replacement_entry": created,
                    "remove_error": f"{type(exc).__name__}: {exc}",
                },
                indent=2,
            )

        removed_ids = [str(value) for value in removed.get("removed", [])]
        if str(entry_id) not in removed_ids:
            return json.dumps(
                {
                    "status": "partial",
                    "message": (
                        "Replacement entry was created, but the source entry could "
                        "not be removed. Both entries may now exist."
                    ),
                    "source_entry_id": str(entry_id),
                    "source_date": source_date,
                    "destination_date": destination.isoformat(),
                    "replacement_entry": created,
                    "remove_result": removed,
                },
                indent=2,
            )

        amount_kind = "preserved_raw_amount"
        if measure is not None:
            amount_kind = (
                "recipe_servings" if measure.get("type") == "Recipe" else "grams"
            )
        elif grams is not None:
            amount_kind = "grams"

        return core._ok(
            {
                "updated": True,
                "source_entry_id": str(entry_id),
                "source_date": source_date,
                "destination_date": destination.isoformat(),
                "food_id": food_id,
                "measure_id": target_measure_id,
                "quantity": quantity,
                "api_amount": target_amount,
                "api_amount_kind": amount_kind,
                "diary_group": target_group,
                "measure": (
                    {
                        "name": measure.get("name"),
                        "type": measure.get("type"),
                        "value": measure.get("value"),
                    }
                    if measure is not None
                    else None
                ),
                "replacement_entry": created,
            }
        )
    except Exception as e:
        return core._err(e)
