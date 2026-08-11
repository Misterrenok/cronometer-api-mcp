#!/usr/bin/env python3
"""Inspect every runtime use of MacroTargetTemplate in the current GWT bundle."""
from __future__ import annotations

import re
import httpx

NOCACHE = "https://cronometer.com/cronometer/cronometer.nocache.js"
CACHE = "https://cronometer.com/cronometer/{permutation}.cache.js"


def emit(text: str, pattern: str, radius: int = 5000) -> None:
    matches = list(re.finditer(pattern, text))
    print("PATTERN", pattern, "COUNT", len(matches))
    for i, m in enumerate(matches):
        lo=max(0,m.start()-radius); hi=min(len(text),m.end()+radius)
        print(f"CTX {i} POS {m.start()}\n{text[lo:hi]}\nENDCTX")


def main() -> int:
    with httpx.Client(timeout=30, follow_redirects=True) as c:
        n=c.get(NOCACHE); n.raise_for_status()
        perms=list(dict.fromkeys(re.findall(r"='([A-F0-9]{32})'", n.text)))
        for p in perms:
            r=c.get(CACHE.format(permutation=p))
            if r.status_code != 200: continue
            t=r.text
            print("PERMUTATION",p)
            for pat in (
                r"wKk\([^\n;]{0,120},337\)",
                r"HKk\([^\n;]{0,120},337\)",
                r"DXm",
                r"Pso",
                r"function [A-Za-z0-9_$]+\([^)]*\)\{[^{}]{0,800}\.n[^{}]{0,800}\}",
            ):
                emit(t,pat)
            return 0
    raise RuntimeError('no cache')

if __name__=='__main__': raise SystemExit(main())
