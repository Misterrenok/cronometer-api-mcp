"""Regression tests for verified mobile-write compatibility fixes."""

from __future__ import annotations

import httpx
import pytest

from cronometer_api_mcp import mobile_write_fixes
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

    result = mobile_write_fixes._safe_v2_request(
        client, "/api/v2/test", {"x": 1}
    )

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
