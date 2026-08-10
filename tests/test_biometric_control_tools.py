"""Unit tests for safe biometric editing."""

from __future__ import annotations

import json
from datetime import date


class FakeWebClient:
    def __init__(self) -> None:
        self.items = [
            {
                "biometric_id": "OLD123",
                "metric_id": 1,
                "value": 180.0,
                "date": "2026-08-09",
            }
        ]
        self.add_calls = []
        self.delete_calls = []

    def get_recent_biometrics(self) -> list[dict]:
        return [dict(item) for item in self.items]

    def add_biometric(self, metric_type: str, value: float, day: date) -> str:
        self.add_calls.append((metric_type, value, day))
        self.items.append(
            {
                "biometric_id": "NEW456",
                "metric_id": 1,
                "value": value,
                "date": str(day),
            }
        )
        return "NEW456"

    def remove_biometric(self, biometric_id: str) -> bool:
        self.delete_calls.append(biometric_id)
        self.items = [
            item for item in self.items if item["biometric_id"] != biometric_id
        ]
        return True


def _payload(raw: str) -> dict:
    return json.loads(raw)


def test_update_biometric_adds_replacement_then_deletes_source(monkeypatch):
    from cronometer_api_mcp import biometric_control_tools

    client = FakeWebClient()
    monkeypatch.setattr(
        biometric_control_tools.hybrid, "_get_web_client", lambda: client
    )
    monkeypatch.setattr(
        biometric_control_tools.hybrid,
        "_date",
        lambda value: date.fromisoformat(value) if value else date(2026, 8, 10),
    )

    result = _payload(
        biometric_control_tools.update_biometric(
            biometric_id="OLD123",
            metric_type="weight",
            value=80,
            date="2026-08-10",
            unit="kg",
        )
    )

    assert result["status"] == "success"
    assert result["updated"] is True
    assert result["replacement_biometric_id"] == "NEW456"
    assert result["replacement_candidates"][0]["biometric_id"] == "NEW456"
    assert result["stored_unit"] == "lbs"
    assert round(client.add_calls[0][1], 4) == 176.3698
    assert client.add_calls[0][2] == date(2026, 8, 10)
    assert client.delete_calls == ["OLD123"]


def test_update_biometric_missing_source_does_not_mutate(monkeypatch):
    from cronometer_api_mcp import biometric_control_tools

    client = FakeWebClient()
    monkeypatch.setattr(
        biometric_control_tools.hybrid, "_get_web_client", lambda: client
    )
    monkeypatch.setattr(
        biometric_control_tools.hybrid, "_date", lambda value: date(2026, 8, 10)
    )

    result = _payload(
        biometric_control_tools.update_biometric(
            biometric_id="MISSING",
            metric_type="heart_rate",
            value=70,
        )
    )

    assert result["status"] == "error"
    assert "was not found" in result["error"]
    assert not client.add_calls
    assert not client.delete_calls


def test_update_biometric_delete_exception_returns_partial(monkeypatch):
    from cronometer_api_mcp import biometric_control_tools

    client = FakeWebClient()

    def fail_delete(biometric_id: str) -> bool:
        client.delete_calls.append(biometric_id)
        raise RuntimeError("delete failed")

    client.remove_biometric = fail_delete
    monkeypatch.setattr(
        biometric_control_tools.hybrid, "_get_web_client", lambda: client
    )
    monkeypatch.setattr(
        biometric_control_tools.hybrid, "_date", lambda value: date(2026, 8, 10)
    )

    result = _payload(
        biometric_control_tools.update_biometric(
            biometric_id="OLD123",
            metric_type="body_fat",
            value=15,
        )
    )

    assert result["status"] == "partial"
    assert result["source_biometric_id"] == "OLD123"
    assert result["replacement_biometric_id"] == "NEW456"
    assert {item["biometric_id"] for item in result["current_biometrics"]} == {
        "OLD123",
        "NEW456",
    }
    assert result["delete_error"] == "RuntimeError: delete failed"


def test_update_biometric_rejects_unknown_metric_before_mutation(monkeypatch):
    from cronometer_api_mcp import biometric_control_tools

    client = FakeWebClient()
    monkeypatch.setattr(
        biometric_control_tools.hybrid, "_get_web_client", lambda: client
    )

    result = _payload(
        biometric_control_tools.update_biometric(
            biometric_id="OLD123",
            metric_type="waist",
            value=80,
        )
    )

    assert result["status"] == "error"
    assert "metric_type" in result["error"]
    assert not client.add_calls
    assert not client.delete_calls
