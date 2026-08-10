"""Unit tests for recurring-item composite controls."""

from __future__ import annotations

import json


class FakeWebClient:
    def __init__(self) -> None:
        self.items = [
            {
                "repeat_item_id": 111,
                "food_name": "Old Food",
                "food_source_id": 10,
                "measure_id": 20,
                "quantity": 1.0,
                "diary_group": 1,
                "days_of_week": [0, 1],
            }
        ]
        self.add_calls = []
        self.delete_calls = []

    def get_repeated_items(self) -> list[dict]:
        return [dict(item) for item in self.items]

    def add_repeat_item(self, **kwargs) -> bool:
        self.add_calls.append(kwargs)
        self.items.append(
            {
                "repeat_item_id": 222,
                "food_name": kwargs["food_name"],
                "food_source_id": kwargs["food_source_id"],
                "measure_id": 999,
                "quantity": kwargs["quantity"],
                "diary_group": kwargs["diary_group"],
                "days_of_week": list(kwargs["days_of_week"]),
            }
        )
        return True

    def delete_repeat_item(self, repeat_item_id: int) -> bool:
        self.delete_calls.append(repeat_item_id)
        self.items = [
            item for item in self.items if item["repeat_item_id"] != repeat_item_id
        ]
        return True


def _payload(raw: str) -> dict:
    return json.loads(raw)


def test_update_repeat_item_creates_replacement_then_deletes_source(monkeypatch):
    from cronometer_api_mcp import repeat_control_tools

    client = FakeWebClient()
    monkeypatch.setattr(
        repeat_control_tools.hybrid, "_get_web_client", lambda: client
    )

    result = _payload(
        repeat_control_tools.update_repeat_item(
            repeat_item_id=111,
            food_source_id=12,
            food_id=34,
            quantity=2.5,
            food_name="New Food",
            diary_group=3,
            days_of_week=[5, 1, 3, 3],
        )
    )

    assert result["status"] == "success"
    assert result["updated"] is True
    assert result["replacement_candidates"][0]["repeat_item_id"] == 222
    assert client.add_calls == [
        {
            "food_source_id": 12,
            "food_id": 34,
            "quantity": 2.5,
            "food_name": "New Food",
            "diary_group": 3,
            "days_of_week": [1, 3, 5],
        }
    ]
    assert client.delete_calls == [111]
    assert [item["repeat_item_id"] for item in client.items] == [222]


def test_update_repeat_item_missing_source_does_not_mutate(monkeypatch):
    from cronometer_api_mcp import repeat_control_tools

    client = FakeWebClient()
    monkeypatch.setattr(
        repeat_control_tools.hybrid, "_get_web_client", lambda: client
    )

    result = _payload(
        repeat_control_tools.update_repeat_item(
            repeat_item_id=999,
            food_source_id=12,
            food_id=34,
            quantity=2,
            food_name="New Food",
        )
    )

    assert result["status"] == "error"
    assert "was not found" in result["error"]
    assert not client.add_calls
    assert not client.delete_calls


def test_update_repeat_item_delete_exception_returns_partial(monkeypatch):
    from cronometer_api_mcp import repeat_control_tools

    client = FakeWebClient()

    def fail_delete(repeat_item_id: int) -> bool:
        client.delete_calls.append(repeat_item_id)
        raise RuntimeError("delete failed")

    client.delete_repeat_item = fail_delete
    monkeypatch.setattr(
        repeat_control_tools.hybrid, "_get_web_client", lambda: client
    )

    result = _payload(
        repeat_control_tools.update_repeat_item(
            repeat_item_id=111,
            food_source_id=12,
            food_id=34,
            quantity=2,
            food_name="New Food",
            diary_group=2,
        )
    )

    assert result["status"] == "partial"
    assert result["source_repeat_item_id"] == 111
    assert result["replacement_candidates"][0]["repeat_item_id"] == 222
    assert {item["repeat_item_id"] for item in result["current_items"]} == {111, 222}
    assert result["delete_error"] == "RuntimeError: delete failed"


def test_update_repeat_item_rejects_empty_days_without_mutation(monkeypatch):
    from cronometer_api_mcp import repeat_control_tools

    client = FakeWebClient()
    monkeypatch.setattr(
        repeat_control_tools.hybrid, "_get_web_client", lambda: client
    )

    result = _payload(
        repeat_control_tools.update_repeat_item(
            repeat_item_id=111,
            food_source_id=12,
            food_id=34,
            quantity=2,
            food_name="New Food",
            days_of_week=[],
        )
    )

    assert result["status"] == "error"
    assert "days_of_week" in result["error"]
    assert not client.add_calls
    assert not client.delete_calls
