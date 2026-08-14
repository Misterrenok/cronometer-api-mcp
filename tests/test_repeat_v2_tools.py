"""Regression tests for corrected recurring-food tools."""

from __future__ import annotations

from cronometer_api_mcp import repeat_v2_tools


EMPTY_RESPONSE = '//OK[0,1,["java.util.ArrayList/4159755760"],0,7]'


def _response(
    *,
    food_id: int = 1055762,
    measure_id: int = 461776,
    repeat_item_id: int = 658384,
    quantity: float = 3.0,
    food_name: str = "Wasa, Crispbread, Multi Grain",
    diary_group_raw: int = 0,
    day: int = 1,
) -> str:
    return (
        f"//OK[0,{food_id},{measure_id},{repeat_item_id},"
        f"1,4,{diary_group_raw},1,3,{day},1,{float(quantity)},2,1,1,"
        '["java.util.ArrayList/4159755760",'
        '"com.cronometer.shared.repeatitems.RepeatItem/477684891",'
        '"java.lang.Integer/3438268394",'
        f'"{food_name}"],0,7]'
    )


def test_parse_captured_repeat_response():
    assert repeat_v2_tools._parse(_response()) == [
        {
            "repeat_item_id": 658384,
            "food_id": 1055762,
            "measure_id": 461776,
            "food_name": "Wasa, Crispbread, Multi Grain",
            "quantity": 3.0,
            "diary_group": 1,
            "days_of_week": [1],
        }
    ]


def test_parse_empty_response():
    assert repeat_v2_tools._parse(EMPTY_RESPONSE) == []


class FakeClient:
    def __init__(self, gets: list[str]) -> None:
        self.user_id = "2107848"
        self.nonce = "testnonce"
        self.gwt_header = "AAAA"
        self.gets = list(gets)
        self.bodies: list[str] = []

    def authenticate(self) -> None:
        return None

    def _gwt_post(self, body: str) -> str:
        self.bodies.append(body)
        if "getRepeatedItems" in body:
            return self.gets.pop(0)
        if "addRepeatItem" in body or "deleteRepeatItem" in body:
            return "//OK[[],0,7]"
        raise AssertionError(body)


def test_add_uses_confirmed_field_order_and_readback(monkeypatch):
    created = _response(
        food_id=464877,
        measure_id=1073268,
        repeat_item_id=700001,
        quantity=1,
        food_name="Oatmeal, Regular or Quick, Dry",
    )
    client = FakeClient([EMPTY_RESPONSE, created])
    monkeypatch.setattr(
        repeat_v2_tools.hybrid,
        "_get_web_client",
        lambda: client,
    )

    item = repeat_v2_tools._add(
        464877,
        1073268,
        1,
        "Oatmeal, Regular or Quick, Dry",
        1,
        [1],
    )

    assert item["repeat_item_id"] == 700001
    add_body = next(body for body in client.bodies if "addRepeatItem" in body)
    assert (
        "|2107848|7|1|9|1|10|1|0|11|1|0|1073268|464877|0|"
        in add_body
    )


def test_delete_verifies_readback(monkeypatch):
    client = FakeClient([_response(), EMPTY_RESPONSE])
    monkeypatch.setattr(
        repeat_v2_tools.hybrid,
        "_get_web_client",
        lambda: client,
    )

    assert repeat_v2_tools._delete(658384) is True
    delete_body = next(body for body in client.bodies if "deleteRepeatItem" in body)
    assert "|2107848|658384|" in delete_body
