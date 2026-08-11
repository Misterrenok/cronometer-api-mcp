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
        '''def test_failure_variant_still_retries(tmp_path):\n    \"\"\"HTTP 200 + result:\"FAILURE\" retains the original retry behavior.\"\"\"\n    client, state = make_client(\n        tmp_path, [SYNTHETIC_FAILURE_BODY, {\"result\": \"SUCCESS\", \"id\": 1}]\n    )\n\n    result = client._request(\"/api/v2/get_diary\", {})\n\n    assert result == {\"result\": \"SUCCESS\", \"id\": 1}\n    assert state[\"login\"] == 1\n    assert state[\"post\"] == 2\n''',
        '''def test_functional_failure_variant_does_not_relogin(tmp_path):\n    \"\"\"A non-auth FAILURE is surfaced without destroying a valid session.\"\"\"\n    client, state = make_client(tmp_path, [SYNTHETIC_FAILURE_BODY])\n\n    with pytest.raises(CronometerError, match=\"synthetic\"):\n        client._request(\"/api/v2/get_diary\", {})\n\n    assert state[\"login\"] == 0\n    assert state[\"post\"] == 1\n''',
    )


if __name__ == "__main__":
    main()
