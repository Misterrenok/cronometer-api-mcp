"""Verified GWT create path for saved Cronometer macro templates.

Cronometer's mobile endpoint updates existing templates but does not create new
ones.  The pinned web client still calls the correct GWT RPC method, but its
MacroTargetTemplate field order is stale: it writes string-table indexes into
two primitive integer fields and leaves the real name field null.

This module uses the current 14-field serializer layout for CREATE only, then
accepts success only after the mobile API reads back the exact persisted
name/macros and exposes a real template ID.  Unexpected writes are rolled back.
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
        abs(float(actual) - float(expected))
        <= max(0.05, abs(float(expected)) * 1e-4)
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
    """Build the current MacroTargetTemplate/3691130822 CREATE payload.

    Current serializer fields 9..14 are:
      Integer object, primitive int, String name, primitive int,
      Double protein, Double trailing target.

    Both primitive ints are zero for a new/custom template.  The old client
    incorrectly encoded ``Rigorous`` into the first int and ``template_name``
    into the second int, leaving the actual String field null.
    """
    carbs_str = _fmt(carbs_g)
    fat_str = _fmt(fat_g)
    calories_str = _fmt(calories)
    protein_str = _fmt(protein_g)

    # String table (1-indexed):
    # 1 module, 2 strong-name, 3 service, 4 method, 5 String type, 6 I,
    # 7 MacroTargetTemplate type, 8 nonce, 9 Boolean type, 10 Double type,
    # 11 Integer type, 12 template name.
    header = (
        "7|0|12|https://cronometer.com/cronometer/|"
        f"{web_client.gwt_header}|"
        "com.cronometer.shared.rpc.CronometerService|"
        "saveMacroTargetTemplate|java.lang.String/2004016611|"
        "I|com.cronometer.shared.targets.models.MacroTargetTemplate/"
        "3691130822|"
        f"{web_client.nonce or ''}|"
        "java.lang.Boolean/476441737|"
        "java.lang.Double/858496421|"
        "java.lang.Integer/3438268394|"
        f"{template_name}|"
        "1|2|3|4|3|5|6|7|"
    )

    if fat_g == carbs_g:
        data = (
            f"8|{web_client.user_id}|"
            f"7|9|0|10|{carbs_str}|-3|0|10|{calories_str}|-3|-3|0|"
            f"11|0|0|12|0|10|{protein_str}|-6|"
        )
    else:
        data = (
            f"8|{web_client.user_id}|"
            f"7|9|0|10|{carbs_str}|10|{fat_str}|0|10|{calories_str}|"
            f"10|{fat_str}|10|{fat_str}|0|"
            f"11|0|0|12|0|10|{protein_str}|10|{calories_str}|"
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
            "saveMacroTargetTemplate returned //OK but no exact persisted template "
            "was visible through mobile REST; any detected new template was rolled back"
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
