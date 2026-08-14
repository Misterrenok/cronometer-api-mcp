"""Regression tests for live RepeatItem response layout."""

from __future__ import annotations

from cronometer_api_mcp import repeat_v2_tools as repeat
from cronometer_api_mcp import repeat_v6_patch  # noqa: F401


MONDAY_WASA = (
    '//OK[0,1055762,461776,658384,1,4,0,1,3,1,1,3.0,2,1,1,'
    '["java.util.ArrayList/4159755760",'
    '"com.cronometer.shared.repeatitems.RepeatItem/477684891",'
    '"java.lang.Integer/3438268394",'
    '"Wasa, Crispbread, Multi Grain"],0,7]'
)

WEDNESDAY_OATMEAL = (
    '//OK[0,1073268,464877,845579,1,4,0,3,3,1,1,2.0,2,1,1,'
    '["java.util.ArrayList/4159755760",'
    '"com.cronometer.shared.repeatitems.RepeatItem/477684891",'
    '"java.lang.Integer/3438268394",'
    '"Oatmeal, Regular or Quick, Dry"],0,7]'
)


def test_parses_captured_monday_wasa():
    assert repeat._parse(MONDAY_WASA) == [
        {
            "repeat_item_id": 658384,
            "food_id": 461776,
            "measure_id": 1055762,
            "food_name": "Wasa, Crispbread, Multi Grain",
            "quantity": 3.0,
            "diary_group": 1,
            "days_of_week": [1],
        }
    ]


def test_parses_live_wednesday_oatmeal():
    assert repeat._parse(WEDNESDAY_OATMEAL) == [
        {
            "repeat_item_id": 845579,
            "food_id": 464877,
            "measure_id": 1073268,
            "food_name": "Oatmeal, Regular or Quick, Dry",
            "quantity": 2.0,
            "diary_group": 1,
            "days_of_week": [3],
        }
    ]


def test_request_places_quantity_before_days_and_group_after_name():
    body = repeat._GWT_ADD
    assert "|7|{quantity}|9|{day_count}|{day_entries}|0|11|{diary_group}|0|" in body
    assert "|{food_id}|{measure_id}|0|" in body
