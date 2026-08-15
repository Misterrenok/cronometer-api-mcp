"""Regression tests for corrected recurring GWT field semantics."""

from __future__ import annotations

import json

from cronometer_api_mcp import repeat_v2_tools as repeat
from cronometer_api_mcp import repeat_v3_patch


# These captured legacy rows stored a zero/null diary-group key. Under the
# current DiaryGroup semantics that means Uncategorized, not Breakfast.
VALID_WASA = (
    "//OK[0,1055762,461776,658384,1,4,0,1,3,1,1,3.0,2,1,1,"
    '["java.util.ArrayList/4159755760",'
    '"com.cronometer.shared.repeatitems.RepeatItem/477684891",'
    '"java.lang.Integer/3438268394",'
    '"Wasa, Crispbread, Multi Grain"],0,7]'
)

LEGACY_BROKEN = (
    "//OK[0,464877,1,845544,1,4,0,1,3,1,1,1.0,2,1,1,"
    '["java.util.ArrayList/4159755760",'
    '"com.cronometer.shared.repeatitems.RepeatItem/477684891",'
    '"java.lang.Integer/3438268394",'
    '"Sour dressing, non-butterfat, cultured, filled cream-type"],0,7]'
)

EMPTY = '//OK[0,1,["java.util.ArrayList/4159755760"],0,7]'


def test_valid_wasa_maps_measure_food_repeat_in_correct_order():
    assert repeat._parse(VALID_WASA) == [
        {
            "repeat_item_id": 658384,
            "food_id": 461776,
            "measure_id": 1055762,
            "food_name": "Wasa, Crispbread, Multi Grain",
            "quantity": 3.0,
            "diary_group": 0,
            "diary_group_raw": 0,
            "days_of_week": [1],
        }
    ]


def test_legacy_broken_item_recovers_real_repeat_id():
    assert repeat._parse(LEGACY_BROKEN) == [
        {
            "repeat_item_id": 845544,
            "food_id": 1,
            "measure_id": 464877,
            "food_name": "Sour dressing, non-butterfat, cultured, filled cream-type",
            "quantity": 1.0,
            "diary_group": 0,
            "diary_group_raw": 0,
            "days_of_week": [1],
        }
    ]


class FakeClient:
    def __init__(self) -> None:
        # Breakfast is DiaryGroup index 1 => packed key 1 << 16 = 65536.
        created = (
            "//OK[0,1073268,464877,900001,1,4,65536,3,1,3,1,1,1.0,2,1,1,"
            '["java.util.ArrayList/4159755760",'
            '"com.cronometer.shared.repeatitems.RepeatItem/477684891",'
            '"java.lang.Integer/3438268394",'
            '"Oatmeal, Regular or Quick, Dry"],0,7]'
        )
        self.gets = [EMPTY, created]
        self.user_id = "2107848"
        self.nonce = "testnonce"
        self.gwt_header = "AAAA"
        self.bodies: list[str] = []

    def authenticate(self) -> None:
        return None

    def _gwt_post(self, body: str) -> str:
        self.bodies.append(body)
        if "getRepeatedItems" in body:
            return self.gets.pop(0)
        if "addRepeatItem" in body:
            return "//OK[[],0,7]"
        raise AssertionError(body)


def test_legacy_cached_schema_aliases_food_source_id_to_measure_id(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(repeat.hybrid, "_get_web_client", lambda: client)

    payload = json.loads(
        repeat_v3_patch.add_repeat_item(
            food_source_id=1073268,
            food_id=464877,
            quantity=1,
            food_name="Oatmeal, Regular or Quick, Dry",
            diary_group=1,
            days_of_week=[1],
        )
    )

    assert payload["status"] == "success"
    assert payload["item"]["food_id"] == 464877
    assert payload["item"]["measure_id"] == 1073268
    assert payload["item"]["diary_group"] == 1
    add_body = next(body for body in client.bodies if "addRepeatItem" in body)
    assert "|9|1|10|1|10|65536|11|1|0|464877|1073268|0|" in add_body
