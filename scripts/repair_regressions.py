#!/usr/bin/env python3
"""One-shot repair: narrow macro-template mobile payloads to the known endpoint."""

from pathlib import Path

PATH = Path("src/cronometer_api_mcp/mobile_write_fixes.py")

OLD = """    common = {
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
        (
            "/api/v2/update_macro_target_template",
            {"macroTargetTemplate": energy_template, "config": {"call_version": 1}},
        ),
        (
            "/api/v2/update_macro_target_template",
            {"macro_target_template": energy_template, "config": {"call_version": 1}},
        ),
        (
            "/api/v2/update_macro_target_template",
            {"targetTemplate": energy_template, "config": {"call_version": 1}},
        ),
        (
            "/api/v2/update_macro_target_template",
            {"target": energy_template, "config": {"call_version": 1}},
        ),
    ]
"""

NEW = """    # The mobile handler is confirmed to require the top-level key
    # ``template``.  The account's active diary template has no ID field, so
    # try that exact shape first; ID variants follow only to identify the
    # server's create/update semantics.
    common = {
        "name": template_name,
        "protein": float(protein_g),
        "fat": float(fat_g),
        "carbs": float(carbs_g),
        "grams": True,
        "macroChoice": 0,
    }
    energy_template = {**common, "energy": float(calories)}
    calories_template = {**common, "calories": float(calories)}
    id_zero_template = {**energy_template, "id": 0}
    template_id_zero = {**energy_template, "templateId": 0}
    id_null_template = {**energy_template, "id": None}
    template_id_null = {**energy_template, "templateId": None}

    attempts = [
        (
            "/api/v2/update_macro_target_template",
            {"template": energy_template, "config": {"call_version": 1}},
        ),
        (
            "/api/v2/update_macro_target_template",
            {"template": energy_template, "config": {"call_version": 2}},
        ),
        (
            "/api/v2/update_macro_target_template",
            {"template": calories_template, "config": {"call_version": 1}},
        ),
        (
            "/api/v2/update_macro_target_template",
            {"template": template_id_zero, "config": {"call_version": 1}},
        ),
        (
            "/api/v2/update_macro_target_template",
            {"template": id_zero_template, "config": {"call_version": 1}},
        ),
        (
            "/api/v2/update_macro_target_template",
            {"template": template_id_null, "config": {"call_version": 1}},
        ),
        (
            "/api/v2/update_macro_target_template",
            {"template": id_null_template, "config": {"call_version": 1}},
        ),
    ]
"""


def main() -> None:
    text = PATH.read_text(encoding="utf-8")
    if NEW in text:
        return
    if OLD not in text:
        raise RuntimeError("macro payload block changed; refusing blind patch")
    PATH.write_text(text.replace(OLD, NEW, 1), encoding="utf-8")


if __name__ == "__main__":
    main()
