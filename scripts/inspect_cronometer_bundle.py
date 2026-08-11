#!/usr/bin/env python3
"""Inspect MacroTargetTemplate runtime use and serializer layout in the GWT bundle."""

from __future__ import annotations

import re

import httpx

NOCACHE = "https://cronometer.com/cronometer/cronometer.nocache.js"
CACHE = "https://cronometer.com/cronometer/{permutation}.cache.js"


def emit(text: str, pattern: str, radius: int = 5000) -> None:
    matches = list(re.finditer(pattern, text))
    print("PATTERN", pattern, "COUNT", len(matches))
    for i, match in enumerate(matches):
        lo = max(0, match.start() - radius)
        hi = min(len(text), match.end() + radius)
        print(f"CTX {i} POS {match.start()}\n{text[lo:hi]}\nENDCTX")


def main() -> int:
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        nocache = client.get(NOCACHE)
        nocache.raise_for_status()
        permutations = list(
            dict.fromkeys(re.findall(r"='([A-F0-9]{32})'", nocache.text))
        )
        for permutation in permutations:
            response = client.get(CACHE.format(permutation=permutation))
            if response.status_code != 200:
                continue
            text = response.text
            print("PERMUTATION", permutation)
            for pattern in (
                r"wKk\([^\n;]{0,120},337\)",
                r"HKk\([^\n;]{0,120},337\)",
                r"DXm",
                r"Pso",
                r"function [A-Za-z0-9_$]+\([^)]*\)\{[^{}]{0,800}\.n[^{}]{0,800}\}",
            ):
                emit(text, pattern)
            return 0
    raise RuntimeError("no cache")


if __name__ == "__main__":
    raise SystemExit(main())
