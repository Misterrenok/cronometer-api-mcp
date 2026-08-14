"""Tests for recurring-food meal-group wire encoding."""

from __future__ import annotations

from cronometer_api_mcp import repeat_v2_tools as repeat
from cronometer_api_mcp import repeat_v7_patch  # noqa: F401


def test_template_uses_zero_based_group_before_name_reference():
    assert (
        "9|{day_count}|{day_entries}|{diary_group_raw}|11|1|0|"
        in repeat._GWT_ADD
    )


def test_public_lunch_serializes_as_raw_group_one(monkeypatch):
    bodies: list[str] = []
    before = []
    after = [
        {
            "repeat_item_id": 900001,
            "food_id": 464877,
            "measure_id": 1073268,
            "food_name": "Oatmeal, Regular or Quick, Dry",
            "quantity": 3.0,
            "diary_group": 2,
            "days_of_week": [3],
        }
    ]
    reads = iter([before, after])
    monkeypatch.setattr(repeat, "_list", lambda: next(reads))

    def rpc(template: str, **values):
        body = template
        for key, value in values.items():
            body = body.replace("{" + key + "}", str(value))
        bodies.append(body)
        return "//OK[[],0,7]"

    monkeypatch.setattr(repeat, "_rpc", rpc)

    item = repeat._add(
        464877,
        1073268,
        3,
        "Oatmeal, Regular or Quick, Dry",
        2,
        [3],
    )
    assert item["diary_group"] == 2
    assert "|10|3|1|11|1|0|464877|1073268|0|" in bodies[0]
