"""Verified mobile-write fixes for Cronometer API regressions.

The pinned web-GWT client has stale write paths in the current Cronometer
backend: several biometric types can silently become Weight, and saved macro
templates can return transport success without persisting. This module routes
those operations through the mobile REST API and accepts success only after a
read-back verifies the exact object that was requested.
"""

from __future__ import annotations

from datetime import date
from types import MethodType

from . import hybrid_tools as hybrid
from . import server as core
from .client import CronometerError

_ORIGINAL_ADD = hybrid._add_biometric_verified
_ORIGINAL_GET_WEB_CLIENT = hybrid._get_web_client

_UNIT_IDS = {
    "heart_rate": {"bpm": 5},
    "blood_glucose": {"mmol/l": 8, "mg/dl": 9},
    "body_fat": {"%": 13, "percent": 13},
}

_AUTH_MARKERS = (
    "auth",
    "session",
    "token",
    "expired",
    "login required",
    "not logged",
    "not authenticated",
)


def _is_auth_failure(value: object) -> bool:
    text = str(value).lower()
    return any(marker in text for marker in _AUTH_MARKERS)


def _safe_v2_request(
    self,
    endpoint: str,
    payload: dict,
    *,
    _retried: bool = False,
) -> dict:
    """Retry only genuine auth failures, never ordinary endpoint failures.

    The base client historically treated every HTTP 403 and every JSON
    ``result=FAIL`` as an expired session. A functional write rejection could
    therefore erase a valid session and trigger repeated /login calls. This
    replacement preserves the session unless the response explicitly points to
    auth/session/token expiry.
    """
    self._ensure_auth()

    request_payload = dict(payload)
    request_payload["auth"] = self._auth_block()
    request_payload.setdefault("lastSeen", 0)

    response = self._http.post(endpoint, json=request_payload)
    response_text = getattr(response, "text", "")
    auth_http_failure = response.status_code == 401 or (
        response.status_code == 403 and _is_auth_failure(response_text)
    )
    if auth_http_failure and not _retried:
        self._invalidate_session()
        self.login()
        return _safe_v2_request(self, endpoint, payload, _retried=True)

    response.raise_for_status()
    data = response.json()
    if isinstance(data, dict) and data.get("result") in ("FAIL", "FAILURE"):
        if _is_auth_failure(data) and not _retried:
            self._invalidate_session()
            self.login()
            return _safe_v2_request(self, endpoint, payload, _retried=True)
        raise CronometerError(f"Cronometer API error: {data}")

    return data


def _unit_id(metric: str, unit: str | None) -> int:
    if metric == "heart_rate":
        chosen = (unit or "bpm").strip().lower()
    elif metric == "blood_glucose":
        chosen = (unit or "mg/dL").strip().lower()
    elif metric == "body_fat":
        chosen = (unit or "%").strip().lower()
    else:
        raise ValueError(f"mobile biometric writer does not handle {metric!r}")
    try:
        return _UNIT_IDS[metric][chosen]
    except KeyError as exc:
        allowed = ", ".join(sorted(_UNIT_IDS[metric]))
        raise ValueError(f"{metric} unit must be one of: {allowed}") from exc


def _new_rows(day: date, before_ids: set[str]) -> list[dict]:
    return [
        row
        for row in hybrid._mobile_biometric_rows(day)
        if str(row.get("biometricId")) not in before_ids
    ]


def _rollback(rows: list[dict]) -> None:
    ids = [
        str(row.get("biometricId"))
        for row in rows
        if row.get("biometricId") not in (None, "")
    ]
    if ids:
        hybrid._cleanup_new_biometric_ids(ids)


