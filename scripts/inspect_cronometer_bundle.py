#!/usr/bin/env python3
"""Inspect public Cronometer GWT bundle for current macro serialization IDs."""
from __future__ import annotations

import re

import httpx

NOCACHE = "https://cronometer.com/cronometer/cronometer.nocache.js"
CACHE = "https://cronometer.com/cronometer/{permutation}.cache.js"


def snippets(text: str, needle: str, radius: int = 500) -> list[str]:
    out: list[str] = []
    start = 0
    while True:
        pos = text.find(needle, start)
        if pos < 0:
            break
        lo = max(0, pos - radius)
        hi = min(len(text), pos + len(needle) + radius)
        out.append(text[lo:hi])
        start = pos + len(needle)
        if len(out) >= 8:
            break
    return out


def main() -> int:
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        nocache = client.get(NOCACHE)
        nocache.raise_for_status()
        candidates = re.findall(r"='([A-F0-9]{32})'", nocache.text)
        if not candidates:
            raise RuntimeError("Could not find GWT permutation in nocache.js")
        print("PERMUTATION_CANDIDATES", sorted(set(candidates)))

        for permutation in dict.fromkeys(candidates):
            response = client.get(CACHE.format(permutation=permutation))
            if response.status_code != 200:
                print("CACHE_SKIP", permutation, response.status_code)
                continue
            text = response.text
            print("CACHE", permutation, "chars", len(text))
            print(
                "MACRO_SIGNATURES",
                sorted(set(re.findall(r"MacroTargetTemplate/\\d+", text))),
            )
            print(
                "DAY_SIGNATURES",
                sorted(set(re.findall(r"entries\\.models\\.Day/\\d+", text)))[:20],
            )
            for needle in (
                "saveMacroTargetTemplate",
                "getMacroTargetTemplates",
                "updateDailyTargetTemplate",
                "MacroTargetTemplate",
                "update_macro_target_template",
            ):
                found = snippets(text, needle)
                print("NEEDLE", needle, "COUNT", text.count(needle))
                for idx, snippet in enumerate(found):
                    print(f"SNIPPET {needle} {idx}: {snippet}")
            return 0

    raise RuntimeError("No GWT cache candidate could be fetched")


if __name__ == "__main__":
    raise SystemExit(main())
