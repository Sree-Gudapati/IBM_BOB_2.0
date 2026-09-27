from debugagent.models import Family, Frame, ParsedTrace

def test_root_walks_cause_chain_to_innermost():
    inner = ParsedTrace(Family.JVM, "java.lang.NullPointerException", "x", ())
    mid = ParsedTrace(Family.JVM, "java.lang.IllegalStateException", "y", (), cause=inner)
    outer = ParsedTrace(Family.JVM, "java.lang.RuntimeException", "z", (), cause=mid)
    assert outer.root() is inner

def test_short_error_type_strips_package():
    t = ParsedTrace(Family.JVM, "java.lang.NullPointerException", "", ())
    assert t.short_error_type == "NullPointerException"
