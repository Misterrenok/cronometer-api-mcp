"""Unit tests for safe biometric editing."""

from __future__ import annotations

import json
from datetime import date


def _payload(raw: str) -> dict:
    return json.loads(raw)


def _source() -> tuple[date, dict]:
    return (
        date(2026, 8, 9),
        {
            "biometricId": 123456,
            "metricId": 1,
            "amount": 180.0,
            "day": "2026-08-09",
        },
    )


def _replacement() -> dict:
    return {
        "biometric_id": "654321",
        "transport_id": "654321",
        "wire_id": "WIRE2",
        "metric_type": "weight",
        "metric_id": 1,
        "input_value": 80.0,
        "input_unit": "kg",
        "stored_value": 176.3698,
        "stored_unit": "lbs",
        "date": "2026-08-10",
    }


def test_update_biometric_adds_replacement_then_deletes_source(monkeypatch):
    from cronometer_api_mcp import biometric_control_tools

    calls: list[tuple] = []
    monkeypatch.setattr(
        biometric_control_tools.hybrid,
        "_find_recent_biometric",
        lambda biometric_id: _source(),
    )
    monkeypatch.setattr(
        biometric_control_tools.hybrid,
        "_date",
        lambda value: date.fromisoformat(value) if value else date(2026, 8, 10),
    )

    def add_verified(**kwargs):
        calls.append(("add", kwargs))
        return _replacement()

    def remove_verified(biometric_id: str):
        calls.append(("remove", biometric_id))
        return {"deleted": True, "biometric_id": biometric_id}

    monkeypatch.setattr(
        biometric_control_tools.hybrid, "_add_biometric_verified", add_verified
    )
    monkeypatch.setattr(
        biometric_control_tools.hybrid, "_remove_biometric_verified", remove_verified
    )

    result = _payload(
        biometric_control_tools.update_biometric(
            biometric_id="123456",
            metric_type="weight",
            value=80,
            date="2026-08-10",
            unit="kg",
        )
    )

    assert result["status"] == "success"
    assert result["updated"] is True
    assert result["source_biometric_id"] == "123456"
    assert result["replacement_biometric_id"] == "654321"
    assert result["replacement"]["stored_unit"] == "lbs"
    assert calls[0][0] == "add"
    assert calls[0][1]["metric_type"] == "weight"
    assert calls[0][1]["day"] == date(2026, 8, 10)
    assert calls[1] == ("remove", "123456")


def test_update_biometric_missing_source_does_not_mutate(monkeypatch):
    from cronometer_api_mcp import biometric_control_tools

    mutated = False
    monkeypatch.setattr(
        biometric_control_tools.hybrid,
        "_find_recent_biometric",
        lambda biometric_id: None,
    )

    def should_not_add(**kwargs):
        nonlocal mutated
        mutated = True
        raise AssertionError("replacement should not be created")

    monkeypatch.setattr(
        biometric_control_tools.hybrid, "_add_biometric_verified", should_not_add
    )

    result = _payload(
        biometric_control_tools.update_biometric(
            biometric_id="999999",
            metric_type="heart_rate",
            value=70,
        )
    )

    assert result["status"] == "error"
    assert "was not found" in result["message"]
    assert mutated is False


def test_update_biometric_delete_exception_returns_partial(monkeypatch):
    from cronometer_api_mcp import biometric_control_tools

    monkeypatch.setattr(
        biometric_control_tools.hybrid,
        "_find_recent_biometric",
        lambda biometric_id: _source(),
    )
    monkeypatch.setattr(
        biometric_control_tools.hybrid, "_date", lambda value: date(2026, 8, 10)
    )
    monkeypatch.setattr(
        biometric_control_tools.hybrid,
        "_add_biometric_verified",
        lambda **kwargs: _replacement(),
    )

    def fail_delete(biometric_id: str):
        raise RuntimeError("delete failed")

    monkeypatch.setattr(
        biometric_control_tools.hybrid, "_remove_biometric_verified", fail_delete
    )

    result = _payload(
        biometric_control_tools.update_biometric(
            biometric_id="123456",
            metric_type="body_fat",
            value=15,
        )
    )

    assert result["status"] == "partial"
    assert result["source_biometric_id"] == "123456"
    assert result["replacement_biometric_id"] == "654321"
    assert result["delete_error"] == "RuntimeError: delete failed"


def test_update_biometric_rejects_unknown_metric_without_delete(monkeypatch):
    from cronometer_api_mcp import biometric_control_tools

    deleted = False
    monkeypatch.setattr(
        biometric_control_tools.hybrid,
        "_find_recent_biometric",
        lambda biometric_id: _source(),
    )
    monkeypatch.setattr(
        biometric_control_tools.hybrid, "_date", lambda value: date(2026, 8, 10)
    )

    def reject_metric(**kwargs):
        raise ValueError("metric_type must be one of: weight, heart_rate")

    def should_not_delete(biometric_id: str):
        nonlocal deleted
        deleted = True
        raise AssertionError("source must remain when replacement validation fails")

    monkeypatch.setattr(
        biometric_control_tools.hybrid, "_add_biometric_verified", reject_metric
    )
    monkeypatch.setattr(
        biometric_control_tools.hybrid, "_remove_biometric_verified", should_not_delete
    )

    result = _payload(
        biometric_control_tools.update_biometric(
            biometric_id="123456",
            metric_type="waist",
            value=80,
        )
    )

    assert result["status"] == "error"
    assert "metric_type" in result["message"]
    assert deleted is False
