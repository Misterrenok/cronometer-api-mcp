#!/usr/bin/env python3
"""Apply small compatibility repairs to the repository source."""
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


if __name__ == "__main__":
    main()
