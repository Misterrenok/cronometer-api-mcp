#!/usr/bin/env python3
"""Inspect current Cronometer GWT bundle for MacroTargetTemplate creation."""
from __future__ import annotations

import re

import httpx

NOCACHE = "https://cronometer.com/cronometer/cronometer.nocache.js"
CACHE = "https://cronometer.com/cronometer/{permutation}.cache.js"


def contexts(text: str, needle: str, radius: int = 2400) -> None:
    start = 0
    index = 0
    while True:
        pos = text.find(needle, start)
        if pos < 0:
            return
        print(f"CONTEXT {needle} {index} POS {pos}: {text[max(0,pos-radius):pos+radius]}")
        start = pos + len(needle)
        index += 1
        if index >= 20:
            return


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
                "new I_j",
                "kgn(35,",
                "kgn(52,",
                ",35,",
                ",52,",
                "function N_j",
                "function L_j",
                "saveMacroTargetTemplate",
                "MacroTargetTemplate",
            ):
                print("COUNT", needle, text.count(needle))
                contexts(text, needle)
            return 0
    raise RuntimeError("No GWT cache candidate could be fetched")


if __name__ == "__main__":
    raise SystemExit(main())
