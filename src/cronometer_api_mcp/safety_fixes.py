"""Read-back verification for Cronometer web writes that can return false success.

Cronometer's GWT transport often returns ``//OK`` even when a requested object
ID does not exist or a write was not persisted.  These wrappers only accept a
write as successful after reading the authoritative state back.  Daily macro
targets are verified through the mobile diary summary because that is the
actual target Cronometer applies for the requested date.
"""

from __future__ import annotations

from types import MethodType

from . import hybrid_tools as hybrid
from . import mobile_write_fixes as mobile_fixes
from . import server as core

_BASE_GET_WEB_CLIENT = hybrid._get_web_client


def _close(actual: object, expected: float) -> bool:
    return isinstance(actual, (int, float)) and abs(float(actual) - float(expected)) <= max(
        0.05, abs(float(expected)) * 1e-4
    )


def _effective_daily_targets(day) -> dict:
    diary = core._get_client().get_diary(day)
    summary = (diary or {}).get("summary") or {}
    raw = summary.get("macros") or {}
    if not isinstance(raw, dict):
        raw = {}

    def pick(*keys: str):
        for key in keys:
            value = raw.get(key)
            if isinstance(value, (int, float)):
                return float(value)
        return None

    values = {
        "protein_g": pick("protein", "protein_g"),
        "fat_g": pick("fat", "fat_g"),
        "carbs_g": pick("net_carbs", "netCarbs", "carbs", "carbohydrates"),
        "calories": pick("energy", "calories", "kcal"),
    }
    missing = [key for key, value in values.items() if value is None]
    if missing:
        raise RuntimeError(
            "Cronometer diary did not expose effective macro targets for: "
            + ", ".join(missing)
        )
    return values


def _find_template(template_id: int) -> dict | None:
    for item in mobile_fixes._raw_mobile_templates():
        if mobile_fixes._template_id(item) == template_id:
            return item
    return None


def _find_fast(client, fast_id: int) -> dict | None:
    for item in client.get_user_fasts():
        if not isinstance(item, dict):
            continue
        value = item.get("fast_id")
        try:
            if int(value) == int(fast_id):
                return item
        except (TypeError, ValueError):
            continue
    return None


