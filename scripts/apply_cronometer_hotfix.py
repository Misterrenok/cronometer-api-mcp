#!/usr/bin/env python3
"""Apply Cronometer 2026-08-11 compatibility fixes during the image build.

The project intentionally keeps cphoskins/cronometer-mcp as an installed
runtime dependency.  Cronometer changed a few undocumented web/GWT response
shapes, so patch the pinned dependency and the two hybrid MCP wrappers after
installation.  The patch is idempotent and fails the Docker build if an
expected target cannot be found, preventing a silently half-patched deploy.
"""
from __future__ import annotations

import ast
import inspect
import re
import sys
import textwrap
from pathlib import Path

STAMP = "cronometer-hotfix-20260811"


def replace_function(text: str, name: str, source: str) -> tuple[str, bool]:
    tree = ast.parse(text)
    node = next(
        (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name),
        None,
    )
    if node is None or node.end_lineno is None:
        return text, False
    lines = text.splitlines(keepends=True)
    indent = " " * node.col_offset
    normalized = textwrap.dedent(source).rstrip() + "\n"
    replacement = "".join(
        indent + line if line.strip() else line
        for line in normalized.splitlines(keepends=True)
    )
    return "".join(lines[: node.lineno - 1]) + replacement + "".join(lines[node.end_lineno :]), True


