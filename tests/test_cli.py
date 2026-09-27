import time
from pathlib import Path

from typer.testing import CliRunner

from debugagent.cli import app

R = CliRunner()
TRACE = "tests/data/python_none.txt"

def test_diagnose_file():
    r = R.invoke(app, ["diagnose", TRACE])
    assert r.exit_code == 0 and "python.attribute_error.none_type" in r.stdout

def test_diagnose_stdin_json():
    r = R.invoke(app, ["diagnose", "-", "--json"], input=Path(TRACE).read_text())
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
    p.write_text(("2026-09-26T10:00:00Z INFO [web] GET /health 200\n" * 120_000) + Path(TRACE).read_text())
    t0 = time.perf_counter()
    r = R.invoke(app, ["diagnose", str(p)])
    assert r.exit_code == 0 and time.perf_counter() - t0 < 5.0


# --- Task 3 review fixes -----------------------------------------------------
import os
import sys

import pytest

PY_TB = Path(TRACE).read_text()

@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0, reason="needs POSIX perms, non-root")
def test_unreadable_file_clean_error_exit_2(tmp_path):
    p = tmp_path / "locked.txt"
    p.write_text(PY_TB)
    p.chmod(0)
    try:
        r = R.invoke(app, ["diagnose", str(p)])
    finally:
        p.chmod(0o600)
    assert r.exit_code == 2 and "Cannot read input file" in r.output
    assert r.exception is None or isinstance(r.exception, SystemExit)

def test_directory_as_source_says_directory(tmp_path):
    r = R.invoke(app, ["diagnose", str(tmp_path)])
    assert r.exit_code == 2 and "is a directory" in r.output

def test_missing_patterns_dir_exit_1():
    r = R.invoke(app, ["diagnose", TRACE, "--patterns", "/no/such/dir"])
    assert r.exit_code == 1 and "Pattern directory not found" in r.output

def test_detected_family_without_analyzer_says_so():
    # Go is not yet registered; use it as the "detected but no analyzer" family
    go = "panic: runtime error: invalid memory address\n\ngoroutine 1 [running]:\nmain.main()\n\t/srv/svc/main.go:9 +0x1d\n"
    r = R.invoke(app, ["diagnose", "-"], input=go)
    assert r.exit_code == 2 and "Detected go" in r.output and "no analyzer" in r.output

@pytest.mark.parametrize("enc", ["utf-16", "utf-16-le", "utf-16-be", "utf-32", "utf-8-sig"])
def test_bom_and_utf16_input_decoded(tmp_path, enc):
    p = tmp_path / "t.txt"
    p.write_bytes(PY_TB.encode(enc))
    r = R.invoke(app, ["diagnose", str(p)])
    assert r.exit_code == 0 and "python.attribute_error.none_type" in r.stdout

def test_json_limit_caps_hypotheses_with_note(tmp_path):
    tb = ('Traceback (most recent call last):\n  File "/srv/app/y{i}.py", line 5, in run\n'
          '    d\nIndexError: list index out of range\n')
    p = tmp_path / "many.txt"
    p.write_text("".join(tb.format(i=i) for i in range(10)))
    import json
    data = json.loads(R.invoke(app, ["diagnose", str(p), "--json", "--limit", "3"]).stdout)
    assert len(data["hypotheses"]) == 3 and any("top 3 of 10" in n for n in data["notes"])

def test_tty_stdin_does_not_block(monkeypatch):
    from debugagent import cli
    class FakeTTY:
        def isatty(self): return True
    monkeypatch.setattr(cli.sys, "stdin", FakeTTY())
    with pytest.raises(cli.typer.Exit) as e:
        cli._read_input(None)
    assert e.value.exit_code == 2
