import pytest
from debugagent.models import Family, Frame, ParsedTrace
from debugagent.patterns.loader import load_patterns, DEFAULT_PATTERN_DIR
from debugagent.patterns.matcher import match_trace

PATS = load_patterns(DEFAULT_PATTERN_DIR)
F = (Frame("/srv/billing/app/x.py", 1, "f"),)

@pytest.mark.parametrize("etype,msg,expected", [
    ("AttributeError", "'NoneType' object has no attribute 'zip'", "python.attribute_error.none_type"),
    ("AttributeError", "module 'json' has no attribute 'loadz'", "python.attribute_error.missing_attr"),
    ("ModuleNotFoundError", "No module named 'stripe'", "python.import_error.module_not_found"),
    ("ImportError", "cannot import name 'X' from 'y'", "python.import_error.cannot_import_name"),
    ("KeyError", "'customer_id'", "python.key_error"),
    ("TypeError", "'NoneType' object is not subscriptable", "python.type_error.none_not_subscriptable"),
    ("TypeError", "f() missing 1 required positional argument: 'x'", "python.type_error.call_signature"),
    ("IndexError", "list index out of range", "python.index_error"),
    ("RecursionError", "maximum recursion depth exceeded", "python.recursion_error"),
    ("requests.exceptions.ReadTimeout", "HTTPConnectionPool read timed out", "python.timeout"),
    ("ConnectionRefusedError", "[Errno 111] Connection refused", "python.connection_refused"),
    ("json.decoder.JSONDecodeError", "Expecting value: line 1 column 1", "python.json_decode"),
    ("UnboundLocalError", "local variable 'x' referenced before assignment", "python.unbound_local"),
])
def test_each_python_pattern_matches(etype, msg, expected):
    h = match_trace(ParsedTrace(Family.PYTHON, etype, msg, F), PATS)
    assert h.pattern_id == expected
    assert 2 <= len(h.fixes) <= 3 and h.repro_test