def _patched_get_web_client():
    client = _BASE_GET_WEB_CLIENT()
    if getattr(client, "_chatgpt_verified_write_patch", False):
        return client

    original_get_daily = client.get_daily_macro_targets
    original_update_daily = client.update_daily_targets
    original_delete_template = client.delete_macro_target_template
    original_save_schedule = client.save_macro_schedule
    original_delete_fast = client.delete_fast
    original_cancel_fast = client.cancel_fast_keep_series

    def get_daily_macro_targets_verified(self, day=None):
        target_day = day or core._get_client().today()
        return _effective_daily_targets(target_day)

    def update_daily_targets_verified(
        self,
        day,
        template_name,
        protein_g,
        fat_g,
        carbs_g,
        calories,
    ):
        expected = {
            "protein_g": float(protein_g),
            "fat_g": float(fat_g),
            "carbs_g": float(carbs_g),
            "calories": float(calories),
        }
        if any(value < 0 for value in expected.values()):
            raise ValueError("macro targets cannot be negative")

        before = _effective_daily_targets(day)
        original_update_daily(
            day=day,
            template_name=template_name,
            protein_g=expected["protein_g"],
            fat_g=expected["fat_g"],
            carbs_g=expected["carbs_g"],
            calories=expected["calories"],
        )
        after = _effective_daily_targets(day)
        mismatches = {
            key: {"expected": expected[key], "actual": after.get(key)}
            for key in expected
            if not _close(after.get(key), expected[key])
        }
        if not mismatches:
            return True

        rollback_error = None
        try:
            original_update_daily(
                day=day,
                template_name=template_name,
                protein_g=before["protein_g"],
                fat_g=before["fat_g"],
                carbs_g=before["carbs_g"],
                calories=before["calories"],
            )
            restored = _effective_daily_targets(day)
            if any(not _close(restored.get(key), before[key]) for key in before):
                rollback_error = f"rollback read-back mismatch: {restored!r}"
        except Exception as exc:  # pragma: no cover - defensive live safeguard
            rollback_error = f"{type(exc).__name__}: {exc}"

        message = f"Daily macro write was not verified: {mismatches!r}"
        if rollback_error:
            message += f"; rollback_error={rollback_error}"
        else:
            message += "; original targets were restored"
        raise RuntimeError(message)

    def delete_macro_target_template_verified(self, template_id: int):
        if template_id <= 0:
            raise ValueError("template_id must be greater than zero")
        if _find_template(template_id) is None:
            raise ValueError(f"template_id {template_id} was not found")
        original_delete_template(template_id)
        if _find_template(template_id) is not None:
            raise RuntimeError(
                f"deleteMacroTargetTemplate was not verified for template_id={template_id}"
            )
        return True

    def save_macro_schedule_verified(self, day_of_week_us: int, template_id: int):
        if day_of_week_us not in range(7):
            raise ValueError("day_of_week must be 0 through 6")
        if template_id < 0:
            raise ValueError("template_id cannot be negative")
        if template_id != 0 and _find_template(template_id) is None:
            raise ValueError(f"template_id {template_id} was not found")

        original_save_schedule(day_of_week_us, template_id)
        schedules = self.get_all_macro_schedules()
        row = next(
            (
                item
                for item in schedules
                if isinstance(item, dict) and item.get("day_of_week") == day_of_week_us
            ),
            None,
        )
        actual = row.get("template_id") if row else None
        # The default/profile target may be represented without a template ID.
        if template_id == 0:
            if actual not in (None, 0):
                raise RuntimeError(
                    "saveMacroSchedule default-target write was not verified: "
                    f"day={day_of_week_us}, actual_template_id={actual!r}"
                )
        elif actual != template_id:
            raise RuntimeError(
                "saveMacroSchedule was not verified: "
                f"day={day_of_week_us}, expected_template_id={template_id}, "
                f"actual_template_id={actual!r}"
            )
        return True

    def delete_fast_verified(self, fast_id: int):
        if fast_id <= 0:
            raise ValueError("fast_id must be greater than zero")
        if _find_fast(self, fast_id) is None:
            raise ValueError(f"fast_id {fast_id} was not found")
        original_delete_fast(fast_id)
        if _find_fast(self, fast_id) is not None:
            raise RuntimeError(f"deleteFast was not verified for fast_id={fast_id}")
        return True

    def cancel_fast_keep_series_verified(self, fast_id: int):
        if fast_id <= 0:
            raise ValueError("fast_id must be greater than zero")
        source = _find_fast(self, fast_id)
        if source is None:
            raise ValueError(f"fast_id {fast_id} was not found")
        if source.get("is_active") is False:
            raise ValueError(f"fast_id {fast_id} is not active")

        original_cancel_fast(fast_id)
        current = _find_fast(self, fast_id)
        if current is not None and current.get("is_active") is not False:
            raise RuntimeError(
                f"cancelFastAndKeepSeries was not verified for fast_id={fast_id}"
            )
        return True

    # Keep the original reader available only for diagnostics/tests; normal
    # callers receive the mobile-verified effective values above.
    client._chatgpt_original_get_daily_macro_targets = original_get_daily
    client.get_daily_macro_targets = MethodType(get_daily_macro_targets_verified, client)
    client.update_daily_targets = MethodType(update_daily_targets_verified, client)
    client.delete_macro_target_template = MethodType(
        delete_macro_target_template_verified, client
    )
    client.save_macro_schedule = MethodType(save_macro_schedule_verified, client)
    client.delete_fast = MethodType(delete_fast_verified, client)
    client.cancel_fast_keep_series = MethodType(cancel_fast_keep_series_verified, client)
    client._chatgpt_verified_write_patch = True
    return client


hybrid._get_web_client = _patched_get_web_client
