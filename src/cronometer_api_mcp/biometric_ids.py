"""Conversions for Cronometer measurement IDs used by GWT-RPC.

Cronometer's mobile API exposes biometric IDs as ordinary decimal integers,
while the web GWT-RPC ``J`` (Java long) wire type serializes the exact same
integer in GWT's 64-character alphabet.  For example::

    1754598994 <-> "BolQ5S"

Keeping the MCP-facing ID numeric makes IDs from the mobile diary directly
usable for get/update/delete operations.  The web token is generated only at
the GWT boundary.
"""
from __future__ import annotations

GWT_LONG_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789$_"
_GWT_INDEX = {char: idx for idx, char in enumerate(GWT_LONG_ALPHABET)}


def encode_gwt_long(value: int | str) -> str:
    """Encode a non-negative integer as a GWT-RPC Java-long token."""
    number = int(value)
    if number < 0:
        raise ValueError("biometric ID must be non-negative")
    if number == 0:
        return "A"
    chars: list[str] = []
    while number:
        chars.append(GWT_LONG_ALPHABET[number & 63])
        number >>= 6
    return "".join(reversed(chars))


def decode_gwt_long(token: str) -> int:
    """Decode a positive GWT-RPC Java-long token to its integer value."""
    value = 0
    text = str(token).strip()
    if not text:
        raise ValueError("GWT long token cannot be empty")
    for char in text:
        try:
            digit = _GWT_INDEX[char]
        except KeyError as exc:
            raise ValueError(f"invalid GWT long token: {token!r}") from exc
        value = (value << 6) | digit
    return value


def normalize_biometric_id(value: int | str) -> str:
    """Return the canonical decimal biometric ID for decimal or GWT input."""
    text = str(value).strip()
    if not text:
        raise ValueError("biometric ID cannot be empty")
    if text.isdecimal():
        return str(int(text))
    return str(decode_gwt_long(text))


def web_biometric_id(value: int | str) -> str:
    """Return a GWT ``J`` token accepted by web ``removeMeasurement``."""
    text = str(value).strip()
    if not text:
        raise ValueError("biometric ID cannot be empty")
    if text.isdecimal():
        return encode_gwt_long(text)
    # Validate legacy/wire input before forwarding it.
    decode_gwt_long(text)
    return text
