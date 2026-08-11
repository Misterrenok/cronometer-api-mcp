#!/usr/bin/env python3
"""Inspect public Cronometer GWT bundle for macro serialization internals."""
from __future__ import annotations

import re

import httpx

NOCACHE = "https://cronometer.com/cronometer/cronometer.nocache.js"
CACHE = "https://cronometer.com/cronometer/{permutation}.cache.js"


def snippets(text: str, needle: str, radius: int = 1200, limit: int = 12) -> list[str]:
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
        if len(out) >= limit:
            break
    return out


def print_matches(text: str, pattern: str, label: str) -> None:
    matches = sorted(set(re.findall(pattern, text)))
    print(label, matches[:100])


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
            print_matches(text, r"MacroTargetTemplate/\d+", "MACRO_SIGNATURES")
            print_matches(text, r"entries\.models\.Day/\d+", "DAY_SIGNATURES")

            # Current bundle maps MacroTargetTemplate to class 337 with
            # constructor I_j and metadata symbol DXm.  Dump every occurrence
            # around those symbols so field initialization/serializers can be
            # reconstructed from the optimized JavaScript.
            needles = (
                "MacroTargetTemplate",
                "function I_j",
                "I_j=function",
                "new I_j",
                "DXm",
                "Pso",
                "kgn(337",
                "_.i=false;_.n=0",
                "3691130822",
                "608853615",
                "MacroSchedule",
                "MacroTargetsContext",
            )
            for needle in needles:
                found = snippets(text, needle)
                print("NEEDLE", needle, "COUNT", text.count(needle))
                for idx, snippet in enumerate(found):
                    print(f"SNIPPET {needle} {idx}: {snippet}")

            # Function bodies using the class constructor/metadata names.
            for symbol in ("I_j", "DXm", "Pso"):
                refs = [m.start() for m in re.finditer(re.escape(symbol), text)]
                print("REFS", symbol, refs[:100])
            return 0

    raise RuntimeError("No GWT cache candidate could be fetched")


if __name__ == "__main__":
    raise SystemExit(main())
