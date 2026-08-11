"""Verified GWT create path for saved Cronometer macro templates.

Cronometer's mobile endpoint updates existing templates but does not create new
ones. The pinned web client's saved-template payload is stale, so Cronometer can
return transport success without persisting anything.

This module serializes CREATE using the current 14-field
MacroTargetTemplate/3691130822 layout observed in Cronometer's web bundle, then
accepts success only after the mobile API reads back the exact persisted
name/macros and exposes a real template ID. Unexpected writes are rolled back.
Cronometer's current web client gates creation of saved macro templates behind
its Gold Macro Scheduler entitlement, so a transport-level //OK without a
persisted template is reported as an entitlement-aware failure rather than a
false success.
"""

from __future__ import annotations

from types import MethodType

from . import hybrid_tools as hybrid
from . import mobile_write_fixes as mobile_fixes

_BASE_GET_WEB_CLIENT = hybrid._get_web_client


def _fmt(value: float) -> str:
    return str(int(value)) if value == int(value) else str(value)


def _new_templates(before: list[dict], after: list[dict], name: str) -> list[dict]:
    before_ids = {
        template_id
        for item in before
        if (template_id := mobile_fixes._template_id(item)) is not None
    }
    return [
        item
        for item in after
        if (
            (template_id := mobile_fixes._template_id(item)) is not None
            and template_id not in before_ids
        )
        or (
            template_id is None
            and mobile_fixes._template_name(item) == name
            and item not in before
        )
    ]


def _strict_template_matches(
    template: dict,
    *,
    name: str,
    protein_g: float,
    fat_g: float,
    carbs_g: float,
    calories: float,
) -> bool:
    if mobile_fixes._template_name(template) != name:
        return False

    pairs = (
        (mobile_fixes._number(template, "protein", "protein_g"), protein_g),
        (mobile_fixes._number(template, "fat", "fat_g"), fat_g),
        (
            mobile_fixes._number(template, "carbs", "netCarbs", "carbs_g"),
            carbs_g,
        ),
        (
            mobile_fixes._number(template, "energy", "calories", "kcal"),
            calories,
        ),
    )
    if any(actual is None for actual, _expected in pairs):
        return False
    return all(
        abs(float(actual) - float(expected)) <= max(0.05, abs(float(expected)) * 1e-4)
        for actual, expected in pairs
    )


def _rollback_templates(web_client, templates: list[dict]) -> None:
    for template in templates:
        mobile_fixes._delete_template_or_raise(web_client, template)


def _build_create_body(
    web_client,
    template_name: str,
    protein_g: float,
    fat_g: float,
    carbs_g: float,
    calories: float,
) -> str:
    """Build the current saved-template CREATE payload.

    The current MacroTargetTemplate writer serializes fields in this order:
      a, b, c, d, e, f, g, i, j, k, n, o, p, q

    For a new fixed-macro template the web UI constructs them as:
      null, carbs, null, null, calories, fat, null, true,
      Integer(0), null, 0.0, template_name, protein, null.

    All boxed macro values are emitted explicitly instead of relying on GWT
    object back-references. This keeps the payload deterministic when two macro
    values happen to be equal.
    """
    carbs_str = _fmt(carbs_g)
    fat_str = _fmt(fat_g)
    calories_str = _fmt(calories)
    protein_str = _fmt(protein_g)

    # String table (1-indexed):
    # 1 module, 2 strong-name, 3 service, 4 method, 5 String type, 6 I,
    # 7 MacroTargetTemplate type, 8 nonce, 9 Double type, 10 Integer type,
    # 11 template name.
    header = (
        "7|0|11|https://cronometer.com/cronometer/|"
        f"{web_client.gwt_header}|"
        "com.cronometer.shared.rpc.CronometerService|"
        "saveMacroTargetTemplate|java.lang.String/2004016611|"
        "I|com.cronometer.shared.targets.models.MacroTargetTemplate/"
        "3691130822|"
        f"{web_client.nonce or ''}|"
        "java.lang.Double/858496421|"
        "java.lang.Integer/3438268394|"
        f"{template_name}|"
        "1|2|3|4|3|5|6|7|"
    )

    data = (
        f"8|{web_client.user_id}|"
        "7|"
        "0|"
        f"9|{carbs_str}|"
        "0|"
        "0|"
        f"9|{calories_str}|"
        f"9|{fat_str}|"
        "0|"
        "1|"
        "10|0|"
        "0|"
        "0|"
        "11|"
        f"9|{protein_str}|"
        "0|"
    )
    return header + data


def save_macro_target_template_gwt_verified(
    web_client,
    template_name: str,
    protein_g: float,
    fat_g: float,
    carbs_g: float,
    calories: float,
) -> int:
    """Create one template through GWT and verify it through mobile REST."""
    if not template_name or not template_name.strip():
        raise ValueError("template_name cannot be empty")
    if "|" in template_name:
        raise ValueError("template_name cannot contain '|'")
    if min(protein_g, fat_g, carbs_g, calories) < 0:
        raise ValueError("macro targets cannot be negative")

    web_client.authenticate()
    before = mobile_fixes._raw_mobile_templates()
    body = _build_create_body(
        web_client,
        template_name,
        protein_g,
        fat_g,
        carbs_g,
        calories,
    )
    raw = web_client._gwt_post(body)
    if "//OK" not in raw:
        raise RuntimeError(f"saveMacroTargetTemplate failed: {raw[:300]}")

    after = mobile_fixes._raw_mobile_templates()
    created = _new_templates(before, after, template_name)
    matching = [
        item
        for item in created
        if _strict_template_matches(
            item,
            name=template_name,
            protein_g=protein_g,
            fat_g=fat_g,
            carbs_g=carbs_g,
            calories=calories,
        )
    ]

    if not matching:
        if created:
            _rollback_templates(web_client, created)
        raise RuntimeError(
            "Cronometer returned //OK but did not persist the saved macro template. "
            "The current Cronometer web client and official product documentation "
            "gate saved Macro Scheduler templates behind a Gold subscription. "
            "If this account does not have an active Gold entitlement, template "
            "creation is unavailable. Any detected partial write was rolled back."
        )

    chosen = matching[-1]
    extras = [item for item in created if item is not chosen]
    if extras:
        _rollback_templates(web_client, extras)

    template_id = mobile_fixes._template_id(chosen)
    if template_id is None:
        _rollback_templates(web_client, [chosen])
        raise RuntimeError(
            "Macro template persisted but mobile REST did not expose a deletable ID; "
            "the new template was rolled back"
        )
    return template_id


def _patched_get_web_client():
    client = _BASE_GET_WEB_CLIENT()
    if not getattr(client, "_chatgpt_gwt_template_create_patch", False):
        client.save_macro_target_template = MethodType(
            save_macro_target_template_gwt_verified, client
        )
        client._chatgpt_gwt_template_create_patch = True
    return client


hybrid._get_web_client = _patched_get_web_client
