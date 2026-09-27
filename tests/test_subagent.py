from pathlib import Path

from debugagent.models import Family
from debugagent.subagent import build_subagents


def test_subagent_only_holds_its_own_family_patterns():
    subs = build_subagents()
    assert all(p.family is Family.PYTHON for p in subs[Family.PYTHON].patterns)

def test_subagent_run_returns_one_hypothesis_per_trace():
    text = Path("tests/data/python_none.txt").read_text()
    assert len(build_subagents()[Family.PYTHON].run(text)) == 1