def _try_mobile_add(
    metric_id: int,
    stored_value: float,
    day: date,
    unit_id: int,
) -> tuple[dict | None, list[str]]:
    """Try conservative mobile biometric payload shapes and verify each one."""
    mobile = core._get_client()
    before_ids = {
        str(row.get("biometricId")) for row in hybrid._mobile_biometric_rows(day)
    }
    biometric = {
        "amount": float(stored_value),
        "biometricId": None,
        "day": mobile._format_day(day),
        "meta": {},
        "metricId": metric_id,
        "order": 65539,
        "samplesVersion": 0,
        "type": "Biometric",
        "unitId": unit_id,
        "userId": mobile.user_id,
    }

    attempts = [
        (
            "/api/v2/add_biometric",
            {"biometric": biometric, "config": {"call_version": 2}},
        ),
        (
            "/api/v2/add_biometric",
            {"data": biometric, "config": {"call_version": 2}},
        ),
        (
            "/api/v2/add_biometric",
            {**biometric, "config": {"call_version": 2}},
        ),
        (
            "/api/v2/add_measurement",
            {"biometric": biometric, "config": {"call_version": 2}},
        ),
    ]
    errors: list[str] = []

    for endpoint, attempt_payload in attempts:
        try:
            response = mobile._request(endpoint, attempt_payload)
        except Exception as exc:
            errors.append(f"{endpoint}: {type(exc).__name__}: {exc}")
            continue

        rows = _new_rows(day, before_ids)
        matches = [row for row in rows if row.get("metricId") == metric_id]
        if matches:
            chosen = matches[-1]
            extras = [row for row in rows if row is not chosen]
            _rollback(extras)
            return chosen, errors

        if rows:
            _rollback(rows)
        errors.append(
            f"{endpoint}: response={response!r}; no verified metric_id={metric_id} row"
        )

    return None, errors


def add_biometric_verified(
    metric_type: str,
    value: float,
    day: date,
    unit: str | None = None,
) -> dict:
    metric, expected_metric_id, stored_value, stored_unit = hybrid._prepare_biometric(
        metric_type, value, unit
    )

    if metric == "weight":
        return _ORIGINAL_ADD(metric_type, value, day, unit)

    unit_id = _unit_id(metric, unit)
    row, errors = _try_mobile_add(expected_metric_id, stored_value, day, unit_id)
    if row is None:
        raise RuntimeError(
            "No verified mobile biometric write path succeeded for "
            f"{metric}; attempts={errors}"
        )

    biometric_id = str(row.get("biometricId"))
    return {
        "biometric_id": biometric_id,
        "transport_id": biometric_id,
        "wire_id": None,
        "metric_type": metric,
        "metric_id": expected_metric_id,
        "input_value": value,
        "input_unit": unit,
        "stored_value": round(float(row.get("amount", stored_value)), 4),
        "stored_unit": stored_unit,
        "unit_id": row.get("unitId"),
        "date": str(day),
        "write_transport": "mobile-rest",
    }


def _raw_mobile_templates() -> list[dict]:
    response = core._get_client().get_macro_target_templates()
    templates = response.get("templates", []) if isinstance(response, dict) else []
    return [item for item in templates if isinstance(item, dict)]


def _template_id(template: dict) -> int | None:
    for key in ("id", "templateId", "template_id"):
        value = template.get(key)
        if isinstance(value, int) and value > 0:
            return value
        if isinstance(value, str) and value.isdigit() and int(value) > 0:
            return int(value)
    return None


def _template_name(template: dict) -> str:
    for key in ("name", "templateName", "template_name"):
        value = template.get(key)
        if isinstance(value, str):
            return value
    return ""


def _number(template: dict, *keys: str) -> float | None:
    for key in keys:
        value = template.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _template_matches(
    template: dict,
    *,
    name: str,
    protein_g: float,
    fat_g: float,
    carbs_g: float,
    calories: float,
) -> bool:
    if _template_name(template) != name:
        return False
    checks = (
        (_number(template, "protein", "protein_g"), protein_g),
        (_number(template, "fat", "fat_g"), fat_g),
        (_number(template, "carbs", "netCarbs", "carbs_g"), carbs_g),
        (_number(template, "energy", "calories", "kcal"), calories),
    )
    for actual, expected in checks:
        if actual is None:
            continue
        if abs(actual - float(expected)) > max(0.05, abs(float(expected)) * 1e-4):
            return False
    return True


