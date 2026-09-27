from debugagent.models import Family
from debugagent.orchestrator import diagnose
from debugagent.subagent import build_subagents

SIMPLE = open("tests/data/python_none.txt").read()

def test_diagnose_python_end_to_end():
    d = diagnose(SIMPLE, build_subagents())
    assert d.families == {Family.PYTHON}
    assert d.top.pattern_id == "python.attribute_error.none_type"
    assert d.top.locations[0].function == "build"

def test_same_error_twice_is_deduplicated():
    d = diagnose(SIMPLE + "\n" + SIMPLE, build_subagents())
    assert len(d.hypotheses) == 1

def test_no_trace_gives_empty_diagnosis():
    d = diagnose("INFO request ok\n", build_subagents())
    assert d.top is None and d.families == frozenset()

def test_oversized_input_notes_truncation():
    d = diagnose("x\n" * 3_000_000 + SIMPLE, build_subagents())
    assert d.top.pattern_id == "python.attribute_error.none_type"
    assert any("truncated" in n for n in d.notes)
