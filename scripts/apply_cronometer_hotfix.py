#!/usr/bin/env python3
"""Patch the pinned third-party cronometer-mcp client for live API regressions.

Our own MCP source is fixed normally in this repository.  This script only
patches cronometer-mcp==2.0.3 after installation, because those fixes cannot be
committed into that external package from this repository.
"""

from __future__ import annotations

import inspect
from pathlib import Path

STAMP = "cronometer-hotfix-20260811-v2"


def patch_web_client(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    original = text
    changes: list[str] = []

    # requests guesses CSV encoding from headers; Cronometer exports are UTF-8
    # and may contain Cyrillic/Turkish text.  Decode bytes explicitly.
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

    # addBiometric may return a quoted GWT-long token (alphabet includes $/_)
    # or, on newer responses, a bare decimal ID.  Capture only the first value.
    if "quoted GWT-long token or a bare decimal ID" not in text:
        old = """        # Extract biometric ID from response: //OK["BXW0DA",[],0,7]\n        biometric_id = ""\n        if raw.startswith("//OK["):\n            import re\n            match = re.search(r'"([A-Za-z0-9]+)"', raw)\n            if match:\n                biometric_id = match.group(1)\n"""
        new = """        # Cronometer can return a quoted GWT-long token or a bare decimal ID.\n        biometric_id = ""\n        if raw.startswith("//OK["):\n            match = re.search(\n                r'^//OK\\[\\s*(?:"([^"\\r\\n]+)"|([1-9][0-9]{5,}))', raw\n            )\n            if match:\n                biometric_id = match.group(1) or match.group(2) or ""\n"""
        if old not in text:
            raise RuntimeError("add_biometric ID patch target not found")
        text = text.replace(old, new, 1)
        changes.append("addBiometric response ID parsing")

    # A transport-level //OK is not proof a macro template was persisted.
    if "saveMacroTargetTemplate was not verified" not in text:
        old = """        # Template was created but not found — return 0 as fallback\n        logger.warning(\n            "Template '%s' created but not found in template list",\n            template_name,\n        )\n        return 0\n"""
        new = """        raise RuntimeError(\n            f"saveMacroTargetTemplate was not verified: template {template_name!r} "\n            "is absent from getMacroTargetTemplates after the write"\n        )\n"""
        if old not in text:
            raise RuntimeError("macro template verification patch target not found")
        text = text.replace(old, new, 1)
        changes.append("macro template false-success rejection")

    # Cronometer sometimes returns "Success" even though target values did not
    # stick.  Verify exact effective values before reporting success.
    if "Updated and verified daily targets" not in text:
        old = """        if "Success" in raw:\n            logger.info(\n                "Updated daily targets for %s: protein=%.1fg, fat=%.1fg, "\n                "carbs=%.1fg, calories=%.0f",\n                day, protein_g, fat_g, carbs_g, calories,\n            )\n            return True\n"""
        new = """        if "Success" in raw:\n            verified = self.get_daily_macro_targets(day) or {}\n            expected = {\n                "protein_g": float(protein_g),\n                "fat_g": float(fat_g),\n                "carbs_g": float(carbs_g),\n                "calories": float(calories),\n            }\n            mismatches = {}\n            for key, wanted in expected.items():\n                got = verified.get(key)\n                try:\n                    ok = got is not None and abs(float(got) - wanted) <= max(0.05, abs(wanted) * 1e-4)\n                except (TypeError, ValueError):\n                    ok = False\n                if not ok:\n                    mismatches[key] = {"expected": wanted, "actual": got}\n            if mismatches:\n                raise RuntimeError(\n                    "updateDailyTargetTemplate returned Success but the write did not persist; "\n                    f"mismatches={mismatches}"\n                )\n            logger.info(\n                "Updated and verified daily targets for %s: protein=%.1fg, fat=%.1fg, "\n                "carbs=%.1fg, calories=%.0f",\n                day, protein_g, fat_g, carbs_g, calories,\n            )\n            return True\n"""
        if old not in text:
            raise RuntimeError("daily macro target verification patch target not found")
        text = text.replace(old, new, 1)
        changes.append("macro target read-after-write verification")

    if text != original:
        path.write_text(text, encoding="utf-8")
    return changes


def main() -> int:
    try:
        from cronometer_mcp import client as web_client_module
    except ImportError as exc:
        raise RuntimeError(
            "cronometer-mcp must be installed before applying the hotfix"
        ) from exc

    path = Path(
        inspect.getsourcefile(web_client_module) or web_client_module.__file__
    ).resolve()
    changes = patch_web_client(path)
    print(STAMP)
    print(path)
    for change in changes:
        print(f"  + {change}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