def patch_web_client(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    original = text
    changes: list[str] = []

    if "raw_bytes = resp.content" not in text:
        old = "        return resp.text\n"
        new = (
            "        raw_bytes = resp.content\n"
            "        if raw_bytes.startswith(b'\\xef\\xbb\\xbf'):\n"
            "            return raw_bytes.decode('utf-8-sig')\n"
            "        try:\n"
            "            return raw_bytes.decode('utf-8')\n"
            "        except UnicodeDecodeError:\n"
            "            return raw_bytes.decode(resp.encoding or 'utf-8', errors='replace')\n"
        )
        if old not in text:
            raise RuntimeError("export_raw UTF-8 patch target not found")
        text = text.replace(old, new, 1)
        changes.append("CSV explicit UTF-8 decoding")

    old_bio = '''        # Extract biometric ID from response: //OK["BXW0DA",[],0,7]\n        biometric_id = ""\n        if raw.startswith("//OK["):\n            import re\n            match = re.search(r'"([A-Za-z0-9]+)"', raw)\n            if match:\n                biometric_id = match.group(1)\n'''
    new_bio = '''        # Cronometer can return either the legacy quoted ID or a bare numeric ID.\n        # Only accept the first response value so unrelated GWT integers are ignored.\n        biometric_id = ""\n        if raw.startswith("//OK["):\n            match = re.search(\n                r'^//OK\\[\\s*(?:"([A-Za-z0-9]+)"|([1-9][0-9]{5,}))', raw\n            )\n            if match:\n                biometric_id = match.group(1) or match.group(2) or ""\n'''
    if "bare numeric ID" not in text:
        if old_bio not in text:
            raise RuntimeError("add_biometric ID patch target not found")
        text = text.replace(old_bio, new_bio, 1)
        changes.append("addBiometric numeric ID parsing")

    old_template = '''        # Template was created but not found — return 0 as fallback\n        logger.warning(\n            "Template '%s' created but not found in template list",\n            template_name,\n        )\n        return 0\n'''
    new_template = '''        # A //OK transport response is not proof that Cronometer persisted the template.\n        raise RuntimeError(\n            f"saveMacroTargetTemplate was not verified: template {template_name!r} "\n            "is absent from getMacroTargetTemplates after the write"\n        )\n'''
    if "A //OK transport response is not proof" not in text:
        if old_template not in text:
            raise RuntimeError("macro template verification patch target not found")
        text = text.replace(old_template, new_template, 1)
        changes.append("macro template false-success rejection")

    old_targets = '''        if "Success" in raw:\n            logger.info(\n                "Updated daily targets for %s: protein=%.1fg, fat=%.1fg, "\n                "carbs=%.1fg, calories=%.0f",\n                day, protein_g, fat_g, carbs_g, calories,\n            )\n            return True\n'''
    new_targets = '''        if "Success" in raw:\n            verified = self.get_daily_macro_targets(day) or {}\n            expected = {\n                "protein_g": float(protein_g),\n                "fat_g": float(fat_g),\n                "carbs_g": float(carbs_g),\n                "calories": float(calories),\n            }\n            mismatches = {}\n            for key, wanted in expected.items():\n                got = verified.get(key)\n                try:\n                    ok = got is not None and abs(float(got) - wanted) <= max(0.05, abs(wanted) * 1e-4)\n                except (TypeError, ValueError):\n                    ok = False\n                if not ok:\n                    mismatches[key] = {"expected": wanted, "actual": got}\n            if mismatches:\n                raise RuntimeError(\n                    "updateDailyTargetTemplate returned Success but the write did not persist; "\n                    f"mismatches={mismatches}"\n                )\n            logger.info(\n                "Updated and verified daily targets for %s: protein=%.1fg, fat=%.1fg, "\n                "carbs=%.1fg, calories=%.0f",\n                day, protein_g, fat_g, carbs_g, calories,\n            )\n            return True\n'''
    if "Updated and verified daily targets" not in text:
        if old_targets not in text:
            raise RuntimeError("daily macro target verification patch target not found")
        text = text.replace(old_targets, new_targets, 1)
        changes.append("macro target read-after-write verification")

    if text != original:
        path.write_text(text, encoding="utf-8")
    return changes


GET_RECENT = r'''
def get_recent_biometrics() -> str:
    """Get recent biometric entries with IDs verified from the mobile diary."""
    try:
        mobile = core._get_client()
        web = _get_web_client()
        web_rows = web.get_recent_biometrics() or []
        web_by_id = {
            str(row.get("biometric_id")): row
            for row in web_rows
            if isinstance(row, dict) and row.get("biometric_id") not in (None, "")
        }
        records = {}
        today = mobile.today()
        for offset in range(31):
            day = today - timedelta(days=offset)
            try:
                diary = mobile.get_diary(day) or {}
            except Exception:
                continue
            for row in diary.get("diary") or []:
                if not isinstance(row, dict) or row.get("type") != "Biometric":
                    continue
                raw_id = row.get("biometricId")
                if raw_id in (None, ""):
                    continue
                bid = str(raw_id)
                item = {
                    "biometric_id": bid,
                    "value": row.get("amount", row.get("value")),
                    "metric_id": row.get("metricId", 0),
                    "unit_id": row.get("unitId"),
                    "date": str(row.get("day") or day),
                }
                extra = web_by_id.get(bid)
                if isinstance(extra, dict):
                    for key in ("composite", "metric_name"):
                        if extra.get(key) not in (None, ""):
                            item[key] = extra[key]
                records[bid] = item
        for row in web_rows:
            if not isinstance(row, dict):
                continue
            bid = str(row.get("biometric_id") or "")
            if bid and bid not in records:
                normalized = dict(row)
                normalized["biometric_id"] = bid
                records[bid] = normalized
        items = sorted(records.values(), key=lambda row: str(row.get("date") or ""), reverse=True)
        return core._ok({"count": len(items), "biometrics": items, "backend": "mobile-diary+web-gwt"})
    except Exception as e:
        return core._err(e)
'''


ADD_BIOMETRIC = r'''
def add_biometric(
    metric_type: str,
    value: float,
    date: str | None = None,
    unit: str | None = None,
) -> str:
    """Log a supported biometric and return the ID verified from mobile diary."""
    try:
        metric = str(metric_type).strip().lower()
        metric_ids = {"weight": 1, "heart_rate": 3, "blood_glucose": 6, "body_fat": 8}
        if metric not in metric_ids:
            raise ValueError("metric_type must be one of: body_fat, blood_glucose, heart_rate, weight")
        day = _date(date)
        mobile = core._get_client()
        web = _get_web_client()
        before = mobile.get_diary(day) or {}
        before_ids = {
            str(row.get("biometricId"))
            for row in before.get("diary") or []
            if isinstance(row, dict) and row.get("type") == "Biometric" and row.get("biometricId") not in (None, "")
        }
        stored_value = float(value)
        stored_unit = unit
        if metric == "weight":
            chosen = (unit or "kg").strip().lower()
            if chosen in ("kg", "kilogram", "kilograms"):
                stored_value *= 2.2046226218
                stored_unit = "lbs"
            elif chosen in ("lb", "lbs", "pound", "pounds"):
                stored_unit = "lbs"
            else:
                raise ValueError("weight unit must be kg or lbs")
        elif metric == "blood_glucose":
            stored_unit = unit or "mg/dL"
        elif metric == "heart_rate":
            stored_unit = unit or "bpm"
        else:
            stored_unit = unit or "%"
        transport_id = str(web.add_biometric(metric, stored_value, day) or "")
        verified_id = ""
        after = mobile.get_diary(day) or {}
        candidates = [
            row for row in after.get("diary") or []
            if isinstance(row, dict) and row.get("type") == "Biometric"
            and row.get("biometricId") not in (None, "")
            and str(row.get("biometricId")) not in before_ids
        ]
        preferred = [row for row in candidates if row.get("metricId") == metric_ids[metric]]
        chosen_row = (preferred or candidates)[0] if (preferred or candidates) else None
        if chosen_row is not None:
            verified_id = str(chosen_row.get("biometricId") or "")
        if not verified_id:
            verified_id = transport_id
        if not verified_id:
            raise RuntimeError("Biometric write was accepted but no new biometricId could be verified")
        return core._ok({
            "biometric_id": verified_id,
            "transport_biometric_id": transport_id or None,
            "metric_type": metric,
            "metric_id": metric_ids[metric],
            "input_value": value,
            "input_unit": unit,
            "stored_value": round(stored_value, 4),
            "stored_unit": stored_unit,
            "date": str(day),
            "backend": "web-gwt+mobile-verify",
        })
    except Exception as e:
        return core._err(e)
'''


UPDATE_BIOMETRIC = r'''
def update_biometric(
    biometric_id: str,
    metric_type: str,
    value: float,
    date: str | None = None,
    unit: str | None = None,
) -> str:
    """Replace a biometric safely, verifying the replacement ID before deletion."""
    try:
        source_id = str(biometric_id).strip()
        if not source_id:
            raise ValueError("biometric_id cannot be empty")
        metric = metric_type.strip().lower()
        stored_value, stored_unit = _prepare_value(metric, float(value), unit)
        target_date = hybrid._date(date)
        mobile = core._get_client()
        web = hybrid._get_web_client()
        source = None
        today = mobile.today()
        for offset in range(31):
            day = today - __import__("datetime").timedelta(days=offset)
            diary = mobile.get_diary(day) or {}
            for row in diary.get("diary") or []:
                if isinstance(row, dict) and row.get("type") == "Biometric" and str(row.get("biometricId") or "") == source_id:
                    source = row
                    break
            if source is not None:
                break
        if source is None:
            raise ValueError(f"biometric_id {source_id!r} was not found in recent mobile diary biometrics")
        before = mobile.get_diary(target_date) or {}
        before_ids = {
            str(row.get("biometricId")) for row in before.get("diary") or []
            if isinstance(row, dict) and row.get("type") == "Biometric" and row.get("biometricId") not in (None, "")
        }
        transport_id = str(web.add_biometric(metric, stored_value, target_date) or "")
        after = mobile.get_diary(target_date) or {}
        candidates = [
            row for row in after.get("diary") or []
            if isinstance(row, dict) and row.get("type") == "Biometric"
            and row.get("biometricId") not in (None, "")
            and str(row.get("biometricId")) not in before_ids
        ]
        replacement_id = str(candidates[0].get("biometricId")) if candidates else transport_id
        if not replacement_id:
            raise RuntimeError("Replacement biometric was not verified; source was not deleted")
        try:
            deleted = web.remove_biometric(source_id)
        except Exception as exc:
            return json.dumps({
                "status": "partial",
                "message": "Replacement was created but deleting the source raised an error.",
                "source_biometric_id": source_id,
                "replacement_biometric_id": replacement_id,
                "delete_error": f"{type(exc).__name__}: {exc}",
                "backend": "web-gwt+mobile-verify",
            }, indent=2)
        if not deleted:
            return json.dumps({
                "status": "partial",
                "message": "Replacement was created but source deletion was not confirmed.",
                "source_biometric_id": source_id,
                "replacement_biometric_id": replacement_id,
                "backend": "web-gwt+mobile-verify",
            }, indent=2)
        return core._ok({
            "updated": True,
            "source_biometric_id": source_id,
            "replacement_biometric_id": replacement_id,
            "transport_biometric_id": transport_id or None,
            "metric_type": metric,
            "input_value": value,
            "input_unit": unit,
            "stored_value": round(stored_value, 4),
            "stored_unit": stored_unit,
            "date": str(target_date),
            "backend": "web-gwt+mobile-verify",
        })
    except Exception as e:
        return core._err(e)
'''


def patch_hybrid(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    changes: list[str] = []
    if "from datetime import date" in text and "timedelta" not in text.split("from datetime import date", 1)[1].splitlines()[0]:
        text = text.replace("from datetime import date\n", "from datetime import date, timedelta\n", 1)
        changes.append("hybrid timedelta import")
    text, ok = replace_function(text, "get_recent_biometrics", GET_RECENT)
    if not ok:
        raise RuntimeError("hybrid get_recent_biometrics not found")
    changes.append("recent biometric IDs from mobile diary")
    text, ok = replace_function(text, "add_biometric", ADD_BIOMETRIC)
    if not ok:
        raise RuntimeError("hybrid add_biometric not found")
    changes.append("biometric add read-after-write verification")
    path.write_text(text, encoding="utf-8")
    return changes


def patch_biometric_control(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    old = '''def _bio_id(entry: dict) -> str | None:\n    value = entry.get("biometric_id")\n    return value if isinstance(value, str) and value else None\n'''
    new = '''def _bio_id(entry: dict) -> str | None:\n    value = entry.get("biometric_id", entry.get("biometricId"))\n    return str(value) if value not in (None, "") else None\n'''
    if old in text:
        text = text.replace(old, new, 1)
    text, ok = replace_function(text, "update_biometric", UPDATE_BIOMETRIC)
    if not ok:
        raise RuntimeError("biometric_control update_biometric not found")
    path.write_text(text, encoding="utf-8")
    return ["numeric biometric ID normalization", "safe verified biometric update"]


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    try:
        from cronometer_mcp import client as web_client_module
    except ImportError as exc:
        raise RuntimeError("cronometer-mcp must be installed before applying the hotfix") from exc
    web_path = Path(inspect.getsourcefile(web_client_module) or web_client_module.__file__).resolve()
    hybrid_path = root / "src/cronometer_api_mcp/hybrid_tools.py"
    controls_path = root / "src/cronometer_api_mcp/biometric_control_tools.py"
    report = {
        web_path: patch_web_client(web_path),
        hybrid_path: patch_hybrid(hybrid_path),
        controls_path: patch_biometric_control(controls_path),
    }
    print(STAMP)
    for path, changes in report.items():
        print(path)
        for change in changes:
            print(f"  + {change}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
