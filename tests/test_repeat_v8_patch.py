"""Tests for restored RepeatItem wire layout."""

from __future__ import annotations

from cronometer_api_mcp import repeat_v2_tools as repeat
from cronometer_api_mcp import repeat_v8_patch  # noqa: F401


def test_restored_template_matches_last_accepted_structure():
    body = repeat._GWT_ADD
    assert "|7|{quantity}|9|{day_count}|{day_entries}|0|11|{diary_group}|0|" in body
    assert "|{food_id}|{measure_id}|0|" in body
    assert "{diary_group_raw}" not in body
