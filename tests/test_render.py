import json
from debugagent.orchestrator import diagnose
from debugagent.render import render_json, render_text
from debugagent.subagent import build_subagents

D = diagnose(open("tests/data/python_none.txt").read(), build_subagents())

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
