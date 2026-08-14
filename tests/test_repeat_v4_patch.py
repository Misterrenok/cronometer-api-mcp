"""Tests for robust recurring-item update paths."""

from __future__ import annotations

import json

from cronometer_api_mcp import repeat_v2_tools as repeat
from cronometer_api_mcp import repeat_v4_patch


def _row(
    *,
    repeat_id: int = 845577,
    food_id: int = 464877,
    measure_id: int = 1073268,
    quantity: float = 1.0,
    group_raw: int = 0,
    day: int = 1,
) -> str:
    return (
        f"//OK[0,{measure_id},{food_id},{repeat_id},"
        f"1,4,{group_raw},1,3,{day},1,{float(quantity)},2,1,1,"
        '["java.util.ArrayList/4159755760",'
        '"com.cronometer.shared.repeatitems.RepeatItem/477684891",'
        '"java.lang.Integer/3438268394",'
        '"Oatmeal, Regular or Quick, Dry"],0,7]'
    )


class InPlaceClient:
    def __init__(self) -> None:
        self.user_id = "2107848"
        self.nonce = "testnonce"
        self.gwt_header = "AAAA"
        self.gets = [
            _row(),
            _row(),
            _row(quantity=2, group_raw=1, day=3),
        ]
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


def test_update_uses_nonzero_repeat_id_when_backend_supports_it(monkeypatch):
    client = InPlaceClient()
    monkeypatch.setattr(repeat.hybrid, "_get_web_client", lambda: client)

    payload = json.loads(
        repeat_v4_patch.update_repeat_item(
            repeat_item_id=845577,
            food_source_id=1073268,
            food_id=464877,
            quantity=2,
            food_name="MCP TEST Oatmeal Updated",
            diary_group=2,
            days_of_week=[3],
        )
    )

    assert payload["status"] == "success"
    assert payload["mode"] == "in-place-gwt"
    assert payload["replacement"]["repeat_item_id"] == 845577
    assert payload["replacement"]["quantity"] == 2.0
    save_body = next(body for body in client.bodies if "addRepeatItem" in body)
    assert "|2|0|464877|1073268|845577|" in save_body
