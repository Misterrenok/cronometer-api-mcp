from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE = Path(__file__).parents[1] / "scripts" / "apply_cronometer_hotfix.py"
spec = importlib.util.spec_from_file_location("cronometer_hotfix", MODULE)
hotfix = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(hotfix)


def test_numeric_and_legacy_id_regex_contract():
    pattern = r'^//OK\[\s*(?:"([A-Za-z0-9]+)"|([1-9][0-9]{5,}))'
    import re

    match = re.search(pattern, '//OK[1754251966,[],0,7]')
    assert match and (match.group(1) or match.group(2)) == "1754251966"

    match = re.search(pattern, '//OK["BXW0DA",[],0,7]')
    assert match and (match.group(1) or match.group(2)) == "BXW0DA"


def test_replace_function_is_syntax_safe():
    source = "def f():\n    return 1\n\ndef g():\n    return 2\n"
    patched, ok = hotfix.replace_function(source, "f", "def f():\n    return 3")
    assert ok
    compile(patched, "<patched>", "exec")
    namespace = {}
    exec(patched, namespace)
    assert namespace["f"]() == 3
    assert namespace["g"]() == 2
