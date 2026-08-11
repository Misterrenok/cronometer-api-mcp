"""Regression tests for verified mobile-write compatibility fixes."""

from __future__ import annotations

import httpx
import pytest

from cronometer_api_mcp import gwt_macro_template_fix, mobile_write_fixes
from cronometer_api_mcp.client import CronometerError


class FakeResponse:
    def __init__(self, status_code: int, data: dict, text: str = "") -> None:
        self.status_code = status_code
        self._data = data
        self.text = text

    def json(self) -> dict:
        return self._data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("POST", "https://example.test/api")
            response = httpx.Response(self.status_code, request=request, text=self.text)
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}", request=request, response=response
            )


class FakeHttp:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict]] = []

    def post(self, endpoint: str, json: dict) -> FakeResponse:
        self.calls.append((endpoint, json))
        return self.responses.pop(0)


class FakeClient:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self._http = FakeHttp(responses)
        self.invalidations = 0
        self.logins = 0
        self.auth_checks = 0

    def _ensure_auth(self) -> None:
        self.auth_checks += 1

    def _auth_block(self) -> dict:
        return {"userId": 1, "token": "token"}

    def _invalidate_session(self) -> None:
        self.invalidations += 1

    def login(self) -> None:
        self.logins += 1


class FakeWebTemplateClient:
    gwt_header = "STRONGNAME"
    nonce = "nonce"
    user_id = "16039098"

    def __init__(self, raw: str = "//OK[1]") -> None:
        self.raw = raw
        self.bodies: list[str] = []
        self.auth_calls = 0
        self.deleted: list[int] = []

    def authenticate(self) -> None:
        self.auth_calls += 1

    def _gwt_post(self, body: str) -> str:
        self.bodies.append(body)
        return self.raw

    def delete_macro_target_template(self, template_id: int) -> bool:
        self.deleted.append(template_id)
        return True


def test_safe_request_does_not_relogin_for_functional_403() -> None:
    client = FakeClient([FakeResponse(403, {}, "endpoint is not allowed")])

    with pytest.raises(httpx.HTTPStatusError):
        mobile_write_fixes._safe_v2_request(client, "/api/v2/test", {"x": 1})

    assert client.invalidations == 0
    assert client.logins == 0
    assert len(client._http.calls) == 1


def test_safe_request_reauthenticates_once_for_explicit_session_failure() -> None:
    client = FakeClient(
        [
            FakeResponse(403, {}, "session expired"),
            FakeResponse(200, {"result": "SUCCESS"}),
        ]
    )

    result = mobile_write_fixes._safe_v2_request(client, "/api/v2/test", {"x": 1})

    assert result == {"result": "SUCCESS"}
    assert client.invalidations == 1
    assert client.logins == 1
    assert len(client._http.calls) == 2


def test_safe_request_does_not_relogin_for_functional_body_fail() -> None:
    client = FakeClient(
        [FakeResponse(200, {"result": "FAIL", "error": "Unsupported operation"})]
    )

    with pytest.raises(CronometerError, match="Unsupported operation"):
        mobile_write_fixes._safe_v2_request(client, "/api/v2/test", {})

    assert client.invalidations == 0
    assert client.logins == 0


def test_biometric_unit_ids_match_mobile_catalog() -> None:
    assert mobile_write_fixes._unit_id("heart_rate", "bpm") == 5
    assert mobile_write_fixes._unit_id("blood_glucose", "mmol/L") == 8
    assert mobile_write_fixes._unit_id("blood_glucose", "mg/dL") == 9
    assert mobile_write_fixes._unit_id("body_fat", "%") == 13


def test_template_helpers_accept_current_mobile_shapes() -> None:
    template = {
        "templateId": "42",
        "templateName": "Probe",
        "protein": 123.4,
        "fat": 67.8,
        "carbs": 234.5,
        "energy": 2042.0,
    }

    assert mobile_write_fixes._template_id(template) == 42
    assert mobile_write_fixes._template_name(template) == "Probe"
    assert mobile_write_fixes._template_matches(
        template,
        name="Probe",
        protein_g=123.4,
        fat_g=67.8,
        carbs_g=234.5,
        calories=2042.0,
    )


def test_gwt_create_body_uses_current_name_and_int_field_order() -> None:
    client = FakeWebTemplateClient()

    body = gwt_macro_template_fix._build_create_body(
        client,
        "Probe Template",
        protein_g=148.55,
        fat_g=99.0333,
        carbs_g=371.375,
        calories=2971.0,
    )

    assert body.startswith("7|0|12|https://cronometer.com/cronometer/|")
    assert "|java.lang.Integer/3438268394|Probe Template|" in body
    assert "Rigorous" not in body
    # Fields 9..13: Integer(0), int(0), String(name index 12), int(0), Double.
    assert "|11|0|0|12|0|10|148.55|" in body
    # The stale client encoded string-table indexes 12/13 into primitive ints.
    assert "|11|0|12|0|13|" not in body


def test_gwt_create_returns_only_mobile_verified_template_id(monkeypatch) -> None:
    client = FakeWebTemplateClient()
    saved = {
        "templateId": 42,
        "templateName": "Probe Template",
        "protein": 148.55,
        "fat": 99.0333,
        "carbs": 371.375,
        "energy": 2971.0,
    }
    reads = iter([[], [saved]])
    monkeypatch.setattr(
        mobile_write_fixes, "_raw_mobile_templates", lambda: next(reads)
    )

    template_id = gwt_macro_template_fix.save_macro_target_template_gwt_verified(
        client,
        "Probe Template",
        protein_g=148.55,
        fat_g=99.0333,
        carbs_g=371.375,
        calories=2971.0,
    )

    assert template_id == 42
    assert client.auth_calls == 1
    assert len(client.bodies) == 1
    assert client.deleted == []


def test_gwt_create_rejects_transport_ok_without_persistence(monkeypatch) -> None:
    client = FakeWebTemplateClient()
    reads = iter([[], []])
    monkeypatch.setattr(
        mobile_write_fixes, "_raw_mobile_templates", lambda: next(reads)
    )

    with pytest.raises(RuntimeError, match="no exact persisted template"):
        gwt_macro_template_fix.save_macro_target_template_gwt_verified(
            client,
            "Probe Template",
            protein_g=120.0,
            fat_g=60.0,
            carbs_g=200.0,
            calories=1820.0,
        )

    assert len(client.bodies) == 1
