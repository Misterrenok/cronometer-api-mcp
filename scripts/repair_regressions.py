#!/usr/bin/env python3
"""Apply small compatibility repairs to the repository source and tests."""

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"repair target not found in {path}: {old!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    replace_once(
        "src/cronometer_api_mcp/server.py",
        '    return json.dumps({"status": "error", "message": msg})\n',
        '    return json.dumps({"status": "error", "message": msg, "error": msg})\n',
    )
    replace_once(
        "src/cronometer_api_mcp/mobile_write_fixes.py",
        "    response_text = response.text\n",
        '    response_text = getattr(response, "text", "")\n',
    )
    replace_once(
        "tests/test_client.py",
        """def test_failure_variant_still_retries(tmp_path):\n    \"\"\"HTTP 200 + result:\"FAILURE\" retains the original retry behavior.\"\"\"\n    client, state = make_client(\n        tmp_path, [SYNTHETIC_FAILURE_BODY, {\"result\": \"SUCCESS\", \"id\": 1}]\n    )\n\n    result = client._request(\"/api/v2/get_diary\", {})\n\n    assert result == {\"result\": \"SUCCESS\", \"id\": 1}\n    assert state[\"login\"] == 1\n    assert state[\"post\"] == 2\n""",
        """def test_functional_failure_variant_does_not_relogin(tmp_path):\n    \"\"\"A non-auth FAILURE is surfaced without destroying a valid session.\"\"\"\n    client, state = make_client(tmp_path, [SYNTHETIC_FAILURE_BODY])\n\n    with pytest.raises(CronometerError, match=\"synthetic\"):\n        client._request(\"/api/v2/get_diary\", {})\n\n    assert state[\"login\"] == 0\n    assert state[\"post\"] == 1\n""",
    )
    replace_once(
        "src/cronometer_api_mcp/mobile_write_fixes.py",
        '''        (\n            "/api/v2/update_macro_target_template",\n            {"template": energy_template, "config": {"call_version": 1}},\n        ),\n''',
        '''        (\n            "/api/v2/update_macro_target_template",\n            {"template": energy_template, "config": {"call_version": 1}},\n        ),\n        (\n            "/api/v2/update_macro_target_template",\n            {"macroTargetTemplate": energy_template, "config": {"call_version": 1}},\n        ),\n        (\n            "/api/v2/update_macro_target_template",\n            {"macro_target_template": energy_template, "config": {"call_version": 1}},\n        ),\n        (\n            "/api/v2/update_macro_target_template",\n            {"targetTemplate": energy_template, "config": {"call_version": 1}},\n        ),\n        (\n            "/api/v2/update_macro_target_template",\n            {"target": energy_template, "config": {"call_version": 1}},\n        ),\n''',
    )
    replace_once(
        "scripts/live_mcp_probe.py",
        '''                today = account["today"]\n\n                targets = await call(session, "get_macro_targets", {"date": today})\n''',
        '''                today = account["today"]\n\n                # Remove only the exact temporary record left by a prior aborted probe.\n                recent = await call(session, "get_recent_biometrics")\n                if any(\n                    str(item.get("biometric_id")) == "1754710557"\n                    for item in recent.get("biometrics", [])\n                    if isinstance(item, dict)\n                ):\n                    await call(\n                        session,\n                        "remove_biometric",\n                        {"biometric_id": "1754710557"},\n                    )\n\n                targets = await call(session, "get_macro_targets", {"date": today})\n''',
    )
    replace_once(
        "scripts/live_mcp_probe.py",
        '''                results = [await temporary_macro_template(session)]\n                results.append(\n''',
        '''                results = [await temporary_macro_template(session)]\n\n                # Restore the exact pre-probe daily targets even if a candidate\n                # macro-template endpoint unexpectedly touched today's template.\n                await call(\n                    session,\n                    "set_macro_targets",\n                    {\n                        "target_date": today,\n                        "protein_g": daily.get("protein_g"),\n                        "fat_g": daily.get("fat_g"),\n                        "carbs_g": daily.get("carbs_g"),\n                        "calories": daily.get("energy_kcal"),\n                        "template_name": "Custom Targets",\n                    },\n                )\n\n                results.append(\n''',
    )


if __name__ == "__main__":
    main()
