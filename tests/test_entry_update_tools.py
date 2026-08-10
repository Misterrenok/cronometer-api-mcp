"""Unit tests for safe food-entry editing."""

from __future__ import annotations

import json
from datetime import date


class FakeClient:
    def __init__(self) -> None:
        self.add_calls = []
        self.delete_calls = []
        self.food = {
            "id": 10,
            "name": "Test Food",
            "measures": [
                {"id": 7, "name": "large", "value": 50.0, "type": "Atomic"},
                {"id": 8, "name": "cup", "value": 240.0, "type": "Atomic"},
            ],
        }
        self.diary = {
            "diary": [
                {
                    "type": "Serving",
                    "servingId": "old",
                    "foodId": 10,
                    "measureId": 7,
                    "grams": 100.0,
                    "translationId": 0,
                    "order": (1 << 16) | 1,
                }
            ]
        }

    def get_diary(self, day: date) -> dict:
        return self.diary

    def get_food(self, food_id: int) -> dict:
        assert food_id == 10
        return self.food

    def add_serving(self, **kwargs) -> dict:
        self.add_calls.append(kwargs)
        return {"id": f"new-{len(self.add_calls)}"}

    def delete_entries(self, entry_ids: list[str], day: date) -> dict:
        self.delete_calls.append((entry_ids, day))
        return {"removed": list(entry_ids), "count": len(entry_ids)}


def _payload(raw: str) -> dict:
    return json.loads(raw)


def test_update_food_entry_changes_grams_safely(monkeypatch):
    from cronometer_api_mcp import entry_update_tools

    client = FakeClient()
    monkeypatch.setattr(entry_update_tools.core, "_get_client", lambda: client)

    result = _payload(
        entry_update_tools.update_food_entry(
            entry_id="old",
            source_date="2026-08-10",
            grams=125,
        )
    )

    assert result["status"] == "success"
    assert result["updated"] is True
    assert client.add_calls[0]["grams"] == 125.0
    assert client.add_calls[0]["measure_id"] == 7
    assert client.add_calls[0]["day"] == date(2026, 8, 10)
    assert client.add_calls[0]["diary_group"] == 1
    assert client.delete_calls == [(["old"], date(2026, 8, 10))]


def test_update_food_entry_quantity_uses_measure_gram_weight(monkeypatch):
    from cronometer_api_mcp import entry_update_tools

    client = FakeClient()
    monkeypatch.setattr(entry_update_tools.core, "_get_client", lambda: client)

    result = _payload(
        entry_update_tools.update_food_entry(
            entry_id="old",
            source_date="2026-08-10",
            measure_id=8,
            quantity=2,
        )
    )

    assert result["status"] == "success"
    assert result["grams"] == 480.0
    assert client.add_calls[0]["measure_id"] == 8
    assert client.add_calls[0]["grams"] == 480.0


def test_update_food_entry_moves_date_and_meal(monkeypatch):
    from cronometer_api_mcp import entry_update_tools

    client = FakeClient()
    monkeypatch.setattr(entry_update_tools.core, "_get_client", lambda: client)

    result = _payload(
        entry_update_tools.update_food_entry(
            entry_id="old",
            source_date="2026-08-10",
            destination_date="2026-08-11",
            diary_group="dinner",
        )
    )

    assert result["status"] == "success"
    assert client.add_calls[0]["grams"] == 100.0
    assert client.add_calls[0]["day"] == date(2026, 8, 11)
    assert client.add_calls[0]["diary_group"] == 3
    assert client.delete_calls == [(["old"], date(2026, 8, 10))]


def test_update_food_entry_no_op(monkeypatch):
    from cronometer_api_mcp import entry_update_tools

    client = FakeClient()
    monkeypatch.setattr(entry_update_tools.core, "_get_client", lambda: client)

    result = _payload(
        entry_update_tools.update_food_entry(
            entry_id="old",
            source_date="2026-08-10",
        )
    )

    assert result["status"] == "success"
    assert result["updated"] is False
    assert result["no_op"] is True
    assert not client.add_calls
    assert not client.delete_calls


def test_update_food_entry_preserves_replacement_when_delete_raises(monkeypatch):
    from cronometer_api_mcp import entry_update_tools

    client = FakeClient()

    def fail_delete(entry_ids: list[str], day: date) -> dict:
        raise RuntimeError("delete failed")

    client.delete_entries = fail_delete
    monkeypatch.setattr(entry_update_tools.core, "_get_client", lambda: client)

    result = _payload(
        entry_update_tools.update_food_entry(
            entry_id="old",
            source_date="2026-08-10",
            grams=110,
        )
    )

    assert result["status"] == "partial"
    assert result["source_entry_id"] == "old"
    assert result["replacement_entry"] == {"id": "new-1"}
    assert result["remove_error"] == "RuntimeError: delete failed"