def _delete_template_or_raise(web_client, template: dict) -> None:
    template_id = _template_id(template)
    if template_id is None:
        raise RuntimeError(
            "A macro template was created with an unknown ID shape and cannot be "
            f"safely rolled back: {template!r}"
        )
    if not web_client.delete_macro_target_template(template_id):
        raise RuntimeError(f"Could not roll back macro template id={template_id}")


def _save_macro_target_template_mobile(
    web_client,
    template_name: str,
    protein_g: float,
    fat_g: float,
    carbs_g: float,
    calories: float,
) -> int:
    """Create a saved macro template via mobile REST and verify persistence."""
    mobile = core._get_client()
    before = _raw_mobile_templates()
    before_ids = {_template_id(item) for item in before}

    common = {
        "id": 0,
        "name": template_name,
        "protein": float(protein_g),
        "fat": float(fat_g),
        "carbs": float(carbs_g),
        "grams": True,
        "macroChoice": 0,
    }
    energy_template = {**common, "energy": float(calories)}
    calories_template = {**common, "calories": float(calories)}

    attempts = [
        (
            "/api/v2/add_macro_target_template",
            {"template": energy_template, "config": {"call_version": 1}},
        ),
        (
            "/api/v2/add_macro_target_template",
            {"data": energy_template, "config": {"call_version": 1}},
        ),
        (
            "/api/v2/add_macro_target_template",
            {**energy_template, "config": {"call_version": 1}},
        ),
        (
            "/api/v2/save_macro_target_template",
            {"template": energy_template, "config": {"call_version": 1}},
        ),
        (
            "/api/v2/save_macro_target_template",
            {"template": calories_template, "config": {"call_version": 1}},
        ),
        (
            "/api/v2/update_macro_target_template",
            {"template": energy_template, "config": {"call_version": 1}},
        ),
    ]
    errors: list[str] = []

    for endpoint, attempt_payload in attempts:
        try:
            response = mobile._request(endpoint, attempt_payload)
        except Exception as exc:
            errors.append(f"{endpoint}: {type(exc).__name__}: {exc}")
            continue

        after = _raw_mobile_templates()
        new_templates = [
            item
            for item in after
            if _template_id(item) not in before_ids
            or (
                _template_id(item) is None
                and _template_name(item) == template_name
                and item not in before
            )
        ]
        matching = [
            item
            for item in new_templates
            if _template_matches(
                item,
                name=template_name,
                protein_g=protein_g,
                fat_g=fat_g,
                carbs_g=carbs_g,
                calories=calories,
            )
        ]
        if matching:
            chosen = matching[-1]
            extras = [item for item in new_templates if item is not chosen]
            for item in extras:
                _delete_template_or_raise(web_client, item)
            template_id = _template_id(chosen)
            if template_id is None:
                raise RuntimeError(
                    "Macro template persisted but the mobile response did not expose "
                    f"a deletable template ID: {chosen!r}"
                )
            return template_id

        if new_templates:
            for item in new_templates:
                _delete_template_or_raise(web_client, item)
        errors.append(
            f"{endpoint}: response={response!r}; no verified saved template appeared"
        )

    raise RuntimeError(
        f"No verified mobile macro-template write path succeeded; attempts={errors}"
    )


def _patched_get_web_client():
    client = _ORIGINAL_GET_WEB_CLIENT()
    if not getattr(client, "_chatgpt_mobile_template_patch", False):
        client.save_macro_target_template = MethodType(
            _save_macro_target_template_mobile, client
        )
        client._chatgpt_mobile_template_patch = True
    return client


core.CronometerClient._request = _safe_v2_request
hybrid._add_biometric_verified = add_biometric_verified
hybrid._get_web_client = _patched_get_web_client
