#!/usr/bin/env python3
"""Inspect current Cronometer GWT bundle for MacroTargetTemplate field semantics."""
from __future__ import annotations

import re

import httpx

NOCACHE = "https://cronometer.com/cronometer/cronometer.nocache.js"
CACHE = "https://cronometer.com/cronometer/{permutation}.cache.js"


def contexts(text: str, needle: str, radius: int = 1800, limit: int = 20) -> None:
    start = 0
    for index in range(limit):
        pos = text.find(needle, start)
        if pos < 0:
            return
        print(f"CONTEXT {needle} {index} POS {pos}: {text[max(0,pos-radius):pos+radius]}")
        start = pos + len(needle)


def main() -> int:
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        nocache = client.get(NOCACHE)
        nocache.raise_for_status()
        candidates = re.findall(r"='([A-F0-9]{32})'", nocache.text)
        for permutation in dict.fromkeys(candidates):
            response = client.get(CACHE.format(permutation=permutation))
            if response.status_code != 200:
                continue
            text = response.text
            print("PERMUTATION", permutation)
            for needle in (
                "Rigorous",
                "Custom Targets",
                "Macro Target",
                "Macro Targets",
                "macro target",
                "macroTarget",
                "target template",
                "Template Name",
                "template name",
                "O_j(", "P_j(", "Q_j(", "R_j(", "S_j(", "T_j(", "U_j(",
                "V_j(", "W_j(", "X_j(", "Y_j(", "Z_j(", "$_j(", "__j(",
                "wKk(",
            ):
                count = text.count(needle)
                if count:
                    print("COUNT", needle, count)
                    contexts(text, needle, limit=12 if needle != "wKk(" else 0)
            # Show field setter function declarations if present.
            for symbol in (
                "O_j", "P_j", "Q_j", "R_j", "S_j", "T_j", "U_j", "V_j",
                "W_j", "X_j", "Y_j", "Z_j", "$_j", "__j",
            ):
                match = re.search(rf"function\s+{re.escape(symbol)}\s*\([^)]*\)\s*\{{[^}}]*\}}", text)
                print("SETTER", symbol, match.group(0) if match else "NOT_FOUND")
            return 0
    raise RuntimeError("No GWT cache candidate could be fetched")


if __name__ == "__main__":
    raise SystemExit(main())
