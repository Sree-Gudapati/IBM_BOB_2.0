from pathlib import Path

from debugagent.models import Family
from debugagent.orchestrator import diagnose
from debugagent.subagent import build_subagents

SIMPLE = Path("tests/data/python_none.txt").read_text()

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


def test_family_without_subagent_is_noted():
    # Go is not yet registered; use it as the "detected but no analyzer" family
    go = "panic: runtime error: invalid memory address\n\ngoroutine 1 [running]:\nmain.main()\n\t/srv/svc/main.go:9 +0x1d\n"
    d = diagnose(SIMPLE + "\n" + go, build_subagents())
    assert d.top.pattern_id == "python.attribute_error.none_type"
    assert any("no go analyzer" in n for n in d.notes)
