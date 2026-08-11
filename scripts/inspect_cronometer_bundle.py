#!/usr/bin/env python3
"""Target the current Cronometer bundle around macro-template creation semantics."""
from __future__ import annotations

import re
import httpx

NOCACHE = "https://cronometer.com/cronometer/cronometer.nocache.js"
CACHE = "https://cronometer.com/cronometer/{permutation}.cache.js"


def emit_contexts(text: str, needle: str, radius: int = 3500, limit: int = 20) -> None:
    print("NEEDLE", needle, "COUNT", text.count(needle))
    start = 0
    for index in range(limit):
        pos = text.find(needle, start)
        if pos < 0:
            break
        print(f"CTX {needle} {index} POS {pos}\n{text[max(0,pos-radius):pos+radius]}\nENDCTX")
        start = pos + len(needle)


def main() -> int:
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        nocache = client.get(NOCACHE)
        nocache.raise_for_status()
        permutations = list(dict.fromkeys(re.findall(r"='([A-F0-9]{32})'", nocache.text)))
        for permutation in permutations:
            response = client.get(CACHE.format(permutation=permutation))
            if response.status_code != 200:
                continue
            text = response.text
            print("PERMUTATION", permutation)
            for needle in (
                "Rigorous",
                "saveMacroTargetTemplate",
                "getMacroTargetTemplates",
                "updateDailyTargetTemplate",
                "new I_j",
                "HKk(",
                "337)",
                "Pso",
            ):
                emit_contexts(text, needle, limit=8 if needle not in {"HKk("} else 0)
            return 0
    raise RuntimeError("No current cache.js could be fetched")


if __name__ == "__main__":
    raise SystemExit(main())
