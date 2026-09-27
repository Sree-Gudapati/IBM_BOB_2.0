import time
from typer.testing import CliRunner
from debugagent.cli import app

R = CliRunner()
TRACE = "tests/data/python_none.txt"

def test_diagnose_file():
    r = R.invoke(app, ["diagnose", TRACE])
    assert r.exit_code == 0 and "python.attribute_error.none_type" in r.stdout

def test_diagnose_stdin_json():
    r = R.invoke(app, ["diagnose", "-", "--json"], input=open(TRACE).read())
    assert r.exit_code == 0 and '"pattern_id": "python.attribute_error.none_type"' in r.stdout

# Review Focus #5: degenerate input → clear message, exit 2, no traceback
def test_empty_stdin_exit_2():
    r = R.invoke(app, ["diagnose", "-"], input="")
    assert r.exit_code == 2 and "No input" in r.output and "Traceback" not in r.output

def test_binary_garbage_exit_2(tmp_path):
    p = tmp_path / "junk.bin"
    p.write_bytes(bytes(range(256)) * 100)
    r = R.invoke(app, ["diagnose", str(p)])
    assert r.exit_code == 2 and "No stack trace found" in r.output

def test_missing_file_exit_2():
    r = R.invoke(app, ["diagnose", "does/not/exist.txt"])
    assert r.exit_code == 2 and "not found" in r.output.lower()

def test_bad_extra_pattern_dir_exit_1(tmp_path):
    (tmp_path / "bad.yaml").write_text("id: x\n")
    r = R.invoke(app, ["diagnose", TRACE, "--patterns", str(tmp_path)])
    assert r.exit_code == 1 and "bad.yaml" in r.output

def test_large_log_within_budget(tmp_path):
    p = tmp_path / "big.log"
    p.write_text(("2026-09-26T10:00:00Z INFO [web] GET /health 200\n" * 120_000) + open(TRACE).read())
    t0 = time.perf_counter()
    r = R.invoke(app, ["diagnose", str(p)])
    assert r.exit_code == 0 and time.perf_counter() - t0 < 5.0
