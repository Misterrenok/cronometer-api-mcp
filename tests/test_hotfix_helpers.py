from __future__ import annotations

import re

from cronometer_api_mcp.biometric_ids import (
    decode_gwt_long,
    encode_gwt_long,
    normalize_biometric_id,
    web_biometric_id,
)


def test_biometric_id_decimal_gwt_round_trip():
    assert encode_gwt_long(1754598994) == "BolQ5S"
    assert decode_gwt_long("BolQ5S") == 1754598994
    assert normalize_biometric_id("BolQ5S") == "1754598994"
    assert web_biometric_id("1754598994") == "BolQ5S"


def test_gwt_long_alphabet_accepts_dollar_and_underscore():
    # GWT Java-long tokens use a custom base64 alphabet ending in $ and _.
    assert encode_gwt_long(1754599166) == "BolQ7$"
    assert normalize_biometric_id("BolQ7$") == "1754599166"
    assert decode_gwt_long("_") == 63


def test_add_biometric_response_regex_contract():
    pattern = r'^//OK\[\s*(?:"([^"\r\n]+)"|([1-9][0-9]{5,}))'

    match = re.search(pattern, "//OK[1754251966,[],0,7]")
    assert match and (match.group(1) or match.group(2)) == "1754251966"

    match = re.search(pattern, '//OK["BolQ7$",[],0,7]')
    assert match and (match.group(1) or match.group(2)) == "BolQ7$"
