"""Unit tests for composite diary control tools."""

from __future__ import annotations

import json
from datetime import date


class FakeClient:
    def __init__(self) -> None:
        self.add_calls = []
        self.delete_calls = []
        self.request_calls = []
        self.food = {
            "id": 10,
            "name": "Test Food",
            "measures": [
                {"id": 7, "name": "large", "value": 50.0, "type": "Atomic"},
                {"id": 8, "name": "serving", "value": 1.0, "type": "Recipe"},
            ],
        }
        self.diary = {"diary": []}

    def today(self) -> date:
        return date(2026, 8, 10)

    def get_food(self, food_id: int) -> dict:
        assert food_id == 10
        return self.food

    def add_serving(self, **kwargs) -> dict:
        self.add_calls.append(kwargs)
        return {"id": f"new-{len(self.add_calls)}"}

    def get_diary(self, day: date) -> dict:
        return self.diary

    def delete_entries(self, entry_ids: list[str], day: date) -> dict:
        self.delete_calls.append((entry_ids, day))
        return {"removed": list(entry_ids), "count": len(entry_ids)}

    def _format_day(self, day: date) -> str:
        return f"{day.year}-{day.month}-{day.day}"

    def _request(self, endpoint: str, payload: dict) -> dict:
        self.request_calls.append((endpoint, payload))
        return {"copied": True}


def _payload(raw: str) -> dict:
    return json.loads(raw)


def _serving(
    serving_id: str,
    *,
    meal_group: int = 1,
    food_id: int = 10,
    measure_id: int = 7,
    grams: float = 50.0,
) -> dict:
    return {
        "type": "Serving",
        "servingId": serving_id,
        "foodId": food_id,
        "measureId": measure_id,
        "grams": grams,
        "translationId": 0,
        "order": (meal_group << 16) | 1,
    }


def test_add_food_entry_by_measure_converts_quantity(monkeypatch):
    from cronometer_api_mcp import control_tools

    client = FakeClient()
    monkeypatch.setattr(control_tools.core, "_get_client", lambda: client)

    result = _payload(
        control_tools.add_food_entry_by_measure(
            food_id=10,
            measure_id=7,
            quantity=2,
            date="2026-08-09",
            diary_group="breakfast",
        )
    )

    assert result["status"] == "success"
    assert result["api_amount"] == 100.0
    call = client.add_calls[0]
    assert call["grams"] == 100.0
    assert call["measure_id"] == 7
    assert call["day"] == date(2026, 8, 9)
    assert call["diary_group"] == 1


def test_add_food_entry_by_measure_recipe_uses_serving_count(monkeypatch):
    from cronometer_api_mcp import control_tools

    client = FakeClient()
    monkeypatch.setattr(control_tools.core, "_get_client", lambda: client)

    result = _payload(
        control_tools.add_food_entry_by_measure(
            food_id=10,
            measure_id=8,
            quantity=1.5,
        )
    )

    assert result["status"] == "success"
    assert client.add_calls[0]["grams"] == 1.5


def test_copy_food_entry_preserves_meal_group(monkeypatch):
    from cronometer_api_mcp import control_tools

    client = FakeClient()
    client.diary = {"diary": [_serving("old", meal_group=2, grams=75)]}
    monkeypatch.setattr(control_tools.core, "_get_client", lambda: client)

    result = _payload(
        control_tools.copy_food_entry(
            entry_id="old",
            source_date="2026-08-09",
            destination_date="2026-08-10",
        )
    )

    assert result["status"] == "success"
    assert client.add_calls[0]["grams"] == 75.0
    assert client.add_calls[0]["diary_group"] == 2
    assert client.add_calls[0]["day"] == date(2026, 8, 10)
    assert not client.delete_calls


def test_move_food_entry_adds_before_delete(monkeypatch):
    from cronometer_api_mcp import control_tools

    client = FakeClient()
    client.diary = {"diary": [_serving("old", meal_group=2)]}
    monkeypatch.setattr(control_tools.core, "_get_client", lambda: client)

    result = _payload(
        control_tools.move_food_entry(
            entry_id="old",
            source_date="2026-08-09",
            destination_date="2026-08-10",
            diary_group="dinner",
        )
    )

    assert result["status"] == "success"
    assert result["moved"] is True
    assert client.add_calls[0]["diary_group"] == 3
    assert client.delete_calls == [(["old"], date(2026, 8, 9))]


def test_copy_meal_between_dates_copies_only_selected_food_group(monkeypatch):
    from cronometer_api_mcp import control_tools

    client = FakeClient()
    client.diary = {
        "diary": [
            _serving("breakfast", meal_group=1),
            _serving("lunch-1", meal_group=2, grams=60),
            _serving("lunch-2", meal_group=2, grams=80),
            {"type": "Exercise", "servingId": "exercise", "order": (2 << 16) | 1},
        ]
    }
    monkeypatch.setattr(control_tools.core, "_get_client", lambda: client)

    result = _payload(
        control_tools.copy_meal_between_dates(
            source_date="2026-08-09",
            destination_date="2026-08-10",
            diary_group="lunch",
        )
    )

    assert result["status"] == "success"
    assert result["copied_count"] == 2
    assert [call["grams"] for call in client.add_calls] == [60.0, 80.0]
    assert all(call["diary_group"] == 2 for call in client.add_calls)
    assert all(call["day"] == date(2026, 8, 10) for call in client.add_calls)
    assert not client.delete_calls


def test_clear_food_entries_filters_meal_and_non_food(monkeypatch):
    from cronometer_api_mcp import control_tools

    client = FakeClient()
    client.diary = {
        "diary": [
            _serving("breakfast", meal_group=1),
            _serving("lunch", meal_group=2),
            {"type": "Exercise", "servingId": "exercise", "order": (2 << 16) | 1},
        ]
    }
    monkeypatch.setattr(control_tools.core, "_get_client", lambda: client)

    result = _payload(
        control_tools.clear_food_entries(
            date="2026-08-10",
            diary_group="lunch",
        )
    )

    assert result["status"] == "success"
    assert result["removed"] == ["lunch"]
    assert client.delete_calls == [(["lunch"], date(2026, 8, 10))]
