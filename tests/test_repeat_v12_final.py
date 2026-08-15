"""Regression tests for the verified RepeatItem serializer mapping."""

from __future__ import annotations

from cronometer_api_mcp import repeat_v2_tools as repeat
from cronometer_api_mcp import repeat_v12_final  # noqa: F401


EMPTY = '//OK[0,1,["java.util.ArrayList/4159755760"],0,7]'
# Canonical Cronometer Lunch group is -4. The single weekday here is
# Wednesday=3 and is followed by the java.lang.Integer type reference=3.
LUNCH_WEDNESDAY = (
    "//OK[0,1073268,464877,900123,1,4,-4,3,3,1,1,3.0,2,1,1,"
    '["java.util.ArrayList/4159755760",'
    '"com.cronometer.shared.repeatitems.RepeatItem/477684891",'
    '"java.lang.Integer/3438268394",'
    '"Oatmeal, Regular or Quick, Dry"],0,7]'
)


def test_parser_decodes_canonical_lunch_group():
    assert repeat._parse(LUNCH_WEDNESDAY) == [
        {
            "repeat_item_id": 900123,
            "food_id": 464877,
            "measure_id": 1073268,
            "food_name": "Oatmeal, Regular or Quick, Dry",
            "quantity": 3.0,
            "diary_group": 2,
            "days_of_week": [3],
        }
    ]


class FakeClient:
    def __init__(self) -> None:
        self.user_id = "2107848"
        self.nonce = "testnonce"
        self.gwt_header = "AAAA"
        self.gets = [EMPTY, LUNCH_WEDNESDAY]
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


def test_lunch_serializes_group_as_integer_object_and_new_id_zero(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(repeat.hybrid, "_get_web_client", lambda: client)

    item = repeat._add(
        464877,
        1073268,
        3,
        "Oatmeal, Regular or Quick, Dry",
        2,
        [3],
    )

    assert item["diary_group"] == 2
    body = next(body for body in client.bodies if "addRepeatItem" in body)
    assert "|3|9|1|10|3|10|1|11|1|0|464877|1073268|0|" in body


def test_group_mapping_is_public_one_to_four_to_wire_zero_to_three():
    template = repeat._GWT_ADD
    assert (
        "|10|{diary_group_raw}|11|1|0|{food_id}|{measure_id}|0|" in template
    )
