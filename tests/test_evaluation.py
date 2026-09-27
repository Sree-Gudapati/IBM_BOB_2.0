from pathlib import Path

import yaml
from typer.testing import CliRunner

from debugagent.cli import app
from debugagent.evaluation import evaluate
from debugagent.scanner import scan
from debugagent.subagent import build_subagents

CORPUS = Path("fixtures/traces")
SYSTEM = Path("fixtures/sample-system")
R = CliRunner()


def _mini_corpus(tmp_path):
    (tmp_path / "a.txt").write_text(open("tests/data/python_none.txt").read())
    (tmp_path / "b.txt").write_text(open("tests/data/python_none.txt").read())
    (tmp_path / "labels.yaml").write_text(yaml.safe_dump({"cases": [
        {"file": "a.txt", "expected": "python.attribute_error.none_type", "service": None},
        {"file": "b.txt", "expected": "python.key_error", "service": None},
    ]}))
    return tmp_path


def test_accuracy_and_misses(tmp_path):
    r = evaluate(_mini_corpus(tmp_path), build_subagents())
    assert r.accuracy == 0.5 and r.coverage == 1.0
    assert [c.file for c in r.results if not c.correct] == ["b.txt"]


def test_cli_threshold_failure_exit_1(tmp_path):
    res = R.invoke(app, ["eval", str(_mini_corpus(tmp_path)), "--min-accuracy", "0.9"])
    assert res.exit_code == 1 and "accuracy 50.0% < 90.0%" in res.output


def test_corpus_has_top10_per_family():
    cases = yaml.safe_load((CORPUS / "labels.yaml").read_text())["cases"]
    for fam in ("python", "jvm", "node", "go", "rust"):
        known = {
            c["expected"] for c in cases
            if c["expected"].startswith(fam + ".") and not c["expected"].endswith(".unknown")
        }
        assert len(known) >= 10, fam


# The Stage 1 acceptance gate
def test_committed_corpus_meets_stage1_targets():
    r = evaluate(CORPUS, build_subagents(), codebase=scan(SYSTEM, history=False))
    misses = [
        (c.file, c.expected, c.got, c.service_got)
        for c in r.results if not c.correct
    ]
    assert r.accuracy >= 0.85, misses
    assert r.coverage >= 0.95, misses
    assert r.max_subagent_s < 2.0
    assert r.p95_latency_s < 5.0
