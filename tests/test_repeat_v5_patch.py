"""Tests for final rollback-safe recurring update strategy."""

from __future__ import annotations

import json

from cronometer_api_mcp import repeat_v2_tools as repeat
from cronometer_api_mcp import repeat_v5_patch


SOURCE = {
    "repeat_item_id": 845577,
    "food_id": 464877,
    "measure_id": 1073268,
    "food_name": "Oatmeal, Regular or Quick, Dry",
    "quantity": 1.0,
    "diary_group": 1,
    "days_of_week": [1],
}


def test_same_food_update_deletes_then_adds_verified_replacement(monkeypatch):
    deleted: list[int] = []
    add_calls: list[tuple] = []
    replacement = {
        **SOURCE,
        "repeat_item_id": 845600,
        "quantity": 2.0,
        "diary_group": 2,
        "days_of_week": [3],
    }

    monkeypatch.setattr(repeat, "_list", lambda: [dict(SOURCE)])
    monkeypatch.setattr(
        repeat,
        "_delete",
        lambda repeat_item_id: deleted.append(repeat_item_id) or True,
    )

    def add(*args):
        add_calls.append(args)
        return dict(replacement)

    monkeypatch.setattr(repeat, "_add", add)

    payload = json.loads(
        repeat_v5_patch.update_repeat_item(
            repeat_item_id=845577,
            food_source_id=1073268,
            food_id=464877,
            quantity=2,
            food_name="MCP TEST Oatmeal Updated",
            diary_group=2,
            days_of_week=[3],
        )
    )

    assert payload["status"] == "success"
    assert payload["mode"] == "delete-add-with-rollback"
    assert payload["replacement"]["repeat_item_id"] == 845600
    assert deleted == [845577]
    assert add_calls == [
        (
            464877,
            1073268,
            2,
            "MCP TEST Oatmeal Updated",
            2,
            [3],
        )
    ]


def test_failed_target_creation_restores_original(monkeypatch):
    deleted: list[int] = []
    add_calls: list[tuple] = []
    restored = {**SOURCE, "repeat_item_id": 845601}

    monkeypatch.setattr(repeat, "_list", lambda: [dict(SOURCE)])
    monkeypatch.setattr(
        repeat,
        "_delete",
        lambda repeat_item_id: deleted.append(repeat_item_id) or True,
    )

    def add(*args):
        add_calls.append(args)
        if len(add_calls) == 1:
            raise RuntimeError("target failed")
        return dict(restored)

    monkeypatch.setattr(repeat, "_add", add)

    payload = json.loads(
        repeat_v5_patch.update_repeat_item(
            repeat_item_id=845577,
            food_source_id=1073268,
            food_id=464877,
            quantity=2,
            food_name="MCP TEST Oatmeal Updated",
            diary_group=2,
            days_of_week=[3],
        )
    )

    assert payload["status"] == "error"
    assert "automatically restored" in payload["message"]
    assert payload["restored"]["food_id"] == 464877
    assert len(add_calls) == 2
