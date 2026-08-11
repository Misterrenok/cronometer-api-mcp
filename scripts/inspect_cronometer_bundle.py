#!/usr/bin/env python3
"""Inspect public Cronometer GWT bundle for macro serialization internals."""
from __future__ import annotations

import re

import httpx

NOCACHE = "https://cronometer.com/cronometer/cronometer.nocache.js"
CACHE = "https://cronometer.com/cronometer/{permutation}.cache.js"


def function_bodies(text: str, symbol: str) -> list[str]:
    """Return complete optimized JS function declarations for ``symbol``."""
    out: list[str] = []
    pattern = re.compile(rf"function\s+{re.escape(symbol)}\s*\([^)]*\)\s*\{{")
    for match in pattern.finditer(text):
        brace = text.find("{", match.start())
        depth = 0
        quote: str | None = None
        escaped = False
        for pos in range(brace, len(text)):
            ch = text[pos]
            if quote:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == quote:
                    quote = None
                continue
            if ch in ('"', "'"):
                quote = ch
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    out.append(text[match.start() : pos + 1])
                    break
    return out


def assignment_snippets(text: str, symbol: str, radius: int = 700) -> list[str]:
    refs: list[str] = []
    for pattern in (rf"{re.escape(symbol)}\s*=", rf"\b{re.escape(symbol)}\("):
        for match in re.finditer(pattern, text):
            refs.append(text[max(0, match.start() - radius) : match.start() + radius])
            if len(refs) >= 20:
                return refs
    return refs


def main() -> int:
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        nocache = client.get(NOCACHE)
        nocache.raise_for_status()
        candidates = re.findall(r"='([A-F0-9]{32})'", nocache.text)
        if not candidates:
            raise RuntimeError("Could not find GWT permutation in nocache.js")

        for permutation in dict.fromkeys(candidates):
            response = client.get(CACHE.format(permutation=permutation))
            if response.status_code != 200:
                continue
            text = response.text
            print("PERMUTATION", permutation)
            print("MACRO_SIGNATURES", sorted(set(re.findall(r"MacroTargetTemplate/\d+", text))))

            # Serialization registry from the current bundle maps
            # Pso -> [M_j, L_j, N_j]. Extract all related functions exactly.
            for symbol in ("M_j", "L_j", "N_j", "J_j", "K_j", "I_j"):
                bodies = function_bodies(text, symbol)
                print("FUNCTION", symbol, "COUNT", len(bodies))
                for index, body in enumerate(bodies):
                    print(f"BODY {symbol} {index}: {body}")
                if not bodies:
                    for index, snippet in enumerate(assignment_snippets(text, symbol)):
                        print(f"REF {symbol} {index}: {snippet}")

            registry = "a[Pso]=[M_j,L_j,N_j]"
            pos = text.find(registry)
            print("REGISTRY_POS", pos)
            if pos >= 0:
                print("REGISTRY_CONTEXT", text[max(0, pos - 1500) : pos + 1500])
            return 0

    raise RuntimeError("No GWT cache candidate could be fetched")


if __name__ == "__main__":
    raise SystemExit(main())
