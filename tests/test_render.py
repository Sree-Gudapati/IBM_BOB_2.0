import json
from pathlib import Path

from debugagent.orchestrator import diagnose
from debugagent.render import render_json, render_text
from debugagent.subagent import build_subagents

D = diagnose(Path("tests/data/python_none.txt").read_text(), build_subagents())

def test_text_has_every_output_contract_section():
    out = render_text(D)
    for needle in ("Top diagnosis", "85%", "Root cause:", "Where:", "invoice.py:7 in build",
                   "Fixes:", "trade-off:", "Repro test:", "def test_repro_build"):
        assert needle in out

def test_json_round_trips():
    data = json.loads(render_json(D))
    assert data["families"] == ["python"]
    top = data["hypotheses"][0]
    assert top["pattern_id"] == "python.attribute_error.none_type"
    assert top["locations"][0] == {"file": "/srv/billing/app/invoice.py", "line": 7, "function": "build", "module": None}
    assert len(top["fixes"]) == 2


# --- Task 3 review fixes: long messages clipped in text; optional sections rendered
from dataclasses import replace

from debugagent.models import Diagnosis


def test_long_message_clipped_in_text_but_full_in_json():
    h = replace(D.top, message="A" * 5000)
    d = Diagnosis((h,), D.families)
    out = render_text(d)
    assert "A" * 500 + "…" in out and "A" * 501 not in out and "4,500 more chars" in out
    assert json.loads(render_json(d))["hypotheses"][0]["message"] == "A" * 5000

def test_text_renders_service_evidence_others_and_notes():
    h = replace(D.top, service="billing", evidence=("seen 3x in 5 min",))
    other = replace(D.top, pattern_id="python.key_error", confidence=0.5, service="web")
    out = render_text(Diagnosis((h, other), D.families, ("input truncated",)))
    for needle in ("Service: billing", "Evidence:", "seen 3x in 5 min", "Other hypotheses:",
                   "python.key_error (50%) in web", "Notes:", "input truncated"):
        assert needle in out

def test_empty_diagnosis_text():
    assert render_text(Diagnosis((), frozenset())) == "No stack trace found."
