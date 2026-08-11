#!/usr/bin/env python3
"""Inspect public Cronometer GWT bundle for macro serialization internals."""
from __future__ import annotations

import re

import httpx

NOCACHE = "https://cronometer.com/cronometer/cronometer.nocache.js"
CACHE = "https://cronometer.com/cronometer/{permutation}.cache.js"


def function_bodies(text: str, symbol: str) -> list[str]:
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


def main() -> int:
    symbols = (
        "M_j", "L_j", "N_j", "J_j", "K_j", "I_j",
        "O_j", "P_j", "Q_j", "R_j", "S_j", "T_j", "U_j",
        "V_j", "W_j", "X_j", "Y_j", "Z_j", "$_j", "__j",
        "Ns", "Js", "Ps", "Ms", "Is", "Qs", "Ws", "Ts",
    )
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
            for symbol in symbols:
                bodies = function_bodies(text, symbol)
                print("FUNCTION", symbol, "COUNT", len(bodies))
                for index, body in enumerate(bodies):
                    print(f"BODY {symbol} {index}: {body}")
            for needle in (".Ns=", ".Js=", ".Ps=", ".Ms=", ".Is=", ".Qs=", ".Ws=", ".Ts="):
                print("METHOD_NEEDLE", needle, "COUNT", text.count(needle))
                start = 0
                for index in range(10):
                    pos = text.find(needle, start)
                    if pos < 0:
                        break
                    print(f"METHOD_REF {needle} {index}: {text[max(0,pos-500):pos+700]}")
                    start = pos + len(needle)
            return 0
    raise RuntimeError("No GWT cache candidate could be fetched")


if __name__ == "__main__":
    raise SystemExit(main())
