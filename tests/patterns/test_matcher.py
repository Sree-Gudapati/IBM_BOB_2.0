from debugagent.models import Family, Frame, ParsedTrace
from debugagent.patterns.loader import load_patterns
from debugagent.patterns.matcher import match_trace, is_library_frame

SPECIFIC = """
id: python.attribute_error.none_type
family: python
error_type: AttributeError
message_regex: "'NoneType' object has no attribute"
category: code
root_cause: None where an object was expected.
base_confidence: 0.85
fixes: [{summary: a, tradeoff: b}, {summary: c, tradeoff: d}]
"""
GENERIC = """
id: python.attribute_error.missing_attr
family: python
error_type: AttributeError
category: code
root_cause: Typo or wrong type.
base_confidence: 0.9
fixes: [{summary: a, tradeoff: b}, {summary: c, tradeoff: d}]
"""

def _pats(tmp_path):
    (tmp_path / "s.yaml").write_text(SPECIFIC)
    (tmp_path / "g.yaml").write_text(GENERIC)
    return load_patterns(tmp_path)

def _trace(msg, frames=None, cause=None, etype="AttributeError"):
    frames = frames or (Frame("/srv/billing/app/invoice.py", 7, "build"),)
    return ParsedTrace(Family.PYTHON, etype, msg, frames, cause)

def test_specific_message_pattern_beats_higher_confidence_generic(tmp_path):
    h = match_trace(_trace("'NoneType' object has no attribute 'zip'"), _pats(tmp_path))
    assert h.pattern_id == "python.attribute_error.none_type"
    assert h.confidence == 0.85

def test_generic_match_is_discounted(tmp_path):
    h = match_trace(_trace("'Foo' object has no attribute 'bar'"), _pats(tmp_path))
    assert h.pattern_id == "python.attribute_error.missing_attr"
    assert h.confidence == round(0.9 * 0.85, 4)

def test_matches_root_cause_not_wrapper(tmp_path):
    inner = _trace("'NoneType' object has no attribute 'zip'")
    outer = _trace("wrapped", etype="RuntimeError", cause=inner)
    assert match_trace(outer, _pats(tmp_path)).pattern_id == "python.attribute_error.none_type"

# Review Focus #3: unknown → low confidence, never a confident wrong answer
def test_unrecognized_error_is_low_confidence_unknown(tmp_path):
    h = match_trace(_trace("boom", etype="WeirdCustomError"), _pats(tmp_path))
    assert h.pattern_id == "python.unknown" and h.category == "unknown"
    assert h.confidence == 0.1 and "Unrecognized" in h.root_cause

def test_locations_skip_library_frames_innermost_first(tmp_path):
    frames = (
        Frame("/usr/lib/python3.11/site-packages/requests/models.py", 971, "json"),
        Frame("/srv/billing/app/client.py", 12, "fetch"),
        Frame("/srv/billing/app/api.py", 30, "handle"),
    )
    h = match_trace(_trace("'NoneType' object has no attribute 'x'", frames), _pats(tmp_path))
    assert [f.function for f in h.locations] == ["fetch", "handle"]

def test_repro_is_rendered_with_location(tmp_path):
    h = match_trace(_trace("'NoneType' object has no attribute 'zip'"), _pats(tmp_path))
    assert "def test_repro_build" in h.repro_test and "invoice.py:7" in h.repro_test

def test_is_library_frame_per_family():
    assert is_library_frame(Frame("x/node_modules/express/lib/router.js", 1, "h"), Family.NODE)
    assert is_library_frame(Frame("Thread.java", 1, "run", "java.lang.Thread"), Family.JVM)
    assert not is_library_frame(Frame("Orders.java", 1, "place", "com.acme.Orders"), Family.JVM)
    assert is_library_frame(Frame("/usr/local/go/src/runtime/panic.go", 1, "gopanic"), Family.GO)
    assert is_library_frame(Frame("/rustc/abc/library/core/src/panicking.rs", 1, "panic"), Family.RUST)
