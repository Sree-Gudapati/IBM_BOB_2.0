# Stage 1 — Debug Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic, offline, read-only Debug Agent CLI that takes a stack trace or error log from any of 5 language families (JVM, Python, Node, Go, Rust) and returns a ranked root-cause diagnosis with confidence, 2–3 fixes with trade-offs, the affected code locations, and a repro-test skeleton. It will be proven against a sample polyglot repo and then validated against the user's real microservices.

**Architecture:** Input text is normalized (log prefixes and ANSI codes stripped, size capped). Then the language families present are detected. One `LanguageSubagent` per family runs in parallel (a thread pool with a per-subagent timeout). Each subagent parses the traces for its family, walks exception chains to the root cause, and matches it against a YAML pattern database. An aggregator merges the hypotheses. It uses a `CodebaseMap` produced by the Codebase Scanner (services, languages, frameworks, dependency graph, and bug tags mined from git history) to attribute each hypothesis to a service, find the originating service across service boundaries, and apply codebase-specific confidence boosts. A fix log feeds a learning loop that promotes a recurring fix to a pattern after 10 occurrences. An eval harness measures accuracy, coverage, and latency against a labeled trace corpus.

**Tech Stack:** Python ≥3.11, `typer` (CLI), `pyyaml` (pattern DB), `pytest` (tests), `git` CLI (history mining). No network and no LLM in Stage 1.

**Spec:** `docs/superpowers/specs/2026-09-26-microservices-ai-workflow-design.md` (the original is `~/Downloads/2026-09-26-microservices-ai-workflow-design.md`; Task 1 copies it into the repo).

**Decisions already made by the user:** Python; sample polyglot repo first, then the real repo; deterministic only (no LLM) in Stage 1. Debugging comes before all other work: Stages 2–4 are only a roadmap at the end, and each gets its own plan later.

**Project location:** a new git repo at `~/code/debug-agent`. Pick a different path at execution time if you prefer. The session's scratch workspace is temporary, so the project must not live there.

## Global Constraints

- Python `>=3.11`. Runtime dependencies are limited to `typer>=0.12` and `pyyaml>=6.0`. The only dev dependency is `pytest>=8`.
- Target language families (spec): **JVM:** Java, Kotlin, Scala · **Python:** Python 3.8+ · **Node.js:** JavaScript, TypeScript · **Go:** Go 1.16+ · **Rust:** Rust (stable).
- Coverage scope (spec): "top 10 error types per language family", so at least 10 patterns per family and at least 50 in total.
- Debug Agent is **read-only** (spec rollout: "Debug Agent read-only (shows diagnostics, doesn't act)"). It never writes to scanned repos. The only files it writes are under `<root>/.debugagent/`.
- Output contract (spec): a diagnosis with confidence, **2–3 suggested fixes with trade-offs**, affected code locations, and a test case that reproduces the issue.
- Learning loop (spec): "After 10 similar fixes, elevate to a pattern"; "manual pattern addition, then automated".
- Stage 1 acceptance targets. Where the spec contradicts itself, this plan uses the stricter value:
  - Accuracy **≥ 85%** top-1 on the labeled corpus. The spec gives 80% in "Success Criteria" and 85% in the "Metrics" table.
  - Coverage **≥ 95%**: known-type traces get a non-`unknown` diagnosis.
  - Per-subagent latency **< 2 s**.
  - Diagnosis time: the spec says both "< 5 min" and "15 minutes". Deterministic `diagnose` must finish in **< 5 s** end-to-end, which easily meets both.
- Accuracy proxy: the spec's "proposed fixes work on first try" can't be measured offline. Stage 1 measures **top-1 pattern_id matches the human label** instead. First-try fix success is tracked later through the fix log (`debugagent learn`).
- Test coverage > 80% (spec, Testing Strategy).

## Review Focus

These are the input classes most likely to hurt a real user. The spec doesn't mention them; each is pinned by a test in the task named after it.

1. **Log-wrapped traces.** Real traces arrive with prefixes like `2026-09-26T10:00:00Z ERROR [billing]` on every line, ANSI colors, and CRLF line endings. They must parse exactly like clean traces (Task 1 and Task 2).
2. **Chained exceptions.** Examples: Java `Caused by:`, Python `The above exception was the direct cause…` / `During handling…`, and wrapped Node `cause`. The diagnosis must target the **innermost/original** cause, not the outer wrapper (Task 2 for Python, Task 4 for JVM).
3. **Unrecognized errors.** These must produce a low-confidence `<family>.unknown` hypothesis (confidence 0.1) that says "unrecognized". They must never produce a confident wrong answer (Task 2).
4. **Mixed multi-service input.** A Node frontend timeout plus a Java backend NPE in one paste must be diagnosed as "the Java NPE is the source; the Node timeout is a symptom", using the dependency graph (Task 10).
5. **Degenerate input.** Empty stdin, binary garbage, a 50 MB log, or text with no traces must each produce a clear message and exit code 2 within the time budget, never a traceback. A subagent that crashes or times out must not sink the others (Task 3 and Task 8).

---

## File Structure

```
debug-agent/
├── pyproject.toml
├── docs/superpowers/specs/2026-09-26-microservices-ai-workflow-design.md
├── src/debugagent/
│   ├── models.py            # Family, Frame, ParsedTrace, FixOption, Hypothesis, Diagnosis
│   ├── detect.py            # normalize(), detect_families()
│   ├── parsers/
│   │   ├── __init__.py      # PARSERS: dict[Family, Callable[[str], list[ParsedTrace]]]
│   │   ├── python.py  jvm.py  node.py  go.py  rust.py
│   ├── patterns/
│   │   ├── loader.py        # Pattern, load_patterns()
│   │   ├── matcher.py       # match_trace(), is_library_frame()
│   │   └── data/{python,jvm,node,go,rust}/*.yaml   # ≥10 each
│   ├── subagent.py          # LanguageSubagent, build_subagents()
│   ├── orchestrator.py      # diagnose()
│   ├── aggregator.py        # aggregate()
│   ├── scanner/
│   │   ├── models.py        # ServiceInfo, CodebaseMap
│   │   ├── languages.py     # detect_service(), scan_services()
│   │   ├── graph.py         # build_edges()
│   │   ├── history.py       # mine_history()
│   │   └── store.py         # scan(), save_map(), load_map()
│   ├── learning.py          # message_signature(), record_fix(), promote()
│   ├── evaluation.py        # EvalReport, evaluate()
│   ├── render.py            # render_text(), render_json()
│   └── cli.py               # typer app: diagnose | scan | learn | promote | eval
├── fixtures/
│   ├── sample-system/       # polyglot microservices with seeded bugs (Task 11)
│   └── traces/<family>/*.txt + traces/labels.yaml
└── tests/  (mirrors src layout; test_<module>.py)
```

The files are split by responsibility. Each parser, the matcher, the orchestrator, and the aggregator is small and replaceable. The pattern data is YAML so that people (and later the learning loop) can add patterns without touching code.

---

## Task order and why

Debugging comes first, as a vertical slice. After **Task 3**, `debugagent diagnose` already works end-to-end for Python. Every later task widens it: more families, then parallelism, then codebase awareness, then learning, then measurement.

| # | Task | Deliverable you can run |
|---|------|------------------------|
| 1 | Skeleton, models, input normalization and detection | `pytest` green; `detect_families()` works |
| 2 | Python parser, pattern DB, matcher, Python patterns | Python traces → hypotheses |
| 3 | Subagent, `diagnose` CLI, text/JSON renderer | `debugagent diagnose trace.txt` (Python) |
| 4 | JVM parser and patterns | Java/Kotlin/Scala traces diagnosed |
| 5 | Node parser and patterns | JS/TS traces diagnosed |
| 6 | Go parser and patterns | Go panics diagnosed |
| 7 | Rust parser and patterns | Rust panics diagnosed |
| 8 | Parallel orchestrator (timeouts, failure isolation, timings) | multi-language input diagnosed in parallel |
| 9 | Codebase Scanner: services, frameworks, dependency graph, store | `debugagent scan <root>` |
| 10 | Root-cause aggregator: service attribution and cross-service root cause | `diagnose --codebase` names the source service |
| 11 | Git-history bug mining and codebase-specific boosts | "this service has timezone bugs" signals |
| 12 | Sample polyglot system, labeled corpus, eval harness | `debugagent eval` enforces ≥85% / ≥95% / <2 s |
| 13 | Learning loop (fix log → promotion after 10) | `debugagent learn` / `promote` |
| 14 | Real-repo validation | eval report on your real services |

---

### Task 1: Project skeleton, core models, input normalization, and family detection

**Files:**
- Create: `pyproject.toml`, `src/debugagent/__init__.py`, `src/debugagent/models.py`, `src/debugagent/detect.py`, `tests/test_detect.py`, `tests/test_models.py`, `.gitignore`
- Copy: spec → `docs/superpowers/specs/2026-09-26-microservices-ai-workflow-design.md`

**Interfaces:**
- Produces: `Family` (str Enum: `jvm`, `python`, `node`, `go`, `rust`), `Frame(file, line, function, module=None)`, `ParsedTrace(family, error_type, message, frames, cause=None)` with `.root()`, `FixOption(summary, tradeoff)`, `Hypothesis(...)`, `Diagnosis(hypotheses, families, notes)` with `.top`. Also `normalize(text: str) -> str`, `detect_families(text: str) -> frozenset[Family]`, and `MAX_INPUT_CHARS = 5_000_000`.

- [ ] **Step 1: Create the repo and skeleton**

```bash
mkdir -p ~/code/debug-agent && cd ~/code/debug-agent && git init
mkdir -p src/debugagent tests docs/superpowers/specs
cp ~/Downloads/2026-09-26-microservices-ai-workflow-design.md docs/superpowers/specs/
printf '.venv/\n__pycache__/\n*.egg-info/\n.debugagent/\n.pytest_cache/\n' > .gitignore
touch src/debugagent/__init__.py
```

`pyproject.toml`:
```toml
[project]
name = "debugagent"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["typer>=0.12", "pyyaml>=6.0"]

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-cov>=5"]

[project.scripts]
debugagent = "debugagent.cli:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/debugagent"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

```bash
python3.11 -m venv .venv && . .venv/bin/activate && pip install -e '.[dev]'
```

- [ ] **Step 2: Write the failing tests**

`tests/test_models.py`:
```python
from debugagent.models import Family, Frame, ParsedTrace

def test_root_walks_cause_chain_to_innermost():
    inner = ParsedTrace(Family.JVM, "java.lang.NullPointerException", "x", ())
    mid = ParsedTrace(Family.JVM, "java.lang.IllegalStateException", "y", (), cause=inner)
    outer = ParsedTrace(Family.JVM, "java.lang.RuntimeException", "z", (), cause=mid)
    assert outer.root() is inner

def test_short_error_type_strips_package():
    t = ParsedTrace(Family.JVM, "java.lang.NullPointerException", "", ())
    assert t.short_error_type == "NullPointerException"
```

`tests/test_detect.py`:
```python
from debugagent.detect import detect_families, normalize, MAX_INPUT_CHARS
from debugagent.models import Family

PY = 'Traceback (most recent call last):\n  File "app/svc.py", line 3, in run\n    x.y\nAttributeError: \'NoneType\' object has no attribute \'y\'\n'
JAVA = 'Exception in thread "main" java.lang.NullPointerException\n\tat com.acme.Orders.place(Orders.java:42)\n'
NODE = "TypeError: Cannot read properties of undefined (reading 'id')\n    at handler (/srv/web/src/api.ts:10:5)\n"
GO = "panic: runtime error: invalid memory address or nil pointer dereference\n\ngoroutine 1 [running]:\nmain.main()\n\t/srv/inv/main.go:9 +0x1d\n"
RUST = "thread 'main' panicked at src/main.rs:4:37:\ncalled `Option::unwrap()` on a `None` value\n"

def test_detects_each_family():
    assert detect_families(PY) == {Family.PYTHON}
    assert detect_families(JAVA) == {Family.JVM}
    assert detect_families(NODE) == {Family.NODE}
    assert detect_families(GO) == {Family.GO}
    assert detect_families(RUST) == {Family.RUST}

def test_detects_mixed_input():
    assert detect_families(NODE + "\n" + JAVA) == {Family.NODE, Family.JVM}

def test_empty_and_garbage_detect_nothing():
    assert detect_families("") == frozenset()
    assert detect_families("\x00\xff binary junk \x01") == frozenset()

# Review Focus #1: log-wrapped traces parse like clean ones
def test_normalize_strips_timestamp_level_service_prefix_ansi_crlf():
    wrapped = "\r\n".join(
        f"2026-09-26T10:00:00.123Z ERROR [billing] \x1b[31m{ln}\x1b[0m" for ln in PY.splitlines()
    )
    out = normalize(wrapped)
    assert "Traceback (most recent call last):" in out
    assert "AttributeError: 'NoneType' object has no attribute 'y'" in out
    assert "\x1b" not in out and "\r" not in out
    assert detect_families(out) == {Family.PYTHON}

def test_normalize_keeps_tail_of_oversized_input():
    big = "x" * (MAX_INPUT_CHARS + 10) + PY
    out = normalize(big)
    assert len(out) <= MAX_INPUT_CHARS
    assert "AttributeError: 'NoneType' object has no attribute 'y'" in out
```

- [ ] **Step 3: Run to verify failure**

Run: `pytest tests/test_models.py tests/test_detect.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'debugagent.models'`

- [ ] **Step 4: Implement `models.py`**

```python
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum


class Family(str, Enum):
    JVM = "jvm"
    PYTHON = "python"
    NODE = "node"
    GO = "go"
    RUST = "rust"


@dataclass(frozen=True)
class Frame:
    file: str
    line: int | None
    function: str
    module: str | None = None


@dataclass(frozen=True)
class ParsedTrace:
    family: Family
    error_type: str
    message: str
    frames: tuple[Frame, ...]          # innermost (where it blew up) FIRST
    cause: ParsedTrace | None = None

    def root(self) -> ParsedTrace:
        t = self
        while t.cause is not None:
            t = t.cause
        return t

    @property
    def short_error_type(self) -> str:
        return self.error_type.rsplit(".", 1)[-1]


@dataclass(frozen=True)
class FixOption:
    summary: str
    tradeoff: str


@dataclass(frozen=True)
class Hypothesis:
    family: Family
    pattern_id: str                    # "<family>.unknown" when nothing matched
    category: str                      # "code" | "dependency" | "resource" | "config" | "unknown"
    root_cause: str
    confidence: float                  # 0.0–1.0
    error_type: str
    message: str
    fixes: tuple[FixOption, ...]
    locations: tuple[Frame, ...]       # app frames only, innermost first, max 3
    repro_test: str
    tags: tuple[str, ...] = ()
    service: str | None = None
    evidence: tuple[str, ...] = field(default=())


@dataclass(frozen=True)
class Diagnosis:
    hypotheses: tuple[Hypothesis, ...]  # sorted by confidence desc
    families: frozenset[Family]
    notes: tuple[str, ...] = ()         # truncation, subagent timeouts/crashes

    @property
    def top(self) -> Hypothesis | None:
        return self.hypotheses[0] if self.hypotheses else None
```

Frame-order convention (every parser must follow it): `frames[0]` is the frame where the error was raised. Python prints outermost first, so its parser reverses the list. JVM, Node, Go, and Rust already print innermost first.

- [ ] **Step 5: Implement `detect.py`**

```python
import re
from debugagent.models import Family

MAX_INPUT_CHARS = 5_000_000

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_PREFIX = re.compile(
    r"^(?:\[?\d{4}-\d{2}-\d{2}[T ][\d:.,]+(?:Z|[+-]\d{2}:?\d{2})?\]?\s+)?"
    r"(?:\[?(?:TRACE|DEBUG|INFO|WARN|WARNING|ERROR|SEVERE|FATAL|CRITICAL)\]?:?\s+)?"
    r"(?:\[[\w.@:/-]+\]\s+)?"
)

_SIGNATURES: dict[Family, re.Pattern[str]] = {
    Family.PYTHON: re.compile(r'^\s*Traceback \(most recent call last\):|^\s*File "[^"]+\.py", line \d+', re.M),
    Family.JVM: re.compile(r"^\s*at [\w$.<>/]+\([\w$]+\.(?:java|kt|scala):\d+\)|^Exception in thread \"", re.M),
    Family.NODE: re.compile(r"^\s*at (?:.+ \()?(?:file://)?[^\s()]+\.(?:js|mjs|cjs|ts|tsx|jsx):\d+:\d+\)?\s*$", re.M),
    Family.GO: re.compile(r"^panic: |^fatal error: |^goroutine \d+ \[", re.M),
    Family.RUST: re.compile(r"^thread '[^']*' panicked at ", re.M),
}


def normalize(text: str) -> str:
    if len(text) > MAX_INPUT_CHARS:
        text = text[-MAX_INPUT_CHARS:]
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(_PREFIX.sub("", _ANSI.sub("", ln), count=1) for ln in text.split("\n"))


def detect_families(text: str) -> frozenset[Family]:
    return frozenset(f for f, rx in _SIGNATURES.items() if rx.search(text))
```

Parsers must match frame lines with a leading `\s*` and must not rely on exact indentation, because `normalize` may eat leading whitespace after a stripped prefix.

- [ ] **Step 6: Run to verify pass**

Run: `pytest tests/test_models.py tests/test_detect.py -v`
Expected: PASS (7 tests)

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "feat: skeleton, core models, input normalization and family detection"
```

### Task 2: Python parser, pattern DB (loader, matcher, repro templates), Python patterns

**Files:**
- Create: `src/debugagent/parsers/__init__.py`, `src/debugagent/parsers/python.py`, `src/debugagent/patterns/__init__.py`, `src/debugagent/patterns/loader.py`, `src/debugagent/patterns/matcher.py`, `src/debugagent/patterns/repro.py`, `src/debugagent/patterns/data/python/*.yaml` (13 files)
- Test: `tests/parsers/test_python.py`, `tests/patterns/test_loader.py`, `tests/patterns/test_matcher.py`, `tests/patterns/test_python_patterns.py`

**Interfaces:**
- Consumes: `Family`, `Frame`, `ParsedTrace`, `FixOption`, and `Hypothesis` from Task 1.
- Produces:
  - `parsers.python.parse(text: str) -> list[ParsedTrace]` and `parsers.PARSERS: dict[Family, Callable[[str], list[ParsedTrace]]]` (Python only for now; Tasks 4–7 register the others).
  - `patterns.loader.Pattern` (fields: `id, family, error_type: re.Pattern, message_regex: re.Pattern | None, category, root_cause, base_confidence, fixes, repro_template, tags, source`), `load_patterns(*dirs: Path) -> list[Pattern]`, `PatternError`, and `DEFAULT_PATTERN_DIR`.
  - `patterns.matcher.match_trace(trace: ParsedTrace, patterns: Sequence[Pattern]) -> Hypothesis` and `is_library_frame(frame: Frame, family: Family) -> bool`.
  - `patterns.repro.render_repro(template: str, pattern_id: str, root: ParsedTrace, loc: Frame | None) -> str` and `FAMILY_REPRO: dict[Family, str]`.

- [ ] **Step 1: Write the failing parser tests** — `tests/parsers/test_python.py`

```python
from debugagent.detect import normalize
from debugagent.models import Family
from debugagent.parsers.python import parse

SIMPLE = '''Traceback (most recent call last):
  File "/srv/billing/app/api.py", line 20, in handle
    invoice = build(req)
  File "/srv/billing/app/invoice.py", line 7, in build
    return cust.address.zip
           ^^^^^^^^^^^^
AttributeError: 'NoneType' object has no attribute 'zip'
'''

CHAINED = '''Traceback (most recent call last):
  File "/srv/billing/app/db.py", line 3, in get
    return rows[0]
IndexError: list index out of range

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/srv/billing/app/api.py", line 9, in handle
    raise LookupFailed("no customer") from e
app.errors.LookupFailed: no customer
'''

def test_parses_type_message_and_frames_innermost_first():
    [t] = parse(SIMPLE)
    assert t.family is Family.PYTHON
    assert t.error_type == "AttributeError"
    assert t.message == "'NoneType' object has no attribute 'zip'"
    assert t.frames[0].file == "/srv/billing/app/invoice.py" and t.frames[0].line == 7
    assert t.frames[0].function == "build"
    assert len(t.frames) == 2

# Review Focus #2: chained exceptions → innermost/original cause
def test_chained_exception_root_is_original():
    traces = parse(CHAINED)
    assert len(traces) == 1
    assert traces[0].error_type == "app.errors.LookupFailed"
    assert traces[0].root().error_type == "IndexError"

def test_two_unrelated_tracebacks_are_two_traces():
    assert len(parse(SIMPLE + "\nsome log line\n" + SIMPLE)) == 2

# Review Focus #1: prefixed log lines (indentation lost) still parse
def test_log_prefixed_traceback_parses():
    wrapped = "\n".join(f"2026-09-26 10:00:00,123 ERROR [billing] {ln}" for ln in SIMPLE.splitlines())
    [t] = parse(normalize(wrapped))
    assert t.error_type == "AttributeError" and len(t.frames) == 2

def test_source_line_that_looks_like_a_name_is_not_an_exception():
    text = 'Traceback (most recent call last):\n  File "a.py", line 1, in f\n    Config.TIMEOUT\nKeyError: \'x\'\n'
    [t] = parse(text)
    assert t.error_type == "KeyError"

def test_no_traceback_returns_empty():
    assert parse("INFO all good\n") == []
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/parsers/test_python.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'debugagent.parsers'`

- [ ] **Step 3: Implement `parsers/python.py` and `parsers/__init__.py`**

```python
# src/debugagent/parsers/python.py
import re
from debugagent.models import Family, Frame, ParsedTrace

_HEADER = re.compile(r"^\s*Traceback \(most recent call last\):\s*$")
_FRAME = re.compile(r'^\s*File "(?P<file>[^"]+)", line (?P<line>\d+), in (?P<func>.+?)\s*$')
_CHAIN = re.compile(r"^\s*(The above exception was the direct cause|During handling of the above exception)")
_MARKER = re.compile(r"^\s*[~^]+\s*$")
_EXC = re.compile(r"^(?P<type>(?:[A-Za-z_]\w*\.)*[A-Z]\w*)(?::\s?(?P<msg>.*))?$")
_EXC_SUFFIXES = ("Error", "Exception", "Warning", "Interrupt", "Exit", "StopIteration")


def _exception_line(line: str) -> re.Match[str] | None:
    m = _EXC.match(line.strip())
    if not m:
        return None
    if m.group("msg") is None and not m.group("type").endswith(_EXC_SUFFIXES):
        return None
    return m


def parse(text: str) -> list[ParsedTrace]:
    results: list[ParsedTrace] = []
    frames: list[Frame] | None = None
    chained = False
    for line in text.split("\n"):
        if _CHAIN.match(line):
            chained = True
            continue
        if _HEADER.match(line):
            frames = []
            continue
        if frames is None:
            continue
        fm = _FRAME.match(line)
        if fm:
            frames.append(Frame(fm["file"], int(fm["line"]), fm["func"].strip()))
            continue
        if not line.strip() or _MARKER.match(line) or not frames:
            continue
        em = _exception_line(line)
        if em is None:
            continue  # a source line
        cause = results.pop() if chained and results else None
        results.append(ParsedTrace(
            Family.PYTHON, em["type"], (em["msg"] or "").strip(),
            tuple(reversed(frames)), cause=cause,
        ))
        frames, chained = None, False
    return results
```

```python
# src/debugagent/parsers/__init__.py
from typing import Callable
from debugagent.models import Family, ParsedTrace
from debugagent.parsers import python

PARSERS: dict[Family, Callable[[str], list[ParsedTrace]]] = {
    Family.PYTHON: python.parse,
}
```

Also create empty `tests/__init__.py`, `tests/parsers/__init__.py`, and `tests/patterns/__init__.py`, so tests can import shared fixtures (e.g. `from tests.parsers.test_rust import BT`).

- [ ] **Step 4: Run parser tests to verify pass**

Run: `pytest tests/parsers/test_python.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Write the failing loader and matcher tests**

`tests/patterns/test_loader.py`:
```python
import pytest
from debugagent.models import Family
from debugagent.patterns.loader import load_patterns, PatternError, DEFAULT_PATTERN_DIR

GOOD = """
id: python.test.thing
family: python
error_type: KeyError
category: code
root_cause: Missing key.
base_confidence: 0.7
fixes:
  - {summary: Use .get(), tradeoff: May hide bad data}
  - {summary: Validate schema, tradeoff: More code}
tags: [schema]
"""

def test_loads_valid_pattern_and_defaults_repro(tmp_path):
    (tmp_path / "a.yaml").write_text(GOOD)
    [p] = load_patterns(tmp_path)
    assert p.id == "python.test.thing" and p.family is Family.PYTHON
    assert p.error_type.fullmatch("KeyError")
    assert p.message_regex is None and len(p.fixes) == 2
    assert "pytest" in p.repro_template          # family default applied
    assert p.source == "manual"                  # non-default dir → manual

@pytest.mark.parametrize("mutation,needle", [
    (lambda s: s.replace("root_cause: Missing key.\n", ""), "missing required key 'root_cause'"),
    (lambda s: s.replace("base_confidence: 0.7", "base_confidence: 1.5"), "base_confidence"),
    (lambda s: s + "message_regex: '([unclosed'\n", "bad message_regex"),
    (lambda s: s.replace("  - {summary: Validate schema, tradeoff: More code}\n", ""), "2-3 fixes"),
])
def test_invalid_pattern_errors_name_the_file(tmp_path, mutation, needle):
    (tmp_path / "bad.yaml").write_text(mutation(GOOD))
    with pytest.raises(PatternError) as e:
        load_patterns(tmp_path)
    assert "bad.yaml" in str(e.value) and needle in str(e.value)

def test_duplicate_ids_rejected(tmp_path):
    (tmp_path / "a.yaml").write_text(GOOD)
    (tmp_path / "b.yaml").write_text(GOOD)
    with pytest.raises(PatternError, match="duplicate id"):
        load_patterns(tmp_path)

def test_missing_directory_is_skipped(tmp_path):
    assert load_patterns(tmp_path / "nope") == []

def test_builtin_python_patterns_load_and_meet_top10():
    pats = [p for p in load_patterns(DEFAULT_PATTERN_DIR) if p.family is Family.PYTHON]
    assert len(pats) >= 10
```

`tests/patterns/test_matcher.py`:
```python
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
```

- [ ] **Step 6: Run to verify failure**

Run: `pytest tests/patterns -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'debugagent.patterns'`

- [ ] **Step 7: Implement `patterns/repro.py`**

```python
import re
from string import Template
from debugagent.models import Family, Frame, ParsedTrace

FAMILY_REPRO: dict[Family, str] = {
    Family.PYTHON: '''# Repro for ${pattern_id} at ${file}:${line}
import pytest

def test_repro_${test_name}():
    # Arrange: rebuild the input that reached ${function}() (see the logged payload)
    # Assert the current failure; after the fix, change this to assert the correct result
    with pytest.raises(${short_error_type}):
        ${function}(...)  # call with the failing input
''',
    Family.JVM: '''// Repro for ${pattern_id} at ${file}:${line}
@Test
void repro_${test_name}() {
    // Arrange: rebuild the input that reached ${module}.${function}
    assertThrows(${short_error_type}.class, () -> {
        // call ${function} with the failing input
    });
}
''',
    Family.NODE: '''// Repro for ${pattern_id} at ${file}:${line}
test("repro ${test_name}", async () => {
  // Arrange: rebuild the input that reached ${function}
  await expect(async () => {
    // call ${function} with the failing input
  }).rejects.toThrow(/${message_escaped}/);
});
''',
    Family.GO: '''// Repro for ${pattern_id} at ${file}:${line}
func TestRepro_${test_name}(t *testing.T) {
	defer func() {
		if r := recover(); r == nil {
			t.Fatal("expected panic: ${message_quoted}")
		}
	}()
	// call ${function} with the failing input
}
''',
    Family.RUST: '''// Repro for ${pattern_id} at ${file}:${line}
#[test]
#[should_panic(expected = "${message_quoted}")]
fn repro_${test_name}() {
    // call ${function} with the failing input
}
''',
}


def render_repro(template: str, pattern_id: str, root: ParsedTrace, loc: Frame | None) -> str:
    function = loc.function if loc else "unknown"
    short_fn = re.split(r"[.:/]+", function)[-1] or function
    test_name = re.sub(r"\W+", "_", short_fn).strip("_") or "repro"
    msg = root.message[:80]
    return Template(template).safe_substitute(
        pattern_id=pattern_id,
        file=loc.file.rsplit("/", 1)[-1] if loc else "?",
        line=loc.line if loc and loc.line is not None else "?",
        function=short_fn,
        module=(loc.module or "") if loc else "",
        test_name=test_name,
        error_type=root.error_type,
        short_error_type=root.short_error_type,
        message_escaped=re.escape(msg).replace("/", r"\/"),
        message_quoted=msg.replace("\\", "\\\\").replace('"', '\\"'),
    )
```

- [ ] **Step 8: Implement `patterns/loader.py`**

```python
import re
from dataclasses import dataclass
from pathlib import Path
import yaml
from debugagent.models import Family, FixOption
from debugagent.patterns.repro import FAMILY_REPRO

DEFAULT_PATTERN_DIR = Path(__file__).parent / "data"
CATEGORIES = {"code", "dependency", "resource", "config"}
_REQUIRED = ("id", "family", "error_type", "category", "root_cause", "base_confidence", "fixes")


class PatternError(ValueError):
    pass


@dataclass(frozen=True)
class Pattern:
    id: str
    family: Family
    error_type: re.Pattern[str]
    message_regex: re.Pattern[str] | None
    category: str
    root_cause: str
    base_confidence: float
    fixes: tuple[FixOption, ...]
    repro_template: str
    tags: tuple[str, ...]
    source: str            # "builtin" | "manual" | "learned"


def _build(path: Path, d: dict, source: str) -> Pattern:
    if not isinstance(d, dict):
        raise PatternError(f"{path}: top level must be a mapping")
    for k in _REQUIRED:
        if k not in d:
            raise PatternError(f"{path}: missing required key '{k}'")
    try:
        family = Family(d["family"])
    except ValueError:
        raise PatternError(f"{path}: unknown family {d['family']!r}") from None
    if d["category"] not in CATEGORIES:
        raise PatternError(f"{path}: category must be one of {sorted(CATEGORIES)}")
    conf = d["base_confidence"]
    if not isinstance(conf, (int, float)) or not 0 < conf < 1:
        raise PatternError(f"{path}: base_confidence must be in (0, 1), got {conf!r}")
    fixes = d["fixes"]
    if not isinstance(fixes, list) or not 2 <= len(fixes) <= 3:
        raise PatternError(f"{path}: need 2-3 fixes with trade-offs, got {len(fixes) if isinstance(fixes, list) else fixes!r}")
    try:
        etype = re.compile(d["error_type"])
        mrx = re.compile(d["message_regex"]) if d.get("message_regex") else None
    except re.error as e:
        raise PatternError(f"{path}: bad message_regex/error_type: {e}") from None
    return Pattern(
        id=d["id"], family=family, error_type=etype, message_regex=mrx,
        category=d["category"], root_cause=d["root_cause"].strip(), base_confidence=float(conf),
        fixes=tuple(FixOption(f["summary"], f["tradeoff"]) for f in fixes),
        repro_template=d.get("repro_template") or FAMILY_REPRO[family],
        tags=tuple(d.get("tags", ())), source=d.get("source", source),
    )


def load_patterns(*dirs: Path) -> list[Pattern]:
    out: dict[str, Pattern] = {}
    for base in dirs:
        base = Path(base)
        if not base.is_dir():
            continue
        source = "builtin" if base.resolve() == DEFAULT_PATTERN_DIR.resolve() else "manual"
        for path in sorted(base.rglob("*.yaml")):
            try:
                data = yaml.safe_load(path.read_text())
            except yaml.YAMLError as e:
                raise PatternError(f"{path}: invalid YAML: {e}") from None
            p = _build(path, data, source)
            if p.id in out:
                raise PatternError(f"{path}: duplicate id {p.id!r}")
            out[p.id] = p
    return list(out.values())
```

Note: the "bad message_regex" test needle matches the combined message `bad message_regex/error_type`.

- [ ] **Step 9: Implement `patterns/matcher.py`**

```python
import re
from typing import Sequence
from debugagent.models import Family, Frame, Hypothesis, ParsedTrace
from debugagent.patterns.loader import Pattern
from debugagent.patterns.repro import render_repro

GENERIC_DISCOUNT = 0.85
UNKNOWN_CONFIDENCE = 0.1

_LIB_PATH = re.compile(
    r"site-packages/|dist-packages/|/lib/python\d[\d.]*/|<frozen |node_modules/|^node:|^internal/"
    r"|/usr/local/go/src/|/go/pkg/mod/|^runtime/|\.cargo/registry/|^/rustc/|/library/(?:std|core|alloc)/"
)
_JVM_LIB = re.compile(r"^(?:java|javax|jdk|sun|com\.sun|kotlin|kotlinx|scala|org\.springframework|io\.netty|org\.apache|com\.zaxxer|io\.quarkus|reactor)\.")


def is_library_frame(frame: Frame, family: Family) -> bool:
    if family is Family.JVM:
        return bool(frame.module and _JVM_LIB.match(frame.module))
    return bool(_LIB_PATH.search(frame.file))


def _locations(root: ParsedTrace) -> tuple[Frame, ...]:
    app = [f for f in root.frames if not is_library_frame(f, root.family)]
    return tuple(app[:3]) or root.frames[:1]


def match_trace(trace: ParsedTrace, patterns: Sequence[Pattern]) -> Hypothesis:
    root = trace.root()
    locs = _locations(root)
    best: tuple[int, float, Pattern] | None = None
    for p in patterns:
        if p.family is not root.family:
            continue
        if not (p.error_type.fullmatch(root.error_type) or p.error_type.fullmatch(root.short_error_type)):
            continue
        if p.message_regex is not None and not p.message_regex.search(root.message):
            continue
        key = (1 if p.message_regex is not None else 0, p.base_confidence, p)
        if best is None or key[:2] > best[:2]:
            best = key
    if best is None:
        return Hypothesis(
            family=root.family, pattern_id=f"{root.family.value}.unknown", category="unknown",
            root_cause=f"Unrecognized {root.error_type}: {root.message[:200]}. No pattern matched; "
                       f"add one under patterns/data/{root.family.value}/.",
            confidence=UNKNOWN_CONFIDENCE, error_type=root.error_type, message=root.message,
            fixes=(), locations=locs, repro_test="",
        )
    specific, _, p = best
    conf = p.base_confidence if specific else round(p.base_confidence * GENERIC_DISCOUNT, 4)
    return Hypothesis(
        family=root.family, pattern_id=p.id, category=p.category, root_cause=p.root_cause,
        confidence=conf, error_type=root.error_type, message=root.message, fixes=p.fixes,
        locations=locs, repro_test=render_repro(p.repro_template, p.id, root, locs[0] if locs else None),
        tags=p.tags,
    )
```

- [ ] **Step 10: Add the 13 Python patterns** in `src/debugagent/patterns/data/python/<slug>.yaml` (file name = the part of the id after `python.`)

Full example, `attribute_error.none_type.yaml`:
```yaml
id: python.attribute_error.none_type
family: python
error_type: AttributeError
message_regex: "'NoneType' object has no attribute"
category: code
root_cause: >
  A value expected to be an object is None, usually an unchecked return from a
  lookup (dict.get, ORM .first(), regex match) or an optional field in a payload.
base_confidence: 0.85
tags: [null]
fixes:
  - summary: Guard with an explicit None check at the call site and handle the missing case
    tradeoff: Local and fast, but can hide the upstream bug that produced None
  - summary: Make the producer raise (or return a typed Optional checked by mypy) instead of silently returning None
    tradeoff: Surfaces the bug at its source; changes the function's contract for other callers
```

The remaining 12 use the same shape. `error_type` and `message_regex` are regexes; a blank `message_regex` cell means omit the key (a generic pattern).

| file slug | error_type | message_regex | category | conf | tags | root_cause | fixes (tradeoff in parentheses) |
|---|---|---|---|---|---|---|---|
| attribute_error.missing_attr | `AttributeError` | `has no attribute` | code | 0.6 | [typo] | Typo in the attribute name, or the object is a different type than assumed (dict vs object, wrong library version) | Fix the name and add type hints + mypy (cheap; needs typing discipline) · Pin the dependency version that has the attribute (fast; defers upgrade work) |
| import_error.module_not_found | `ModuleNotFoundError` | `No module named` | config | 0.85 | [import, deploy] | Package missing from the runtime image, or wrong import path / missing `__init__.py` | Add to requirements/pyproject and rebuild the image (correct; slower deploy) · Fix the package layout/PYTHONPATH (no dependency change; may break other imports) |
| import_error.cannot_import_name | `ImportError` | `cannot import name` | code | 0.8 | [import] | Circular import, or the symbol was removed or renamed in a dependency upgrade | Break the cycle by moving the import into the function (quick; hides a design smell) · Pin or upgrade to a version that exports the symbol (clean; version churn) |
| key_error | `KeyError` | | code | 0.7 | [schema] | Dict lookup for a key missing from a payload or config, often schema drift between services | Use `.get()` with an explicit default (tolerant; may mask bad data) · Validate the payload at the boundary with a schema, e.g. pydantic (fails early and loudly; more code) |
| type_error.none_not_subscriptable | `TypeError` | `'NoneType' object is not (subscriptable\|iterable\|callable)` | code | 0.85 | [null] | None flowed to a place that needs a container or callable | Guard None where the value is produced (local; may hide the upstream cause) · Return an empty container instead of None (removes the bug class; changes semantics) |
| type_error.call_signature | `TypeError` | `missing \d+ required positional argument\|takes \d+ positional arguments? but \d+ (were\|was) given\|got an unexpected keyword argument` | code | 0.85 | [api-drift] | Caller and callee signatures drifted apart (a refactor or library upgrade) | Update every call site (correct; touches many files) · Add a backward-compatible default or kwarg to the callee (safe; accumulates cruft) |
| index_error | `IndexError` | `index out of range` | code | 0.8 | [off-by-one, empty] | Off-by-one error, or code assumed a collection is non-empty | Check emptiness/length before indexing (local fix) · Iterate or use `next(iter(x), default)` instead of indexing (removes the bug class; small refactor) |
| recursion_error | `RecursionError` | `maximum recursion depth exceeded` | code | 0.85 | [recursion] | Unbounded recursion: a missing base case, or cyclic data (for example a self-referencing object in a serializer) | Add a base case or cycle detection (fixes the root; needs understanding of the data) · Convert to iteration with an explicit stack (robust; bigger change) |
| timeout | `TimeoutError\|ReadTimeout\|ConnectTimeout\|ReadTimeoutError\|ConnectTimeoutError` | | dependency | 0.75 | [timeout] | A downstream dependency didn't respond in time; the real fault is usually in the service being called | Raise the timeout and add retry with backoff (quick; can amplify load during an outage) · Fix the downstream slowness and add a circuit breaker (root fix; cross-team) |
| connection_refused | `ConnectionRefusedError\|ConnectionError\|NewConnectionError\|OperationalError` | `Connection refused\|Errno 111\|could not connect` | dependency | 0.8 | [connectivity] | Target service or DB isn't listening: down, wrong host/port, or not ready yet at startup | Check service discovery / env host+port (config fix; needs a deploy) · Add a readiness wait with retry at startup (resilient; slower boot) |
| json_decode | `JSONDecodeError` | | dependency | 0.75 | [parsing] | The response body wasn't JSON, usually an HTML error page or empty body from an upstream failure | Check status code and content-type before `.json()` (clearer errors; more code) · Log the raw body (truncated) on failure (diagnosable; log volume) |
| unbound_local | `UnboundLocalError` | | code | 0.85 | [scoping] | Variable is assigned only in some branches, or an assignment later in the function shadows a global | Initialize the variable before the branches (simple) · Rename the local or use `global`/`nonlocal` explicitly (clear intent; wider diff) |

- [ ] **Step 11: Write the per-pattern golden test** — `tests/patterns/test_python_patterns.py`

```python
import pytest
from debugagent.models import Family, Frame, ParsedTrace
from debugagent.patterns.loader import load_patterns, DEFAULT_PATTERN_DIR
from debugagent.patterns.matcher import match_trace

PATS = load_patterns(DEFAULT_PATTERN_DIR)
F = (Frame("/srv/billing/app/x.py", 1, "f"),)

@pytest.mark.parametrize("etype,msg,expected", [
    ("AttributeError", "'NoneType' object has no attribute 'zip'", "python.attribute_error.none_type"),
    ("AttributeError", "module 'json' has no attribute 'loadz'", "python.attribute_error.missing_attr"),
    ("ModuleNotFoundError", "No module named 'stripe'", "python.import_error.module_not_found"),
    ("ImportError", "cannot import name 'X' from 'y'", "python.import_error.cannot_import_name"),
    ("KeyError", "'customer_id'", "python.key_error"),
    ("TypeError", "'NoneType' object is not subscriptable", "python.type_error.none_not_subscriptable"),
    ("TypeError", "f() missing 1 required positional argument: 'x'", "python.type_error.call_signature"),
    ("IndexError", "list index out of range", "python.index_error"),
    ("RecursionError", "maximum recursion depth exceeded", "python.recursion_error"),
    ("requests.exceptions.ReadTimeout", "HTTPConnectionPool read timed out", "python.timeout"),
    ("ConnectionRefusedError", "[Errno 111] Connection refused", "python.connection_refused"),
    ("json.decoder.JSONDecodeError", "Expecting value: line 1 column 1", "python.json_decode"),
    ("UnboundLocalError", "local variable 'x' referenced before assignment", "python.unbound_local"),
])
def test_each_python_pattern_matches(etype, msg, expected):
    h = match_trace(ParsedTrace(Family.PYTHON, etype, msg, F), PATS)
    assert h.pattern_id == expected
    assert 2 <= len(h.fixes) <= 3 and h.repro_test
```

- [ ] **Step 12: Run all tests to verify pass**

Run: `pytest -v`
Expected: PASS (all tests from Tasks 1–2)

- [ ] **Step 13: Commit**

```bash
git add -A && git commit -m "feat: python parser, YAML pattern DB, matcher, repro templates, 13 python patterns"
```

### Task 3: Language subagent, sequential `diagnose`, renderers, and the `diagnose` CLI (end-to-end for Python)

**Files:**
- Create: `src/debugagent/subagent.py`, `src/debugagent/aggregator.py`, `src/debugagent/orchestrator.py`, `src/debugagent/render.py`, `src/debugagent/cli.py`
- Test: `tests/test_subagent.py`, `tests/test_orchestrator.py`, `tests/test_render.py`, `tests/test_cli.py`, `tests/data/python_none.txt`

**Interfaces:**
- Consumes: `PARSERS`, `load_patterns`, `DEFAULT_PATTERN_DIR`, `match_trace`, `normalize`, `detect_families`, and `MAX_INPUT_CHARS`.
- Produces:
  - `LanguageSubagent(family: Family, parse: Callable[[str], list[ParsedTrace]], patterns: list[Pattern])` with `.run(text: str) -> list[Hypothesis]`.
  - `build_subagents(extra_pattern_dirs: Sequence[Path] = ()) -> dict[Family, LanguageSubagent]`.
  - `aggregate(hyps: Iterable[Hypothesis]) -> tuple[Hypothesis, ...]` (Task 9 adds a `codebase` parameter).
  - `diagnose(text: str, subagents: dict[Family, LanguageSubagent]) -> Diagnosis` (Task 8 adds `timeout_s`, Task 9 adds `codebase`).
  - `render_text(d: Diagnosis, limit: int = 3) -> str` and `render_json(d: Diagnosis) -> str`.
  - The CLI `debugagent diagnose [SOURCE|-] [--json] [--patterns DIR]...`. Exit codes: `0` = diagnosed, `1` = pattern DB error, `2` = no input or no stack trace found.

- [ ] **Step 1: Write the failing tests**

`tests/data/python_none.txt`: copy the `SIMPLE` traceback from `tests/parsers/test_python.py` (Task 2) verbatim.

`tests/test_orchestrator.py`:
```python
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
```

`tests/test_render.py`:
```python
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
```

`tests/test_cli.py`:
```python
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
```

`tests/test_subagent.py`:
```python
from debugagent.models import Family
from debugagent.subagent import build_subagents

def test_subagent_only_holds_its_own_family_patterns():
    subs = build_subagents()
    assert all(p.family is Family.PYTHON for p in subs[Family.PYTHON].patterns)

def test_subagent_run_returns_one_hypothesis_per_trace():
    text = open("tests/data/python_none.txt").read()
    assert len(build_subagents()[Family.PYTHON].run(text)) == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_subagent.py tests/test_orchestrator.py tests/test_render.py tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'debugagent.subagent'`

- [ ] **Step 3: Implement `subagent.py`**

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence
from debugagent.models import Family, Hypothesis, ParsedTrace
from debugagent.parsers import PARSERS
from debugagent.patterns.loader import DEFAULT_PATTERN_DIR, Pattern, load_patterns
from debugagent.patterns.matcher import match_trace


@dataclass
class LanguageSubagent:
    family: Family
    parse: Callable[[str], list[ParsedTrace]]
    patterns: list[Pattern]

    def run(self, text: str) -> list[Hypothesis]:
        return [match_trace(t, self.patterns) for t in self.parse(text)]


def build_subagents(extra_pattern_dirs: Sequence[Path] = ()) -> dict[Family, LanguageSubagent]:
    pats = load_patterns(DEFAULT_PATTERN_DIR, *extra_pattern_dirs)
    return {
        fam: LanguageSubagent(fam, parser, [p for p in pats if p.family is fam])
        for fam, parser in PARSERS.items()
    }
```

- [ ] **Step 4: Implement `aggregator.py` (first version)**

```python
from typing import Iterable
from debugagent.models import Hypothesis


def _key(h: Hypothesis) -> tuple:
    loc = h.locations[0] if h.locations else None
    return (h.pattern_id, loc.file if loc else None, loc.line if loc else None, h.service)


def aggregate(hyps: Iterable[Hypothesis]) -> tuple[Hypothesis, ...]:
    best: dict[tuple, Hypothesis] = {}
    for h in hyps:
        k = _key(h)
        if k not in best or h.confidence > best[k].confidence:
            best[k] = h
    return tuple(sorted(best.values(), key=lambda h: (-h.confidence, h.pattern_id)))
```

- [ ] **Step 5: Implement `orchestrator.py` (sequential; Task 8 parallelizes it)**

```python
from debugagent.aggregator import aggregate
from debugagent.detect import MAX_INPUT_CHARS, detect_families, normalize
from debugagent.models import Diagnosis, Family
from debugagent.subagent import LanguageSubagent


def diagnose(text: str, subagents: dict[Family, LanguageSubagent]) -> Diagnosis:
    notes: list[str] = []
    if len(text) > MAX_INPUT_CHARS:
        notes.append(f"input truncated to its last {MAX_INPUT_CHARS:,} characters")
    clean = normalize(text)
    families = detect_families(clean)
    hyps = []
    for fam in sorted(families, key=lambda f: f.value):
        if fam in subagents:
            hyps.extend(subagents[fam].run(clean))
    return Diagnosis(aggregate(hyps), families, tuple(notes))
```

- [ ] **Step 6: Implement `render.py`**

```python
import json
import textwrap
from debugagent.models import Diagnosis, Frame, Hypothesis


def _loc(f: Frame) -> str:
    return f"{f.file}:{f.line if f.line is not None else '?'} in {f.function}"


def _hyp_block(h: Hypothesis) -> list[str]:
    lines = [f"Top diagnosis (confidence {h.confidence:.0%}) — {h.pattern_id} [{h.category}]"]
    if h.service:
        lines.append(f"Service: {h.service}")
    lines += [f"Error: {h.error_type}: {h.message}", f"Root cause: {h.root_cause}", "Where:"]
    lines += [f"  {i}. {_loc(f)}" for i, f in enumerate(h.locations, 1)] or ["  (no frames)"]
    if h.fixes:
        lines.append("Fixes:")
        lines += [f"  {i}. {fx.summary}\n     trade-off: {fx.tradeoff}" for i, fx in enumerate(h.fixes, 1)]
    if h.evidence:
        lines.append("Evidence:")
        lines += [f"  - {e}" for e in h.evidence]
    if h.repro_test:
        lines += ["Repro test:", textwrap.indent(h.repro_test.rstrip(), "    ")]
    return lines


def render_text(d: Diagnosis, limit: int = 3) -> str:
    if d.top is None:
        return "No stack trace found."
    lines = _hyp_block(d.top)
    others = d.hypotheses[1:limit]
    if others:
        lines.append("Other hypotheses:")
        lines += [f"  - {h.pattern_id} ({h.confidence:.0%})"
                  f"{' in ' + h.service if h.service else ''}: {h.error_type}" for h in others]
    if d.notes:
        lines.append("Notes:")
        lines += [f"  - {n}" for n in d.notes]
    return "\n".join(lines)


def _h(h: Hypothesis) -> dict:
    return {
        "pattern_id": h.pattern_id, "family": h.family.value, "category": h.category,
        "confidence": h.confidence, "service": h.service, "error_type": h.error_type,
        "message": h.message, "root_cause": h.root_cause,
        "fixes": [{"summary": f.summary, "tradeoff": f.tradeoff} for f in h.fixes],
        "locations": [{"file": f.file, "line": f.line, "function": f.function, "module": f.module}
                      for f in h.locations],
        "repro_test": h.repro_test, "tags": list(h.tags), "evidence": list(h.evidence),
    }


def render_json(d: Diagnosis) -> str:
    return json.dumps({
        "families": sorted(f.value for f in d.families),
        "hypotheses": [_h(h) for h in d.hypotheses],
        "notes": list(d.notes),
    }, indent=2)
```

- [ ] **Step 7: Implement `cli.py`**

```python
import sys
from pathlib import Path
from typing import Optional
import typer
from debugagent.orchestrator import diagnose as run_diagnose
from debugagent.patterns.loader import PatternError
from debugagent.render import render_json, render_text
from debugagent.subagent import build_subagents

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.callback()
def main() -> None:
    """Debug Agent: diagnose stack traces across JVM, Python, Node, Go, and Rust services."""


def _read_input(source: Optional[str]) -> str:
    if source in (None, "-"):
        data = sys.stdin.buffer.read() if hasattr(sys.stdin, "buffer") else sys.stdin.read().encode()
    else:
        p = Path(source)
        if not p.is_file():
            typer.echo(f"Input file not found: {source}", err=True)
            raise typer.Exit(2)
        data = p.read_bytes()
    text = data.decode("utf-8", errors="replace")
    if not text.strip():
        typer.echo("No input: pass a file path or pipe a stack trace on stdin.", err=True)
        raise typer.Exit(2)
    return text


@app.command()
def diagnose(
    source: Optional[str] = typer.Argument(None, help="File containing a trace/log; '-' or omitted reads stdin"),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON"),
    patterns: list[Path] = typer.Option([], "--patterns", help="Extra pattern directories"),
) -> None:
    """Diagnose a stack trace or error log."""
    text = _read_input(source)
    try:
        subagents = build_subagents(patterns)
    except PatternError as e:
        typer.echo(f"Pattern database error: {e}", err=True)
        raise typer.Exit(1)
    d = run_diagnose(text, subagents)
    if d.top is None:
        typer.echo("No stack trace found in input (supported: JVM, Python, Node, Go, Rust).", err=True)
        raise typer.Exit(2)
    typer.echo(render_json(d) if json_out else render_text(d))
```

Note: `CliRunner` in typer ≥0.12 mixes stderr into `r.output`, and the tests check `r.output`. If your typer version separates stderr, construct the runner with `CliRunner(mix_stderr=True)`.

- [ ] **Step 8: Run to verify pass**

Run: `pytest -v`
Expected: PASS. Then try it by hand: `debugagent diagnose tests/data/python_none.txt`

- [ ] **Step 9: Commit**

```bash
git add -A && git commit -m "feat: diagnose CLI end-to-end for python with text/json output"
```

### Task 4: JVM parser (Java, Kotlin, Scala) and JVM patterns

**Files:**
- Create: `src/debugagent/parsers/jvm.py`, `src/debugagent/patterns/data/jvm/*.yaml` (14 files)
- Modify: `src/debugagent/parsers/__init__.py` (register `Family.JVM: jvm.parse`)
- Test: `tests/parsers/test_jvm.py`, `tests/patterns/test_jvm_patterns.py`, `tests/data/jvm_chained.txt`

**Interfaces:**
- Consumes: `Family`, `Frame`, and `ParsedTrace` (Task 1); `match_trace`, `load_patterns`, and `DEFAULT_PATTERN_DIR` (Task 2).
- Produces: `parsers.jvm.parse(text: str) -> list[ParsedTrace]`. Frames are innermost first. `Frame.module` holds the fully-qualified class, `Frame.function` holds `Class.method`, and `Frame.file` holds the source file name (e.g. `Orders.java`). The outermost exception comes first and `Caused by:` segments form the `.cause` chain.

- [ ] **Step 1: Write the failing tests**

`tests/data/jvm_chained.txt`:
```
2026-09-26T10:00:01Z ERROR [orders] Request failed
org.springframework.web.util.NestedServletException: Request processing failed; nested exception is java.lang.IllegalStateException: pricing failed
	at org.springframework.web.servlet.FrameworkServlet.processRequest(FrameworkServlet.java:1014)
	at com.acme.orders.api.OrderController.place(OrderController.kt:31)
Caused by: java.lang.IllegalStateException: pricing failed
	at com.acme.orders.pricing.Pricer.price(Pricer.java:55)
	... 12 more
Caused by: java.lang.NullPointerException: Cannot invoke "String.length()" because "customer.name" is null
	at com.acme.orders.pricing.Discounts.forName(Discounts.java:18)
	at com.acme.orders.pricing.Pricer.price(Pricer.java:52)
	at java.base/java.util.Optional.map(Optional.java:260)
	... 12 more
```

`tests/parsers/test_jvm.py`:
```python
from debugagent.detect import normalize
from debugagent.models import Family
from debugagent.parsers.jvm import parse

CHAINED = normalize(open("tests/data/jvm_chained.txt").read())

def test_outer_and_chain():
    [t] = parse(CHAINED)
    assert t.family is Family.JVM
    assert t.error_type == "org.springframework.web.util.NestedServletException"
    assert t.cause.error_type == "java.lang.IllegalStateException"
    root = t.root()
    assert root.error_type == "java.lang.NullPointerException"
    assert root.message.startswith('Cannot invoke "String.length()"')

def test_frames_innermost_first_with_module_and_function():
    root = parse(CHAINED)[0].root()
    f = root.frames[0]
    assert (f.file, f.line, f.function, f.module) == (
        "Discounts.java", 18, "Discounts.forName", "com.acme.orders.pricing.Discounts")

def test_java_base_module_prefix_is_stripped():
    root = parse(CHAINED)[0].root()
    assert root.frames[2].module == "java.util.Optional"

def test_native_and_unknown_source_frames():
    text = ('Exception in thread "main" java.lang.StackOverflowError\n'
            "\tat java.lang.Object.hashCode(Native Method)\n"
            "\tat com.acme.Tree.walk(Unknown Source)\n")
    [t] = parse(text)
    assert t.error_type == "java.lang.StackOverflowError" and t.message == ""
    assert t.frames[0].line is None and t.frames[1].function == "Tree.walk"

def test_kotlin_and_scala_frames():
    text = ("java.lang.ClassCastException: class A cannot be cast to class B\n"
            "\tat com.acme.Svc.run(Svc.kt:3)\n\tat com.acme.Job.go(Job.scala:9)\n")
    [t] = parse(text)
    assert [f.file for f in t.frames] == ["Svc.kt", "Job.scala"]

def test_two_independent_traces():
    one = "java.lang.IllegalArgumentException: bad\n\tat com.acme.A.b(A.java:1)\n"
    assert len(parse(one + "INFO something\n" + one)) == 2

def test_exception_name_in_plain_log_line_without_frames_is_ignored():
    assert parse("WARN retrying after java.io.IOException: reset\nINFO ok\n") == []
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/parsers/test_jvm.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'debugagent.parsers.jvm'`

- [ ] **Step 3: Implement `parsers/jvm.py`**

```python
import re
from debugagent.models import Family, Frame, ParsedTrace

_HEADER = re.compile(
    r'^(?P<caused>Caused by:\s*)?(?:Exception in thread "[^"]*"\s+)?'
    r"(?P<type>(?:[a-z_$][\w$]*\.)+[A-Z][\w$]*(?:Exception|Error|Throwable|Failure)[\w$]*)"
    r"(?::\s?(?P<msg>.*))?\s*$"
)
_FRAME = re.compile(
    r"^\s*at (?:[\w.-]+/)?(?P<qual>[\w$.<>]+)\.(?P<method>[\w$<>-]+)"
    r"\((?P<file>[^:()]+)(?::(?P<line>\d+))?\)"
)
_MORE = re.compile(r"^\s*\.\.\. \d+ (?:more|common frames omitted)")
_SUPPRESSED = re.compile(r"^\s*Suppressed:")


def _fold(segments: list[tuple[str, str, list[Frame]]]) -> ParsedTrace:
    cause = None
    for etype, msg, frames in reversed(segments):
        cause = ParsedTrace(Family.JVM, etype, msg, tuple(frames), cause=cause)
    return cause


def parse(text: str) -> list[ParsedTrace]:
    results: list[ParsedTrace] = []
    segments: list[tuple[str, str, list[Frame]]] = []
    in_suppressed = False

    def flush() -> None:
        if segments and any(fr for _, _, fr in segments):
            results.append(_fold(segments))
        segments.clear()

    for line in text.split("\n"):
        if _SUPPRESSED.match(line):
            in_suppressed = True
            continue
        fm = _FRAME.match(line)
        if fm:
            if segments and not in_suppressed:
                cls = fm["qual"]
                segments[-1][2].append(Frame(
                    file=fm["file"], line=int(fm["line"]) if fm["line"] else None,
                    function=f"{cls.rsplit('.', 1)[-1]}.{fm['method']}", module=cls,
                ))
            continue
        if _MORE.match(line):
            continue
        hm = _HEADER.match(line.strip())
        if hm:
            if hm["caused"] and segments:
                in_suppressed = False
                segments.append((hm["type"], (hm["msg"] or "").strip(), []))
            else:
                flush()
                in_suppressed = False
                segments.append((hm["type"], (hm["msg"] or "").strip(), []))
            continue
        if line.strip():
            flush()          # any other non-empty line ends the current trace
    flush()
    return results
```

- [ ] **Step 4: Register the parser** in `parsers/__init__.py`:

```python
from debugagent.parsers import jvm, python

PARSERS = {
    Family.PYTHON: python.parse,
    Family.JVM: jvm.parse,
}
```

- [ ] **Step 5: Run parser tests to verify pass**

Run: `pytest tests/parsers/test_jvm.py -v`
Expected: PASS (7 tests)

- [ ] **Step 6: Add the 14 JVM patterns** in `src/debugagent/patterns/data/jvm/<slug>.yaml`, in the same YAML shape as Task 2. `error_type` is matched against both the fully-qualified and the short name.

| file slug | error_type | message_regex | category | conf | tags | root_cause | fixes (tradeoff) |
|---|---|---|---|---|---|---|---|
| npe.helpful | `NullPointerException` | `because ".+" is null\|Cannot invoke` | code | 0.9 | [null] | Null dereference; the JDK 14+ message names the exact null expression, so start there | Null-check that expression where it's produced (local; may hide the upstream cause) · Model it as `Optional`/`@NonNull` and validate at the boundary (removes the bug class; wider change) |
| npe | `NullPointerException` | | code | 0.8 | [null] | Null dereference at the top app frame; commonly an unchecked return value, an uninitialized field, or unboxing a null wrapper | Add `-XX:+ShowCodeDetailsInExceptionMessages` (JDK 14+ default) to name the null expression (diagnostic only) · Add `Objects.requireNonNull` at the boundary (fails fast; more checks) |
| optional_get_empty | `NoSuchElementException` | `No value present` | code | 0.9 | [null, optional] | `Optional.get()`/`orElseThrow()` called on an empty Optional: unchecked Optional usage | Replace with `orElse`/`orElseGet`/`ifPresent` (safe; must pick a default) · Throw a domain exception with context via `orElseThrow(() -> ...)` (clear error; still fails) |
| class_cast | `ClassCastException` | | code | 0.8 | [types] | Wrong runtime type, often from raw generics, deserialization into `Object`, or two classloaders | Use typed generics / typed deserialization (correct; refactor) · Guard with `instanceof` pattern matching (local; may hide bad data) |
| pool_exhausted | `SQLTransientConnectionException\|ConnectionPoolTimeoutException\|PoolExhaustedException\|CannotGetJdbcConnectionException` | `not available\|pool\|timed? ?out` | resource | 0.85 | [pool, leak] | Connection pool exhausted: connections are leaked (unclosed) or held during slow calls, or the pool is undersized for the load | Find the leak with `leakDetectionThreshold` and use try-with-resources (root fix; needs investigation) · Raise the pool size and set a connection timeout (fast relief; can overload the DB) |
| socket_timeout | `SocketTimeoutException\|ReadTimeoutException\|TimeoutException\|ResourceAccessException` | | dependency | 0.75 | [timeout] | A downstream call exceeded its timeout; the fault is usually in the callee | Set explicit connect/read timeouts with retry+backoff (quick; can amplify load) · Fix callee latency and add a circuit breaker (root fix; cross-team) |
| connection_refused | `ConnectException\|HttpHostConnectException` | `Connection refused` | dependency | 0.8 | [connectivity] | The target isn't listening: down, wrong host/port, or not ready | Check service discovery / config for host+port (config fix) · Add startup readiness/retry (resilient; slower start) |
| oom | `OutOfMemoryError` | `Java heap space\|GC overhead\|Metaspace\|Direct buffer` | resource | 0.85 | [memory, leak] | Heap or metaspace exhausted: a leak (unbounded cache/collection, classloader leak) or undersized `-Xmx` | Take a heap dump (`-XX:+HeapDumpOnOutOfMemoryError`) and fix the retaining path (root fix; takes time) · Raise `-Xmx` / container memory (fast; delays recurrence) |
| concurrent_modification | `ConcurrentModificationException` | | code | 0.85 | [concurrency] | A collection was modified while being iterated (same thread via a for-each remove, or another thread) | Use `Iterator.remove()` / `removeIf` (simple; single-thread only) · Use a concurrent collection or copy before iterating (thread-safe; memory/perf cost) |
| stack_overflow | `StackOverflowError` | | code | 0.85 | [recursion] | Unbounded recursion, often cyclic object graphs in `toString`/`equals`/JSON serialization (bidirectional JPA relations) | Break the cycle (`@JsonIgnore`/`@ToString.Exclude`) (targeted; needs the cycle found) · Convert the recursion to iteration (robust; refactor) |
| spring_missing_bean | `NoSuchBeanDefinitionException\|UnsatisfiedDependencyException` | | config | 0.85 | [spring, config] | Spring couldn't wire a dependency: missing `@Component`/`@Bean`, a package outside the component scan, or an inactive profile | Add the bean definition or fix the scan package (correct; code change) · Activate the right profile / conditional property (config only; environment-specific) |
| datetime_parse | `DateTimeParseException` | | code | 0.8 | [timezone, parsing] | Date/time string doesn't match the formatter; typically timezone offsets or locale-specific formats from another service | Use ISO-8601 with an offset end-to-end (`OffsetDateTime`) (robust; contract change) · Add a lenient multi-format parser at the boundary (tolerant; masks drift) |
| index_out_of_bounds | `IndexOutOfBoundsException\|ArrayIndexOutOfBoundsException\|StringIndexOutOfBoundsException` | | code | 0.8 | [off-by-one, empty] | Off-by-one error, or code assumed a non-empty list/string | Check bounds/emptiness first (local) · Use iteration/stream APIs instead of indices (removes the bug class; refactor) |
| illegal_argument_state | `IllegalArgumentException\|IllegalStateException` | | code | 0.5 | [precondition] | A precondition check failed; the message and the throwing frame say which invariant broke | Fix the caller that violates the precondition (correct; requires tracing the caller) · Relax the precondition if it's over-strict (fast; risk of bad state) |

- [ ] **Step 7: Write the per-pattern golden test** — `tests/patterns/test_jvm_patterns.py`

```python
import pytest
from debugagent.models import Family, Frame, ParsedTrace
from debugagent.patterns.loader import load_patterns, DEFAULT_PATTERN_DIR
from debugagent.patterns.matcher import match_trace

PATS = load_patterns(DEFAULT_PATTERN_DIR)
F = (Frame("Orders.java", 10, "Orders.place", "com.acme.Orders"),)

@pytest.mark.parametrize("etype,msg,expected", [
    ("java.lang.NullPointerException", 'Cannot invoke "String.length()" because "n" is null', "jvm.npe.helpful"),
    ("java.lang.NullPointerException", "", "jvm.npe"),
    ("java.util.NoSuchElementException", "No value present", "jvm.optional_get_empty"),
    ("java.lang.ClassCastException", "class A cannot be cast to class B", "jvm.class_cast"),
    ("java.sql.SQLTransientConnectionException", "HikariPool-1 - Connection is not available, request timed out after 30000ms.", "jvm.pool_exhausted"),
    ("java.net.SocketTimeoutException", "Read timed out", "jvm.socket_timeout"),
    ("java.net.ConnectException", "Connection refused", "jvm.connection_refused"),
    ("java.lang.OutOfMemoryError", "Java heap space", "jvm.oom"),
    ("java.util.ConcurrentModificationException", "", "jvm.concurrent_modification"),
    ("java.lang.StackOverflowError", "", "jvm.stack_overflow"),
    ("org.springframework.beans.factory.NoSuchBeanDefinitionException", "No qualifying bean of type 'X'", "jvm.spring_missing_bean"),
    ("java.time.format.DateTimeParseException", "Text '2026-09-26T10:00' could not be parsed", "jvm.datetime_parse"),
    ("java.lang.ArrayIndexOutOfBoundsException", "Index 3 out of bounds for length 3", "jvm.index_out_of_bounds"),
    ("java.lang.IllegalStateException", "not started", "jvm.illegal_argument_state"),
])
def test_each_jvm_pattern_matches(etype, msg, expected):
    h = match_trace(ParsedTrace(Family.JVM, etype, msg, F), PATS)
    assert h.pattern_id == expected and 2 <= len(h.fixes) <= 3 and "@Test" in h.repro_test

# Review Focus #2 for JVM: wrapper exceptions resolve to the innermost cause
def test_chained_fixture_diagnoses_root_npe():
    from debugagent.detect import normalize
    from debugagent.parsers.jvm import parse
    [t] = parse(normalize(open("tests/data/jvm_chained.txt").read()))
    h = match_trace(t, PATS)
    assert h.pattern_id == "jvm.npe.helpful"
    assert h.locations[0].function == "Discounts.forName"   # library frames skipped
```

- [ ] **Step 8: Run all tests to verify pass**

Run: `pytest -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add -A && git commit -m "feat: JVM parser (java/kotlin/scala) with cause chains and 14 JVM patterns"
```

### Task 5: Node parser (JavaScript, TypeScript) and Node patterns

**Files:**
- Create: `src/debugagent/parsers/node.py`, `src/debugagent/patterns/data/node/*.yaml` (12 files)
- Modify: `src/debugagent/parsers/__init__.py` (register `Family.NODE`) and `src/debugagent/detect.py` (Node signature also matches the V8 fatal heap OOM line, which has no frames)
- Test: `tests/parsers/test_node.py`, `tests/patterns/test_node_patterns.py`, `tests/data/node_cause.txt`

**Interfaces:**
- Consumes: Task 1 and Task 2 types and functions.
- Produces: `parsers.node.parse(text: str) -> list[ParsedTrace]`. Frames are innermost first. `[cause]:` blocks form the `.cause` chain. `Error [CODE]: msg` is parsed to `error_type="Error"` and `message="[CODE] msg"`. The V8 heap OOM becomes `error_type="FatalError"`.

- [ ] **Step 1: Write the failing tests**

`tests/data/node_cause.txt`:
```
Error: failed to load user 42
    at loadUser (/srv/web/src/users.ts:20:11)
    at async handler (/srv/web/src/api.ts:30:5) {
  [cause]: TypeError: fetch failed
      at node:internal/deps/undici/undici:13185:13
      at async fetchUser (/srv/web/src/client.ts:8:15) {
    [cause]: Error: connect ECONNREFUSED 10.0.3.7:8080
        at TCPConnectWrap.afterConnect [as oncomplete] (node:net:1606:16) {
      errno: -111,
      code: 'ECONNREFUSED',
      syscall: 'connect',
      address: '10.0.3.7',
      port: 8080
    }
  }
}
```

`tests/parsers/test_node.py`:
```python
from debugagent.detect import detect_families
from debugagent.models import Family
from debugagent.parsers.node import parse

def test_simple_typeerror_frames_and_anonymous():
    text = ("TypeError: Cannot read properties of undefined (reading 'id')\n"
            "    at getUser (/srv/web/src/users.ts:14:22)\n"
            "    at Layer.handle [as handle_request] (/srv/web/node_modules/express/lib/router/layer.js:95:5)\n"
            "    at /srv/web/src/anon.js:3:1\n")
    [t] = parse(text)
    assert (t.error_type, t.message) == ("TypeError", "Cannot read properties of undefined (reading 'id')")
    assert t.frames[0].function == "getUser" and t.frames[0].line == 14
    assert t.frames[2].function == "<anonymous>" and t.frames[2].file == "/srv/web/src/anon.js"

def test_cause_chain_root_is_econnrefused():
    [t] = parse(open("tests/data/node_cause.txt").read())
    assert t.message == "failed to load user 42"
    assert t.cause.error_type == "TypeError"
    assert t.root().message == "connect ECONNREFUSED 10.0.3.7:8080"

def test_error_code_bracket_is_kept_in_message():
    text = ("Error [ERR_MODULE_NOT_FOUND]: Cannot find package 'zod' imported from /srv/web/src/a.mjs\n"
            "    at new NodeError (node:internal/errors:405:5)\n")
    [t] = parse(text)
    assert t.error_type == "Error" and t.message.startswith("[ERR_MODULE_NOT_FOUND] Cannot find package")

def test_cjs_loader_preamble_then_error():
    text = ("node:internal/modules/cjs/loader:1080\n  throw err;\n  ^\n\n"
            "Error: Cannot find module 'express'\nRequire stack:\n- /srv/web/src/index.js\n"
            "    at Module._resolveFilename (node:internal/modules/cjs/loader:1077:15)\n")
    [t] = parse(text)
    assert t.message == "Cannot find module 'express'"

def test_heap_oom_without_frames():
    text = "FATAL ERROR: Reached heap limit Allocation failed - JavaScript heap out of memory\n"
    assert detect_families(text) == {Family.NODE}
    [t] = parse(text)
    assert t.error_type == "FatalError" and "heap out of memory" in t.message

def test_error_line_without_frames_is_ignored():
    assert parse("Error: something happened\nINFO fine\n") == []

def test_unhandled_rejection_without_frames_is_kept():
    text = ("node:internal/process/promises:288\n    triggerUncaughtException(err, true);\n    ^\n\n"
            '[UnhandledPromiseRejection: This error originated either by throwing inside of an async '
            'function without a catch block. The promise rejected with the reason "oops".] {\n'
            "  code: 'ERR_UNHANDLED_REJECTION'\n}\n")
    assert detect_families(text) == {Family.NODE}
    [t] = parse(text)
    assert t.error_type == "UnhandledPromiseRejection"
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/parsers/test_node.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'debugagent.parsers.node'`

- [ ] **Step 3: Implement `parsers/node.py`**

```python
import re
from debugagent.models import Family, Frame, ParsedTrace

_TYPE = r"(?P<type>(?:[A-Z]\w*)?(?:Error|Exception)|UnhandledPromiseRejection)"
_HEADER = re.compile(rf"^(?:Uncaught\s+)?\[?{_TYPE}(?: \[(?P<code>[A-Z0-9_]+)\])?:\s?(?P<msg>.*?)\]?\s*(?:\{{)?\s*$")
_CAUSE = re.compile(rf"^\s*\[cause\]:\s*{_TYPE}(?: \[(?P<code>[A-Z0-9_]+)\])?:\s?(?P<msg>.*?)\s*(?:\{{)?\s*$")
_FRAME = re.compile(
    r"^\s*at (?:async )?(?:(?P<func>.+?) \()?(?:file://)?(?P<file>[^\s()]+?):(?P<line>\d+):(?P<col>\d+)\)?\s*(?:\{)?\s*$"
)
_FATAL = re.compile(r"^FATAL ERROR: (?P<msg>.*heap out of memory.*)$")
_IGNORABLE = re.compile(r"^\s*(?:[{}\]]|\w+: .*,?|- .*|Require stack:)\s*$")


def _msg(m: re.Match[str]) -> str:
    msg = (m["msg"] or "").strip()
    return f"[{m['code']}] {msg}" if m["code"] else msg


def _fold(segs: list[tuple[str, str, list[Frame]]]) -> ParsedTrace:
    cause = None
    for etype, msg, frames in reversed(segs):
        cause = ParsedTrace(Family.NODE, etype, msg, tuple(frames), cause=cause)
    return cause


def parse(text: str) -> list[ParsedTrace]:
    results: list[ParsedTrace] = []
    segs: list[tuple[str, str, list[Frame]]] = []

    def flush() -> None:
        # Node prints unhandled rejections with no frames, so keep them anyway
        if segs and (segs[0][2] or segs[0][0] == "UnhandledPromiseRejection"):
            results.append(_fold(segs))
        segs.clear()

    for line in text.split("\n"):
        fm = _FRAME.match(line)
        if fm:
            if segs:
                segs[-1][2].append(Frame(fm["file"], int(fm["line"]), (fm["func"] or "<anonymous>").strip()))
            continue
        cm = _CAUSE.match(line)
        if cm and segs:
            segs.append((cm["type"], _msg(cm), []))
            continue
        fatal = _FATAL.match(line.strip())
        if fatal:
            flush()
            results.append(ParsedTrace(Family.NODE, "FatalError", fatal["msg"].strip(), ()))
            continue
        hm = _HEADER.match(line.strip())
        if hm:
            flush()
            segs.append((hm["type"], _msg(hm), []))
            continue
        if not line.strip() or (segs and _IGNORABLE.match(line)):
            continue
        flush()
    flush()
    return results
```

- [ ] **Step 4: Register the parser and extend detection**

In `parsers/__init__.py`, import `node` and add `Family.NODE: node.parse`. In `detect.py`, replace the Node signature with:
```python
    Family.NODE: re.compile(
        r"^\s*at (?:.+ \()?(?:file://)?[^\s()]+\.(?:js|mjs|cjs|ts|tsx|jsx):\d+:\d+\)?\s*(?:\{)?\s*$"
        r"|^FATAL ERROR: .*heap out of memory|^\[UnhandledPromiseRejection: ", re.M),
```

- [ ] **Step 5: Run to verify pass**

Run: `pytest tests/parsers/test_node.py tests/test_detect.py -v`
Expected: PASS

- [ ] **Step 6: Add the 12 Node patterns** in `src/debugagent/patterns/data/node/<slug>.yaml` (same YAML shape)

| file slug | error_type | message_regex | category | conf | tags | root_cause | fixes (tradeoff) |
|---|---|---|---|---|---|---|---|
| undefined_property | `TypeError` | `Cannot read propert(y\|ies) of (undefined\|null)` | code | 0.85 | [null] | A property was read from `undefined`/`null`: missing API field, un-awaited Promise, or an empty lookup | Use optional chaining with an explicit fallback (local; may hide bad data) · Validate the response with a schema (zod) at the boundary (fails early; more code) |
| not_a_function | `TypeError` | `is not a function` | code | 0.8 | [api-drift, import] | Called a non-function: default vs named import mixup, ESM/CJS interop, or a library API change | Fix the import form (`import x` vs `import { x }`) (targeted) · Pin the library version with the expected API (fast; defers upgrade) |
| reference_error | `ReferenceError` | `is not defined` | code | 0.8 | [typo, scoping] | Identifier not in scope: a typo, a missing import, or a browser-only global used on the server | Add the import/declaration (simple) · Enable `no-undef` + TypeScript strict to catch it at build time (prevents recurrence; config work) |
| econnrefused | `Error` | `ECONNREFUSED` | dependency | 0.85 | [connectivity] | Nothing is listening at the target: the dependency is down, the host/port is wrong, or it isn't ready | Check service discovery / env config for host+port (config fix) · Add retry with backoff + a readiness gate (resilient; slower failure) |
| timeout | `Error\|FetchError\|AxiosError\|TimeoutError\|AbortError` | `ETIMEDOUT\|ESOCKETTIMEDOUT\|timeout of \d+ms exceeded\|aborted due to timeout\|operation was aborted` | dependency | 0.75 | [timeout] | A downstream call exceeded its timeout; the fault is usually in the callee | Tune the timeout and add retries with jitter (quick; can amplify load) · Fix callee latency / add a circuit breaker (root fix; cross-team) |
| econnreset | `Error` | `ECONNRESET\|socket hang up` | dependency | 0.75 | [connectivity, keepalive] | The peer closed the connection: keep-alive timeout mismatch, a proxy idle timeout, or the callee crashing mid-request | Align keep-alive timeouts (client < server) (targeted; needs both configs) · Retry idempotent requests on reset (resilient; unsafe for non-idempotent calls) |
| module_not_found | `Error` | `Cannot find module\|ERR_MODULE_NOT_FOUND\|Cannot find package` | config | 0.85 | [import, deploy] | A dependency is missing from the deployed image, the path is wrong, or ESM needs an explicit file extension | Add it to `dependencies` (not `devDependencies`) and rebuild (correct; redeploy) · Fix the import path/extension (targeted) |
| json_parse | `SyntaxError` | `JSON\|Unexpected token` | dependency | 0.8 | [parsing] | `JSON.parse` got a non-JSON body, usually an HTML error page or an empty response from upstream | Check `res.ok` and content-type before parsing (clear errors) · Log the truncated raw body on failure (diagnosable; log volume) |
| max_call_stack | `RangeError` | `Maximum call stack size exceeded` | code | 0.85 | [recursion] | Unbounded recursion, often a circular structure or a setter/getter calling itself | Add a base case / cycle guard (root fix) · Convert to iteration (robust; refactor) |
| eaddrinuse | `Error` | `EADDRINUSE` | config | 0.9 | [port] | The port is already in use: a duplicate process, the previous instance didn't exit, or a port clash in config | Make the port configurable and unique per service (clean; config change) · Handle SIGTERM for graceful shutdown (prevents recurrence; code change) |
| heap_oom | `FatalError` | `heap out of memory` | resource | 0.85 | [memory, leak] | The V8 heap limit was hit: a leak (unbounded cache/listeners) or a genuinely large working set | Take a heap snapshot and fix the retaining path (root fix; takes time) · Raise `--max-old-space-size` to match the container (fast; delays recurrence) |
| unhandled_rejection | `UnhandledPromiseRejection\|Error` | `UnhandledPromiseRejection\|unhandled promise rejection\|ERR_UNHANDLED_REJECTION\|originated either by throwing inside of an async function` | code | 0.7 | [async] | A Promise rejected with no `.catch`/`try` around the `await`; since Node 15 this crashes the process | Add `try/catch` around the awaited call or `.catch` on the chain (targeted) · Enable `@typescript-eslint/no-floating-promises` (prevents recurrence; lint churn) |

- [ ] **Step 7: Write the per-pattern golden test** — `tests/patterns/test_node_patterns.py`

```python
import pytest
from debugagent.models import Family, Frame, ParsedTrace
from debugagent.parsers.node import parse
from debugagent.patterns.loader import load_patterns, DEFAULT_PATTERN_DIR
from debugagent.patterns.matcher import match_trace

PATS = load_patterns(DEFAULT_PATTERN_DIR)
F = (Frame("/srv/web/src/api.ts", 3, "handler"),)

@pytest.mark.parametrize("etype,msg,expected", [
    ("TypeError", "Cannot read properties of undefined (reading 'id')", "node.undefined_property"),
    ("TypeError", "client.fetchUser is not a function", "node.not_a_function"),
    ("ReferenceError", "window is not defined", "node.reference_error"),
    ("Error", "connect ECONNREFUSED 10.0.3.7:8080", "node.econnrefused"),
    ("AxiosError", "timeout of 5000ms exceeded", "node.timeout"),
    ("Error", "socket hang up", "node.econnreset"),
    ("Error", "Cannot find module 'express'", "node.module_not_found"),
    ("SyntaxError", "Unexpected token '<', \"<!DOCTYPE \"... is not valid JSON", "node.json_parse"),
    ("RangeError", "Maximum call stack size exceeded", "node.max_call_stack"),
    ("Error", "listen EADDRINUSE: address already in use :::3000", "node.eaddrinuse"),
    ("FatalError", "Reached heap limit Allocation failed - JavaScript heap out of memory", "node.heap_oom"),
    ("Error", "[ERR_UNHANDLED_REJECTION] This error originated either by throwing inside of an async function", "node.unhandled_rejection"),
])
def test_each_node_pattern_matches(etype, msg, expected):
    h = match_trace(ParsedTrace(Family.NODE, etype, msg, F), PATS)
    assert h.pattern_id == expected and 2 <= len(h.fixes) <= 3 and h.repro_test

def test_cause_fixture_diagnoses_root_econnrefused():
    [t] = parse(open("tests/data/node_cause.txt").read())
    assert match_trace(t, PATS).pattern_id == "node.econnrefused"
```

- [ ] **Step 8: Run all tests to verify pass**

Run: `pytest -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add -A && git commit -m "feat: node parser (js/ts) with [cause] chains and 12 node patterns"
```

### Task 6: Go parser and Go patterns

**Files:**
- Create: `src/debugagent/parsers/go.py`, `src/debugagent/patterns/data/go/*.yaml` (14 files)
- Modify: `src/debugagent/parsers/__init__.py` (register `Family.GO`)
- Test: `tests/parsers/test_go.py`, `tests/patterns/test_go_patterns.py`

**Interfaces:**
- Consumes: Task 1 and Task 2 types and functions.
- Produces: `parsers.go.parse(text: str) -> list[ParsedTrace]`. `error_type` is one of `"runtime error"` (`panic: runtime error: …`), `"fatal error"` (`fatal error: …`), or `"panic"` (any other `panic: …`). The message is the text after that prefix, without a trailing `!` or ` [recovered]`. Frames come from the **first** goroutine block only (the panicking goroutine), innermost first, with the function name stripped of its argument list.

- [ ] **Step 1: Write the failing tests** — `tests/parsers/test_go.py`

```python
from debugagent.detect import normalize
from debugagent.parsers.go import parse

NIL = """panic: runtime error: invalid memory address or nil pointer dereference
[signal SIGSEGV: segmentation violation code=0x1 addr=0x0 pc=0x4a1b2c]

goroutine 7 [running]:
main.(*Store).Get(0x0, {0x4c3e2a, 0x3})
\t/srv/inventory/store.go:42 +0x1c
main.handler(...)
\t/srv/inventory/main.go:18
created by net/http.(*Server).Serve in goroutine 1
\t/usr/local/go/src/net/http/server.go:3086 +0x5cb

goroutine 1 [IO wait]:
internal/poll.runtime_pollWait(0x7f, 0x72)
\t/usr/local/go/src/runtime/netpoll.go:343 +0x85
exit status 2
"""

DEADLOCK = """fatal error: all goroutines are asleep - deadlock!

goroutine 1 [chan receive]:
main.main()
\t/srv/inventory/main.go:9 +0x2d
"""

def test_runtime_error_nil_deref():
    [t] = parse(NIL)
    assert (t.error_type, t.message) == ("runtime error", "invalid memory address or nil pointer dereference")
    assert [f.function for f in t.frames] == ["main.(*Store).Get", "main.handler"]
    assert t.frames[0].file == "/srv/inventory/store.go" and t.frames[0].line == 42

def test_only_first_goroutine_and_created_by_skipped():
    [t] = parse(NIL)
    assert all("netpoll" not in f.file and "server.go" not in f.file for f in t.frames)

def test_fatal_error_deadlock():
    [t] = parse(DEADLOCK)
    assert (t.error_type, t.message) == ("fatal error", "all goroutines are asleep - deadlock")
    assert t.frames[0].function == "main.main"

def test_custom_panic_and_recovered_suffix():
    text = "panic: interface conversion: interface {} is string, not int [recovered]\n\npanic: again\n\ngoroutine 1 [running]:\nmain.f()\n\t/srv/a/f.go:3 +0x1\n"
    [t] = parse(text)
    assert t.error_type == "panic" and t.message == "interface conversion: interface {} is string, not int"

def test_log_prefixed_panic():
    wrapped = "\n".join(f"2026-09-26T10:00:00Z ERROR [inventory] {ln}" for ln in DEADLOCK.splitlines())
    [t] = parse(normalize(wrapped))
    assert t.frames[0].line == 9

def test_panic_word_in_log_without_goroutine_dump_is_ignored():
    assert parse("panic: this is just a log message\nINFO ok\n") == []
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/parsers/test_go.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'debugagent.parsers.go'`

- [ ] **Step 3: Implement `parsers/go.py`**

```python
import re
from debugagent.models import Family, Frame, ParsedTrace

_PANIC = re.compile(r"^panic: (?P<body>.*?)(?: \[recovered\])?\s*$")
_FATAL = re.compile(r"^fatal error: (?P<body>.*?)!?\s*$")
_GOROUTINE = re.compile(r"^goroutine \d+ \[[^\]]*\]:?\s*$")
_FILE = re.compile(r"^\s*(?P<file>\S+\.go):(?P<line>\d+)(?:\s+\+0x[0-9a-f]+)?\s*$")
_CREATED = re.compile(r"^\s*created by ")


def _func_name(s: str) -> str:
    i = s.rfind("(")
    return s[:i] if i > 0 and s.endswith(")") else s


def _classify(kind: str, body: str) -> tuple[str, str]:
    if kind == "fatal":
        return "fatal error", body
    if body.startswith("runtime error: "):
        return "runtime error", body[len("runtime error: "):]
    return "panic", body


def parse(text: str) -> list[ParsedTrace]:
    results: list[ParsedTrace] = []
    cur: dict | None = None          # {"etype", "msg", "frames", "state", "pending"}

    def flush() -> None:
        nonlocal cur
        if cur and cur["frames"]:
            results.append(ParsedTrace(Family.GO, cur["etype"], cur["msg"], tuple(cur["frames"])))
        cur = None

    for line in text.split("\n"):
        at_col0 = not line[:1].isspace()
        pm = _PANIC.match(line) if at_col0 else None
        fm = _FATAL.match(line) if at_col0 else None
        if pm or fm:
            if cur and cur["state"] == "await":
                continue            # nested panic before the dump: keep the first (original)
            flush()
            etype, msg = _classify("fatal" if fm else "panic", (fm or pm)["body"])
            cur = {"etype": etype, "msg": msg, "frames": [], "state": "await", "pending": None}
            continue
        if cur is None:
            continue
        if _GOROUTINE.match(line.strip()):
            if cur["state"] == "await":
                cur["state"] = "frames"
            else:
                flush()             # second goroutine block: stop
            continue
        if cur["state"] != "frames":
            continue
        if not line.strip():
            flush()
            continue
        fl = _FILE.match(line)
        if fl:
            if cur["pending"]:
                cur["frames"].append(Frame(fl["file"], int(fl["line"]), cur["pending"]))
            cur["pending"] = None
            continue
        cur["pending"] = None if _CREATED.match(line) else _func_name(line.strip())
    flush()
    return results
```

Register `Family.GO: go.parse` in `parsers/__init__.py`.

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/parsers/test_go.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Add the 14 Go patterns** in `src/debugagent/patterns/data/go/<slug>.yaml`

| file slug | error_type | message_regex | category | conf | tags | root_cause | fixes (tradeoff) |
|---|---|---|---|---|---|---|---|
| nil_pointer | `runtime error` | `nil pointer dereference` | code | 0.85 | [null] | A nil pointer was dereferenced: the value was used even though `err != nil`, a pointer/struct field was never initialized, or a nil receiver/interface was used | Check `err` before using the value and return early (idiomatic; local) · Construct via a `New…` func that guarantees non-nil fields (removes the bug class; API change) |
| index_out_of_range | `runtime error` | `index out of range` | code | 0.85 | [off-by-one, empty] | Index ≥ len: off-by-one, or code assumed a non-empty slice | Bounds/len check before indexing (local) · Range over the slice instead of indexing (removes the bug class; refactor) |
| slice_bounds | `runtime error` | `slice bounds out of range` | code | 0.85 | [off-by-one] | Slice expression exceeds len/cap, often from untrusted lengths in parsing | Clamp with `min(n, len(b))` (safe; may truncate silently) · Validate lengths at the parse boundary and return an error (correct; more code) |
| divide_by_zero | `runtime error` | `integer divide by zero` | code | 0.85 | [arithmetic] | Integer division by a zero divisor, typically an empty count or unset config | Guard the divisor and return an error (local) · Validate config at startup (fail fast; config contract) |
| deadlock | `fatal error` | `all goroutines are asleep - deadlock` | code | 0.9 | [concurrency, deadlock] | Every goroutine is blocked: an unbuffered send with no receiver, a missing `close`, or a `WaitGroup` count mismatch | Ensure every channel has a receiver/closer and `wg.Add` matches `Done` (root fix) · Use buffered channels or `select` with `ctx.Done()` (resilient; can hide logic bugs) |
| concurrent_map | `fatal error` | `concurrent map (writes\|read and map write\|iteration and map write)` | code | 0.95 | [concurrency, race] | Unsynchronized concurrent map access (a data race); run with `-race` to find the writers | Guard the map with `sync.RWMutex` (simple; contention) · Use `sync.Map` or shard ownership to a single goroutine (scales; different API) |
| stack_overflow | `fatal error` | `stack overflow` | code | 0.85 | [recursion] | Unbounded recursion, often a `String()`/`MarshalJSON` method that calls itself via `fmt`/`json` | Break the self-call (e.g. convert to an alias type inside `MarshalJSON`) (targeted) · Rewrite as iteration (robust; refactor) |
| oom | `fatal error` | `out of memory` | resource | 0.85 | [memory, leak] | The process exhausted memory: a goroutine leak, an unbounded buffer/cache, or a container limit that's too small | Profile with `pprof` heap/goroutine and fix the leak (root fix; takes time) · Set `GOMEMLIMIT` and raise the container limit (fast; delays recurrence) |
| interface_conversion | `panic` | `interface conversion` | code | 0.85 | [types] | Unchecked type assertion `x.(T)` on a value of a different dynamic type, typical after JSON decoding into `interface{}` | Use the two-value form `v, ok := x.(T)` (safe; must handle !ok) · Decode into typed structs instead of `interface{}` (removes the bug class; refactor) |
| send_closed_channel | `panic` | `send on closed channel` | code | 0.9 | [concurrency] | A sender wrote after the channel was closed; ownership of close is unclear | Only the sole sender closes; coordinate with `sync.Once`/context (correct; design change) · Stop senders via `ctx` before closing (safe shutdown; more plumbing) |
| close_closed_channel | `panic` | `close of (closed\|nil) channel` | code | 0.9 | [concurrency] | Double close (or close of a nil channel) from multiple shutdown paths | Wrap close in `sync.Once` (quick; masks unclear ownership) · Make a single owner responsible for closing (correct; refactor) |
| nil_map_write | `panic` | `assignment to entry in nil map` | code | 0.9 | [null] | Writing to a map that was declared but never `make`d, commonly a struct field | Initialize in the constructor / with `make` (simple) · Lazy-init in the method before writing (local; repeated checks) |
| deadline_exceeded | `panic` | `context deadline exceeded\|i/o timeout\|Client.Timeout exceeded` | dependency | 0.7 | [timeout] | A downstream call exceeded its context deadline and the error was `panic`ked instead of handled | Return the error and let the caller retry with backoff (correct; code change) · Increase the deadline for this call path (fast; may hide callee slowness) |
| connection_refused | `panic` | `connection refused` | dependency | 0.75 | [connectivity] | The dependency isn't listening (down/wrong address) and the startup code panics on the dial error | Retry the dial with backoff and a readiness probe (resilient; slower start) · Fix the address in config/service discovery (config fix) |

- [ ] **Step 6: Write the per-pattern golden test** — `tests/patterns/test_go_patterns.py`

```python
import pytest
from debugagent.models import Family, Frame, ParsedTrace
from debugagent.patterns.loader import load_patterns, DEFAULT_PATTERN_DIR
from debugagent.patterns.matcher import match_trace

PATS = load_patterns(DEFAULT_PATTERN_DIR)
F = (Frame("/srv/inventory/store.go", 42, "main.(*Store).Get"),)

@pytest.mark.parametrize("etype,msg,expected", [
    ("runtime error", "invalid memory address or nil pointer dereference", "go.nil_pointer"),
    ("runtime error", "index out of range [5] with length 3", "go.index_out_of_range"),
    ("runtime error", "slice bounds out of range [:5] with capacity 3", "go.slice_bounds"),
    ("runtime error", "integer divide by zero", "go.divide_by_zero"),
    ("fatal error", "all goroutines are asleep - deadlock", "go.deadlock"),
    ("fatal error", "concurrent map writes", "go.concurrent_map"),
    ("fatal error", "stack overflow", "go.stack_overflow"),
    ("fatal error", "runtime: out of memory", "go.oom"),
    ("panic", "interface conversion: interface {} is string, not int", "go.interface_conversion"),
    ("panic", "send on closed channel", "go.send_closed_channel"),
    ("panic", "close of closed channel", "go.close_closed_channel"),
    ("panic", "assignment to entry in nil map", "go.nil_map_write"),
    ("panic", "context deadline exceeded", "go.deadline_exceeded"),
    ("panic", "dial tcp 10.0.0.5:5432: connect: connection refused", "go.connection_refused"),
])
def test_each_go_pattern_matches(etype, msg, expected):
    h = match_trace(ParsedTrace(Family.GO, etype, msg, F), PATS)
    assert h.pattern_id == expected and 2 <= len(h.fixes) <= 3 and "func TestRepro_Get" in h.repro_test
```

- [ ] **Step 7: Run all tests to verify pass**

Run: `pytest -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add -A && git commit -m "feat: go panic/fatal parser and 14 go patterns"
```

### Task 7: Rust parser and Rust patterns

**Files:**
- Create: `src/debugagent/parsers/rust.py`, `src/debugagent/patterns/data/rust/*.yaml` (12 files)
- Modify: `src/debugagent/parsers/__init__.py` (register `Family.RUST`)
- Test: `tests/parsers/test_rust.py`, `tests/patterns/test_rust_patterns.py`

**Interfaces:**
- Consumes: Task 1 and Task 2 types and functions.
- Produces: `parsers.rust.parse(text: str) -> list[ParsedTrace]` with `error_type="panic"` and message = the panic payload's first line. It handles both the Rust ≥1.73 two-line format and the older single-line quoted format. If a `stack backtrace:` exists, frames are its entries that have an `at file:line` (innermost first, `::h<hash>` stripped). Otherwise there's a single frame `Frame(<panic file>, <line>, "<panic>")`.

- [ ] **Step 1: Write the failing tests** — `tests/parsers/test_rust.py`

```python
from debugagent.parsers.rust import parse

NEW = ("thread 'main' panicked at src/ledger.rs:27:18:\n"
       "called `Option::unwrap()` on a `None` value\n"
       "note: run with `RUST_BACKTRACE=1` environment variable to display a backtrace\n")
OLD = "thread 'main' panicked at 'called `Option::unwrap()` on a `None` value', src/ledger.rs:27:18\n"
BT = """thread 'tokio-runtime-worker' panicked at src/ledger.rs:27:18:
called `Result::unwrap()` on an `Err` value: Os { code: 111, kind: ConnectionRefused, message: "Connection refused" }
stack backtrace:
   0: rust_begin_unwind
             at /rustc/90c541806f23a127002de5b4038be731ba1458ca/library/std/src/panicking.rs:645:5
   1: core::panicking::panic_fmt
             at /rustc/90c541806f23a127002de5b4038be731ba1458ca/library/core/src/panicking.rs:72:14
   2: core::result::unwrap_failed
   3: ledger::post_entry::h0123456789abcdef
             at ./src/ledger.rs:27:18
   4: ledger::main
             at ./src/main.rs:9:5
note: Some details are omitted, run with `RUST_BACKTRACE=full` for a verbose backtrace.
"""

def test_new_format():
    [t] = parse(NEW)
    assert t.error_type == "panic" and t.message == "called `Option::unwrap()` on a `None` value"
    assert (t.frames[0].file, t.frames[0].line, t.frames[0].function) == ("src/ledger.rs", 27, "<panic>")

def test_old_format():
    [t] = parse(OLD)
    assert t.message == "called `Option::unwrap()` on a `None` value" and t.frames[0].line == 27

def test_backtrace_frames_with_location_only_and_hash_stripped():
    [t] = parse(BT)
    assert t.message.startswith("called `Result::unwrap()` on an `Err` value")
    assert [f.function for f in t.frames] == [
        "rust_begin_unwind", "core::panicking::panic_fmt", "ledger::post_entry", "ledger::main"]

def test_two_panics():
    assert len(parse(NEW + "INFO restarting\n" + NEW)) == 2
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/parsers/test_rust.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'debugagent.parsers.rust'`

- [ ] **Step 3: Implement `parsers/rust.py`**

```python
import re
from debugagent.models import Family, Frame, ParsedTrace

_NEW = re.compile(r"^thread '[^']*' panicked at (?P<file>[^\s']+?):(?P<line>\d+):\d+:\s*$")
_OLD = re.compile(r"^thread '[^']*' panicked at '(?P<msg>.*)', (?P<file>\S+?):(?P<line>\d+):\d+\s*$")
_BT_START = re.compile(r"^\s*stack backtrace:\s*$")
_BT_FUNC = re.compile(r"^\s*\d+:\s+(?:0x[0-9a-f]+ - )?(?P<func>\S.*?)\s*$")
_BT_AT = re.compile(r"^\s*at (?P<file>\S+?):(?P<line>\d+)(?::\d+)?\s*$")
_HASH = re.compile(r"::h[0-9a-f]{16}$")


def parse(text: str) -> list[ParsedTrace]:
    results: list[ParsedTrace] = []
    cur: dict | None = None      # {"file", "line", "msg", "frames", "in_bt", "pending"}

    def flush() -> None:
        nonlocal cur
        if cur and cur["msg"] is not None:
            frames = cur["frames"] or [Frame(cur["file"], cur["line"], "<panic>")]
            results.append(ParsedTrace(Family.RUST, "panic", cur["msg"], tuple(frames)))
        cur = None

    for line in text.split("\n"):
        s = line.strip()
        m = _NEW.match(s) or _OLD.match(s)
        if m:
            flush()
            cur = {"file": m["file"], "line": int(m["line"]),
                   "msg": m.groupdict().get("msg"), "frames": [], "in_bt": False, "pending": None}
            continue
        if cur is None or not s:
            continue
        if cur["msg"] is None:
            cur["msg"] = s
            continue
        if _BT_START.match(s):
            cur["in_bt"] = True
            continue
        if s.startswith("note:"):
            continue
        if cur["in_bt"]:
            at = _BT_AT.match(s)
            if at:
                if cur["pending"]:
                    cur["frames"].append(Frame(at["file"], int(at["line"]), cur["pending"]))
                cur["pending"] = None
                continue
            fn = _BT_FUNC.match(s)
            if fn:
                cur["pending"] = _HASH.sub("", fn["func"])
                continue
            flush()          # backtrace ended
    flush()
    return results
```

Register `Family.RUST: rust.parse` in `parsers/__init__.py`. All five families are now registered.

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/parsers/test_rust.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Add the 12 Rust patterns** in `src/debugagent/patterns/data/rust/<slug>.yaml`. All have `error_type: panic`. Dependency patterns get **higher** confidence than `unwrap_err`, so that "unwrap on a ConnectionRefused" is diagnosed as the connectivity cause and not only the unwrap.

| file slug | message_regex | category | conf | tags | root_cause | fixes (tradeoff) |
|---|---|---|---|---|---|---|
| unwrap_none | ``called `Option::unwrap\(\)` on a `None` value`` | code | 0.9 | [null, unwrap] | `unwrap()` on a `None`: a lookup/parse returned nothing and the code assumed it can't | Use `?` with `.ok_or(...)`/`ok_or_else` to propagate a typed error (idiomatic; signature change) · Use `unwrap_or`/`unwrap_or_default` where a default is valid (local; may hide bad data) |
| unwrap_err | ``called `Result::unwrap\(\)` on an `Err` value`` | code | 0.85 | [unwrap, error-handling] | `unwrap()` on an `Err`: a fallible operation failed and the error was not handled; the `Err` payload in the message is the real cause | Propagate with `?` and handle at the boundary (idiomatic; touches signatures) · Replace with `expect("context")` + a retry where transient (better message; still panics) |
| index_oob | `index out of bounds: the len is \d+ but the index is \d+` | code | 0.85 | [off-by-one, empty] | Slice/Vec index ≥ len: off-by-one or an empty collection | Use `.get(i)` and handle `None` (safe; more code) · Iterate instead of indexing (removes the bug class; refactor) |
| overflow | `attempt to (add\|subtract\|multiply\|negate\|shift left\|shift right) with overflow` | code | 0.85 | [arithmetic] | Integer overflow in a debug build (it wraps silently in release): underflowing `usize` subtraction is the classic case | Use `checked_*`/`saturating_*` ops (explicit; verbose) · Widen the type or reorder the arithmetic (targeted; needs analysis) |
| divide_by_zero | `attempt to (divide\|calculate the remainder) (by zero\|with a divisor of zero)` | code | 0.85 | [arithmetic] | Division by zero, typically an empty count or unset config | Guard with `checked_div` and return an error (safe) · Validate config at startup (fail fast; config contract) |
| refcell_borrow | `already (mutably )?borrowed\|BorrowMutError\|BorrowError` | code | 0.85 | [borrow, concurrency] | A `RefCell` runtime borrow conflict: a `borrow_mut` while another borrow is alive, often across a callback or re-entrant call | Shorten borrow scopes (drop guards before calling out) (targeted) · Restructure ownership or use `Cell`/message passing (removes the bug class; refactor) |
| str_slice | `is not a char boundary\|range end index \d+ out of range\|slice index starts at` | code | 0.8 | [off-by-one, encoding] | String/slice range is invalid: byte index inside a multi-byte UTF-8 char, or past the end | Use `char_indices`/`get(range)` (safe; must handle `None`) · Work in bytes explicitly where the data is ASCII-only (fast; must enforce ASCII) |
| nested_runtime | `Cannot (start\|drop) a runtime from within (a\|an asynchronous) (runtime\|context)` | config | 0.9 | [async, tokio] | `block_on` or runtime creation inside an async context (Tokio), usually a sync wrapper called from async code | Make the call path async and `.await` it (correct; ripples through callers) · Use `tokio::task::spawn_blocking` / `block_in_place` (quick; ties up worker threads) |
| mutex_poisoned | `PoisonError\|poisoned` | code | 0.87 | [concurrency] | A thread panicked while holding the Mutex; the poison error is a secondary symptom, so find the first panic | Find and fix the original panic (root fix) · Recover with `into_inner()` if the data is still consistent (keeps running; risks corrupt state) |
| explicit | `explicitly panicked\|not yet implemented\|not implemented\|entered unreachable code` | code | 0.75 | [todo] | A `panic!`/`todo!`/`unimplemented!`/`unreachable!` was reached: an unhandled case in production | Implement the missing branch (correct) · Return an error instead of panicking for unexpected input (resilient; API change) |
| connection_refused | `Connection refused\|ConnectionRefused` | dependency | 0.88 | [connectivity] | The dependency isn't listening (down, wrong address, or not ready) and the error was unwrapped | Fix the address in config/service discovery (config fix) · Retry with backoff before giving up (resilient; slower failure) |
| timeout | `timed out\|TimedOut\|deadline has elapsed\|Elapsed` | dependency | 0.86 | [timeout] | A downstream call timed out and the error was unwrapped; the callee is the likely fault | Handle the timeout error with retry + backoff (resilient; can amplify load) · Fix callee latency / tune the timeout (root fix; cross-team) |

- [ ] **Step 6: Write the per-pattern golden test** — `tests/patterns/test_rust_patterns.py`

```python
import pytest
from debugagent.models import Family, Frame, ParsedTrace
from debugagent.parsers.rust import parse
from debugagent.patterns.loader import load_patterns, DEFAULT_PATTERN_DIR
from debugagent.patterns.matcher import match_trace

PATS = load_patterns(DEFAULT_PATTERN_DIR)
F = (Frame("src/ledger.rs", 27, "ledger::post_entry"),)

@pytest.mark.parametrize("msg,expected", [
    ("called `Option::unwrap()` on a `None` value", "rust.unwrap_none"),
    ('called `Result::unwrap()` on an `Err` value: ParseIntError { kind: InvalidDigit }', "rust.unwrap_err"),
    ("index out of bounds: the len is 3 but the index is 5", "rust.index_oob"),
    ("attempt to subtract with overflow", "rust.overflow"),
    ("attempt to divide by zero", "rust.divide_by_zero"),
    ("already mutably borrowed: BorrowError", "rust.refcell_borrow"),
    ("byte index 3 is not a char boundary; it is inside 'é' (bytes 2..4) of `café`", "rust.str_slice"),
    ("Cannot start a runtime from within a runtime.", "rust.nested_runtime"),
    ('called `Result::unwrap()` on an `Err` value: PoisonError { .. }', "rust.mutex_poisoned"),
    ("not yet implemented", "rust.explicit"),
    ('called `Result::unwrap()` on an `Err` value: Os { code: 111, kind: ConnectionRefused, message: "Connection refused" }', "rust.connection_refused"),
    ('called `Result::unwrap()` on an `Err` value: Elapsed(())', "rust.timeout"),
])
def test_each_rust_pattern_matches(msg, expected):
    h = match_trace(ParsedTrace(Family.RUST, "panic", msg, F), PATS)
    assert h.pattern_id == expected and 2 <= len(h.fixes) <= 3 and "#[should_panic" in h.repro_test

def test_backtrace_locations_skip_std_frames():
    from tests.parsers.test_rust import BT
    [t] = parse(BT)
    h = match_trace(t, PATS)
    assert h.locations[0].function == "ledger::post_entry"
```

`mutex_poisoned` (0.87), `timeout` (0.86), and `connection_refused` (0.88) deliberately outrank `unwrap_err` (0.85), because their messages also contain "called `Result::unwrap()`". The golden test pins this ordering.

- [ ] **Step 7: Run all tests to verify pass**

Run: `pytest -v`
Expected: PASS. Every family has ≥ 10 patterns: `python 13, jvm 14, node 12, go 14, rust 12 = 65`.

- [ ] **Step 8: Commit**

```bash
git add -A && git commit -m "feat: rust panic parser (new/old format, backtraces) and 12 rust patterns"
```

### Task 8: Parallel multi-language orchestrator (timeouts, failure isolation, timings)

**Files:**
- Modify: `src/debugagent/models.py` (add `Diagnosis.timings`), `src/debugagent/orchestrator.py`, `src/debugagent/cli.py` (`--timeout`), `src/debugagent/render.py` (show timings in `--json`)
- Test: `tests/test_orchestrator_parallel.py`

**Interfaces:**
- Consumes: `LanguageSubagent` and `build_subagents` (Task 3); all 5 parsers (Tasks 2 and 4–7).
- Produces: `diagnose(text: str, subagents: dict[Family, LanguageSubagent], timeout_s: float = SUBAGENT_TIMEOUT_S) -> Diagnosis`, with `SUBAGENT_TIMEOUT_S = 2.0` (spec: "Subagent latency < 2s each"). `Diagnosis.timings: tuple[tuple[str, float], ...]` holds (family value, seconds) per completed subagent. Subagents run on **daemon threads**: a hung subagent can't block process exit, and its failure or timeout becomes a `notes` entry.

Why threads: the GIL limits CPU speed-up for regex work, but threads give isolation, a hard wall-clock budget, and the concurrency seam that Stage 3/LLM-backed subagents will need. If profiling in Task 12 shows the budget at risk, swap to `ProcessPoolExecutor` behind the same `diagnose` signature.

- [ ] **Step 1: Write the failing tests** — `tests/test_orchestrator_parallel.py`

```python
import time
from debugagent.models import Family
from debugagent.orchestrator import diagnose
from debugagent.subagent import LanguageSubagent, build_subagents

PY = open("tests/data/python_none.txt").read()
JAVA = open("tests/data/jvm_chained.txt").read()
NODE = open("tests/data/node_cause.txt").read()
GO = "fatal error: all goroutines are asleep - deadlock!\n\ngoroutine 1 [chan receive]:\nmain.main()\n\t/srv/inventory/main.go:9 +0x2d\n"
RUST = "thread 'main' panicked at src/ledger.rs:27:18:\ncalled `Option::unwrap()` on a `None` value\n"

def test_all_five_families_in_one_input():
    d = diagnose("\n".join([PY, JAVA, NODE, GO, RUST]), build_subagents())
    assert d.families == set(Family)
    ids = {h.pattern_id for h in d.hypotheses}
    assert {"python.attribute_error.none_type", "jvm.npe.helpful", "node.econnrefused",
            "go.deadlock", "rust.unwrap_none"} <= ids
    assert {fam for fam, _ in d.timings} == {f.value for f in Family}

# Review Focus #5: a crashing or hanging subagent must not sink the others
def test_crashing_subagent_is_isolated():
    subs = build_subagents()
    def boom(_text):
        raise RuntimeError("parser exploded")
    subs[Family.GO] = LanguageSubagent(Family.GO, boom, [])
    d = diagnose(PY + "\n" + GO, subs)
    assert d.top.pattern_id == "python.attribute_error.none_type"
    assert any("go subagent failed: RuntimeError: parser exploded" in n for n in d.notes)

def test_hanging_subagent_times_out_quickly():
    subs = build_subagents()
    subs[Family.RUST] = LanguageSubagent(Family.RUST, lambda _t: time.sleep(10) or [], [])
    t0 = time.perf_counter()
    d = diagnose(PY + "\n" + RUST, subs, timeout_s=0.3)
    assert time.perf_counter() - t0 < 1.0
    assert d.top.pattern_id == "python.attribute_error.none_type"
    assert any("rust subagent timed out after 0.3s" in n for n in d.notes)

def test_subagents_run_concurrently():
    subs = build_subagents()
    slow = lambda fam: LanguageSubagent(fam, lambda _t: time.sleep(0.4) or [], [])
    subs[Family.GO], subs[Family.RUST] = slow(Family.GO), slow(Family.RUST)
    t0 = time.perf_counter()
    diagnose(GO + "\n" + RUST, subs)
    assert time.perf_counter() - t0 < 0.7      # sequential would be ≥ 0.8
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_orchestrator_parallel.py -v`
Expected: FAIL (`diagnose() got an unexpected keyword argument 'timeout_s'` / no `timings` attribute)

- [ ] **Step 3: Add `timings` to `Diagnosis`** in `models.py`:

```python
@dataclass(frozen=True)
class Diagnosis:
    hypotheses: tuple[Hypothesis, ...]
    families: frozenset[Family]
    notes: tuple[str, ...] = ()
    timings: tuple[tuple[str, float], ...] = ()   # (family value, seconds) per finished subagent
    ...
```

- [ ] **Step 4: Rewrite `orchestrator.py`**

```python
import threading
import time
from debugagent.aggregator import aggregate
from debugagent.detect import MAX_INPUT_CHARS, detect_families, normalize
from debugagent.models import Diagnosis, Family, Hypothesis
from debugagent.subagent import LanguageSubagent

SUBAGENT_TIMEOUT_S = 2.0


def _run_parallel(fams: list[Family], subagents: dict[Family, LanguageSubagent], text: str,
                  timeout_s: float) -> tuple[dict[Family, tuple], list[Family]]:
    results: dict[Family, tuple] = {}

    def worker(fam: Family) -> None:
        t0 = time.perf_counter()
        try:
            results[fam] = ("ok", subagents[fam].run(text), time.perf_counter() - t0)
        except Exception as e:  # isolate any subagent failure
            results[fam] = ("err", e, time.perf_counter() - t0)

    threads = {f: threading.Thread(target=worker, args=(f,), daemon=True, name=f"subagent-{f.value}")
               for f in fams}
    for t in threads.values():
        t.start()
    deadline = time.monotonic() + timeout_s
    for t in threads.values():
        t.join(max(0.0, deadline - time.monotonic()))
    return results, [f for f, t in threads.items() if t.is_alive()]


def diagnose(text: str, subagents: dict[Family, LanguageSubagent],
             timeout_s: float = SUBAGENT_TIMEOUT_S) -> Diagnosis:
    notes: list[str] = []
    if len(text) > MAX_INPUT_CHARS:
        notes.append(f"input truncated to its last {MAX_INPUT_CHARS:,} characters")
    clean = normalize(text)
    families = detect_families(clean)
    fams = sorted((f for f in families if f in subagents), key=lambda f: f.value)
    results, timed_out = _run_parallel(fams, subagents, clean, timeout_s)
    hyps: list[Hypothesis] = []
    timings: list[tuple[str, float]] = []
    for fam in fams:
        if fam in timed_out:
            notes.append(f"{fam.value} subagent timed out after {timeout_s:.1f}s")
            continue
        status, payload, secs = results[fam]
        timings.append((fam.value, round(secs, 4)))
        if status == "ok":
            hyps.extend(payload)
        else:
            notes.append(f"{fam.value} subagent failed: {type(payload).__name__}: {payload}")
    return Diagnosis(aggregate(hyps), families, tuple(notes), tuple(timings))
```

- [ ] **Step 5: Wire up the CLI and renderer**

In `cli.py`'s `diagnose` command, add `timeout: float = typer.Option(2.0, "--timeout", help="Per-subagent budget in seconds")` and call `run_diagnose(text, subagents, timeout_s=timeout)`. In `render_json`, add `"timings": {fam: secs for fam, secs in d.timings}` to the top-level object.

- [ ] **Step 6: Run all tests to verify pass**

Run: `pytest -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "feat: parallel subagent orchestration with timeouts, failure isolation and timings"
```

### Task 9: Codebase Scanner: services, languages, frameworks, dependency graph, store, `scan` CLI

**Files:**
- Create: `src/debugagent/scanner/__init__.py`, `scanner/models.py`, `scanner/languages.py`, `scanner/graph.py`, `scanner/store.py`
- Modify: `src/debugagent/cli.py` (add the `scan` command)
- Test: `tests/scanner/__init__.py`, `tests/scanner/conftest.py` (a `mini_system` fixture), `tests/scanner/test_languages.py`, `tests/scanner/test_graph.py`, `tests/scanner/test_store.py`

**Interfaces:**
- Consumes: `Family` and `Frame` (Task 1).
- Produces:
  - `ServiceInfo(name: str, path: str, family: Family, frameworks: list[str], dependencies: list[str], aliases: list[str], packages: list[str])`. `path` is POSIX and relative to the scan root. `aliases` holds the dir name plus the manifest package/crate/module names. `packages` holds JVM package names.
  - `CodebaseMap(root: str, services: dict[str, ServiceInfo], edges: dict[str, list[str]], history: dict[str, dict[str, int]])`, with methods `service_for_frame(frame: Frame) -> str | None`, `calls(a: str, b: str) -> bool` (transitive: does `a` call `b`?), `to_dict()`, and `from_dict()`.
  - `scan_services(root: Path) -> dict[str, ServiceInfo]`, `build_edges(root: Path, services) -> dict[str, list[str]]`, `scan(root: Path, history: bool = True) -> CodebaseMap` (history is wired in Task 11; until then `history` stays `{}`), `save_map(m, path)`, `load_map(path) -> CodebaseMap`, and `DEFAULT_MAP_PATH = Path(".debugagent/codebase.json")`.
  - The CLI `debugagent scan ROOT [--out FILE]` writes `ROOT/.debugagent/codebase.json` by default and prints one line per service. It never writes anywhere else in ROOT.

- [ ] **Step 1: Write the shared fixture** — `tests/scanner/conftest.py`

```python
import json
import pytest

@pytest.fixture
def mini_system(tmp_path):
    root = tmp_path / "sys"
    files = {
        "docker-compose.yml": (
            "services:\n"
            "  web:\n    build: ./services/web\n    depends_on: [orders]\n"
            "    environment:\n      BILLING_URL: http://billing:8000\n"
            "  orders:\n    build: ./services/orders\n    depends_on:\n      inventory: {condition: service_started}\n"
            "  billing:\n    build: ./services/billing\n"
            "  inventory:\n    build: ./services/inventory\n"
            "  ledger:\n    build: ./services/ledger\n"),
        "services/web/package.json": json.dumps({"name": "@acme/web", "dependencies": {"express": "^4.19.0", "axios": "^1.7.0"}}),
        "services/web/src/api.ts": 'const ORDERS = "http://orders:8080/api";\n',
        "services/web/node_modules/axios/index.js": "// must be skipped\n",
        "services/orders/pom.xml": ("<project><artifactId>orders-service</artifactId><dependencies>"
                                    "<dependency><artifactId>spring-boot-starter-web</artifactId></dependency>"
                                    "<dependency><artifactId>HikariCP</artifactId></dependency></dependencies></project>"),
        "services/orders/src/main/java/com/acme/orders/pricing/Discounts.java": "package com.acme.orders.pricing;\n",
        "services/orders/src/main/resources/application.yml": "inventory:\n  url: http://inventory:9000\n",
        "services/billing/pyproject.toml": ('[project]\nname = "billing"\ndependencies = ["fastapi>=0.110", "requests==2.32.0"]\n'),
        "services/billing/app/client.py": 'LEDGER = "http://ledger:7000"\n',
        "services/inventory/go.mod": "module github.com/acme/inventory\n\ngo 1.22\n\nrequire (\n\tgithub.com/gin-gonic/gin v1.10.0\n)\n",
        "services/inventory/store.go": "package main\n",
        "services/ledger/Cargo.toml": '[package]\nname = "ledger-svc"\nversion = "0.1.0"\n\n[dependencies]\naxum = "0.7"\ntokio = { version = "1", features = ["full"] }\n',
        "services/ledger/src/ledger.rs": "fn post_entry() {}\n",
    }
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return root
```

- [ ] **Step 2: Write the failing tests**

`tests/scanner/test_languages.py`:
```python
from debugagent.models import Family
from debugagent.scanner.languages import scan_services

def test_finds_five_services_with_families(mini_system):
    s = scan_services(mini_system)
    assert {k: v.family for k, v in s.items()} == {
        "web": Family.NODE, "orders": Family.JVM, "billing": Family.PYTHON,
        "inventory": Family.GO, "ledger": Family.RUST}
    assert s["web"].path == "services/web"

def test_frameworks_dependencies_aliases_packages(mini_system):
    s = scan_services(mini_system)
    assert "express" in s["web"].frameworks and "axios" in s["web"].dependencies
    assert "spring" in s["orders"].frameworks and "HikariCP" in s["orders"].dependencies
    assert "fastapi" in s["billing"].frameworks and "requests" in s["billing"].dependencies
    assert "gin" in s["inventory"].frameworks
    assert {"axum", "tokio"} <= set(s["ledger"].frameworks)
    assert "ledger_svc" in s["ledger"].aliases and "ledger-svc" in s["ledger"].aliases
    assert "github.com/acme/inventory" in s["inventory"].aliases
    assert "com.acme.orders.pricing" in s["orders"].packages

def test_skips_vendored_dirs(mini_system):
    assert all("node_modules" not in v.path for v in scan_services(mini_system).values())

def test_empty_dir_has_no_services(tmp_path):
    assert scan_services(tmp_path) == {}

def test_single_service_repo_root(tmp_path):
    (tmp_path / "go.mod").write_text("module example.com/solo\n")
    s = scan_services(tmp_path)
    assert list(s) == [tmp_path.name] and s[tmp_path.name].path == "."
```

`tests/scanner/test_graph.py`:
```python
from debugagent.scanner.graph import build_edges
from debugagent.scanner.languages import scan_services

def test_edges_from_compose_and_source_urls(mini_system):
    edges = build_edges(mini_system, scan_services(mini_system))
    assert set(edges["web"]) == {"orders", "billing"}       # depends_on + env URL + source URL
    assert edges["orders"] == ["inventory"]                  # dict-form depends_on + application.yml
    assert edges["billing"] == ["ledger"]                    # source URL only
    assert edges.get("ledger", []) == []

def test_no_self_edges(mini_system):
    (mini_system / "services/web/src/self.ts").write_text('fetch("http://web:3000/health")\n')
    assert "web" not in build_edges(mini_system, scan_services(mini_system))["web"]
```

`tests/scanner/test_store.py`:
```python
from debugagent.models import Frame
from debugagent.scanner.store import load_map, save_map, scan

def test_round_trip(mini_system, tmp_path):
    m = scan(mini_system, history=False)
    save_map(m, tmp_path / "m.json")
    assert load_map(tmp_path / "m.json") == m

def test_service_for_frame_strategies(mini_system):
    m = scan(mini_system, history=False)
    assert m.service_for_frame(Frame("/srv/web/src/api.ts", 3, "handler")) == "web"            # path segment
    assert m.service_for_frame(Frame("Discounts.java", 18, "Discounts.forName",
                                     "com.acme.orders.pricing.Discounts")) == "orders"          # JVM package
    assert m.service_for_frame(Frame("./src/ledger.rs", 27, "ledger_svc::post_entry")) == "ledger"  # crate
    assert m.service_for_frame(Frame("github.com/acme/inventory/store.go", 42, "main.Get")) == "inventory"
    assert m.service_for_frame(Frame("/usr/lib/other.py", 1, "f")) is None

def test_calls_is_transitive(mini_system):
    m = scan(mini_system, history=False)
    assert m.calls("web", "inventory") and not m.calls("inventory", "web")
```

- [ ] **Step 3: Run to verify failure**

Run: `pytest tests/scanner -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'debugagent.scanner'`

- [ ] **Step 4: Implement `scanner/models.py`**

```python
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from debugagent.models import Family, Frame


@dataclass
class ServiceInfo:
    name: str
    path: str
    family: Family
    frameworks: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    packages: list[str] = field(default_factory=list)


@dataclass
class CodebaseMap:
    root: str
    services: dict[str, ServiceInfo]
    edges: dict[str, list[str]]
    history: dict[str, dict[str, int]] = field(default_factory=dict)

    def service_for_frame(self, frame: Frame) -> str | None:
        segments = set(frame.file.replace("\\", "/").split("/"))
        norm_file = frame.file.replace("\\", "/")
        for name, s in self.services.items():
            for alias in s.aliases:
                if alias in segments or ("/" in alias and alias + "/" in norm_file):
                    return name
            if frame.module and s.packages:
                pkg = frame.module.rsplit(".", 1)[0]
                if any(pkg == p or pkg.startswith(p + ".") for p in s.packages):
                    return name
            crate = frame.function.split("::", 1)[0] if "::" in frame.function else None
            if crate and crate in s.aliases:
                return name
        return None

    def calls(self, a: str, b: str) -> bool:
        seen, stack = set(), list(self.edges.get(a, []))
        while stack:
            n = stack.pop()
            if n == b:
                return True
            if n not in seen:
                seen.add(n)
                stack.extend(self.edges.get(n, []))
        return False

    def to_dict(self) -> dict:
        d = asdict(self)
        for s in d["services"].values():
            s["family"] = s["family"].value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> CodebaseMap:
        services = {k: ServiceInfo(**{**v, "family": Family(v["family"])}) for k, v in d["services"].items()}
        return cls(d["root"], services, d["edges"], d.get("history", {}))
```

- [ ] **Step 5: Implement `scanner/languages.py`**

```python
import json
import re
import tomllib
from pathlib import Path
from debugagent.models import Family
from debugagent.scanner.models import ServiceInfo

SKIP_DIRS = {".git", "node_modules", "target", "build", "dist", "vendor", ".venv", "venv",
             "__pycache__", ".gradle", ".idea", ".debugagent", ".next", "out"}
MANIFESTS: list[tuple[str, Family]] = [
    ("pom.xml", Family.JVM), ("build.gradle.kts", Family.JVM), ("build.gradle", Family.JVM),
    ("build.sbt", Family.JVM), ("go.mod", Family.GO), ("Cargo.toml", Family.RUST),
    ("package.json", Family.NODE), ("pyproject.toml", Family.PYTHON),
    ("setup.py", Family.PYTHON), ("requirements.txt", Family.PYTHON),
]
FRAMEWORKS = {  # substring in lowercased manifest text -> framework label
    "spring-boot": "spring", "quarkus": "quarkus", "micronaut": "micronaut", "ktor": "ktor",
    "django": "django", "flask": "flask", "fastapi": "fastapi", "celery": "celery",
    '"express"': "express", "@nestjs/core": "nestjs", '"fastify"': "fastify", '"next"': "next",
    "gin-gonic/gin": "gin", "labstack/echo": "echo", "gofiber/fiber": "fiber", "grpc": "grpc",
    "actix-web": "actix-web", "axum": "axum", "tokio": "tokio", "rocket": "rocket",
}
MAX_DEPTH = 4


def _dep_names(manifest: Path, family: Family) -> tuple[list[str], list[str]]:
    """Return (dependency names, extra aliases) parsed from a manifest."""
    text = manifest.read_text(errors="replace")
    name = manifest.name
    deps: list[str] = []
    aliases: list[str] = []
    if name == "package.json":
        data = json.loads(text or "{}")
        deps = sorted({**data.get("dependencies", {}), **data.get("devDependencies", {})})
        if data.get("name"):
            aliases += [data["name"], data["name"].rsplit("/", 1)[-1]]
    elif name == "pyproject.toml":
        data = tomllib.loads(text)
        proj = data.get("project", {})
        raw = proj.get("dependencies", []) + list(data.get("tool", {}).get("poetry", {}).get("dependencies", {}))
        deps = sorted({re.split(r"[<>=~!;\[ ]", d, 1)[0] for d in raw if d and d != "python"})
        if proj.get("name"):
            aliases.append(proj["name"])
    elif name == "requirements.txt":
        deps = sorted({re.split(r"[<>=~!;\[ ]", ln.strip(), 1)[0] for ln in text.splitlines()
                       if ln.strip() and not ln.startswith(("#", "-"))})
    elif name == "go.mod":
        m = re.search(r"^module\s+(\S+)", text, re.M)
        if m:
            aliases += [m[1], m[1].rsplit("/", 1)[-1]]
        deps = sorted(set(re.findall(r"^\s*([\w.-]+\.[\w.-]+/\S+)\s+v", text, re.M)))
    elif name == "Cargo.toml":
        data = tomllib.loads(text)
        deps = sorted(data.get("dependencies", {}))
        pkg = data.get("package", {}).get("name")
        if pkg:
            aliases += [pkg, pkg.replace("-", "_")]
    elif name == "pom.xml":
        arts = re.findall(r"<artifactId>([^<]+)</artifactId>", text)
        if arts:
            aliases.append(arts[0])
        deps = sorted(set(arts[1:]))
    elif name.startswith("build.gradle") or name == "build.sbt":
        deps = sorted(set(re.findall(r"""["'][\w.-]+[:%]\s*"?([\w.-]+)"?\s*[:%]""", text)))
    return deps, aliases


def _jvm_packages(service_dir: Path) -> list[str]:
    pkgs = set()
    for lang in ("java", "kotlin", "scala"):
        base = service_dir / "src" / "main" / lang
        if base.is_dir():
            for f in base.rglob("*"):
                if f.suffix in (".java", ".kt", ".scala"):
                    pkgs.add(".".join(f.parent.relative_to(base).parts))
    return sorted(p for p in pkgs if p)


def detect_service(d: Path, root: Path) -> ServiceInfo | None:
    for fname, family in MANIFESTS:
        manifest = d / fname
        if manifest.is_file():
            deps, aliases = _dep_names(manifest, family)
            lowered = manifest.read_text(errors="replace").lower()
            frameworks = sorted({label for needle, label in FRAMEWORKS.items() if needle in lowered})
            name = d.name if d != root else root.name
            rel = d.relative_to(root).as_posix() if d != root else "."
            return ServiceInfo(
                name=name, path=rel, family=family, frameworks=frameworks, dependencies=deps,
                aliases=sorted({name, *aliases}),
                packages=_jvm_packages(d) if family is Family.JVM else [],
            )
    return None


def scan_services(root: Path) -> dict[str, ServiceInfo]:
    root = Path(root)
    found: dict[str, ServiceInfo] = {}
    frontier = [(p, 1) for p in sorted(root.iterdir()) if p.is_dir() and p.name not in SKIP_DIRS] \
        if root.is_dir() else []
    while frontier:
        d, depth = frontier.pop(0)
        svc = detect_service(d, root)
        if svc:
            found.setdefault(svc.name, svc)
            continue                       # don't descend into a service
        if depth < MAX_DEPTH:
            frontier += [(p, depth + 1) for p in sorted(d.iterdir()) if p.is_dir() and p.name not in SKIP_DIRS]
    if not found and root.is_dir():
        svc = detect_service(root, root)
        if svc:
            found[svc.name] = svc
    return found
```

- [ ] **Step 6: Implement `scanner/graph.py`**

```python
import re
from pathlib import Path
import yaml
from debugagent.scanner.languages import SKIP_DIRS
from debugagent.scanner.models import ServiceInfo

TEXT_EXT = {".py", ".java", ".kt", ".scala", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".go", ".rs",
            ".yml", ".yaml", ".properties", ".env", ".json", ".toml", ".conf"}
MAX_FILE_BYTES = 256_000
_URL_HOST = re.compile(r"\b(?:https?|grpc|amqp|redis|postgres(?:ql)?)://([a-z0-9][a-z0-9-]*)(?=[:/\"'\s]|$)", re.I)
_K8S_HOST = re.compile(r"\b([a-z0-9][a-z0-9-]*)\.[a-z0-9-]+\.svc\b")
COMPOSE_FILES = ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")


def _resolver(services: dict[str, ServiceInfo]) -> dict[str, str]:
    alias_to = {}
    for name, s in services.items():
        for a in s.aliases:
            alias_to[a.lower()] = name
    return alias_to


def _iter_text_files(d: Path):
    for p in d.rglob("*"):
        if any(part in SKIP_DIRS for part in p.relative_to(d).parts):
            continue
        if p.is_file() and p.suffix in TEXT_EXT and p.stat().st_size <= MAX_FILE_BYTES:
            yield p


def build_edges(root: Path, services: dict[str, ServiceInfo]) -> dict[str, list[str]]:
    root = Path(root)
    alias_to = _resolver(services)
    edges: dict[str, set[str]] = {n: set() for n in services}

    def add(src: str | None, host: str) -> None:
        dst = alias_to.get(host.lower())
        if src and dst and dst != src:
            edges[src].add(dst)

    for cf in COMPOSE_FILES:
        f = root / cf
        if f.is_file():
            data = yaml.safe_load(f.read_text()) or {}
            for cname, spec in (data.get("services") or {}).items():
                src = alias_to.get(cname.lower())
                deps = spec.get("depends_on") or []
                for dep in (deps if isinstance(deps, list) else list(deps)):
                    add(src, dep)
                env = spec.get("environment") or {}
                values = env.values() if isinstance(env, dict) else [e.split("=", 1)[-1] for e in env]
                for v in values:
                    for host in _URL_HOST.findall(str(v)):
                        add(src, host)

    for name, s in services.items():
        for p in _iter_text_files(root / s.path):
            text = p.read_text(errors="replace")
            for host in _URL_HOST.findall(text) + _K8S_HOST.findall(text):
                add(name, host)
    return {k: sorted(v) for k, v in edges.items()}
```

- [ ] **Step 7: Implement `scanner/store.py` and `scanner/__init__.py`**

```python
# scanner/store.py
import json
from pathlib import Path
from debugagent.scanner.graph import build_edges
from debugagent.scanner.languages import scan_services
from debugagent.scanner.models import CodebaseMap

DEFAULT_MAP_PATH = Path(".debugagent/codebase.json")


def scan(root: Path, history: bool = True) -> CodebaseMap:
    root = Path(root).resolve()
    services = scan_services(root)
    return CodebaseMap(str(root), services, build_edges(root, services), {})


def save_map(m: CodebaseMap, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(m.to_dict(), indent=2, sort_keys=True))


def load_map(path: Path) -> CodebaseMap:
    return CodebaseMap.from_dict(json.loads(Path(path).read_text()))
```

```python
# scanner/__init__.py
from debugagent.scanner.models import CodebaseMap, ServiceInfo
from debugagent.scanner.store import DEFAULT_MAP_PATH, load_map, save_map, scan

__all__ = ["CodebaseMap", "ServiceInfo", "DEFAULT_MAP_PATH", "load_map", "save_map", "scan"]
```

- [ ] **Step 8: Add the `scan` command** to `cli.py`

```python
from debugagent.scanner import DEFAULT_MAP_PATH, save_map, scan as run_scan

@app.command()
def scan(
    root: Path = typer.Argument(..., exists=True, file_okay=False, help="Repo or monorepo root"),
    out: Optional[Path] = typer.Option(None, "--out", help="Map file (default ROOT/.debugagent/codebase.json)"),
    history: bool = typer.Option(True, "--history/--no-history", help="Mine git history for bug tags"),
) -> None:
    """Scan services, languages, frameworks and the call graph (read-only)."""
    m = run_scan(root, history=history)
    if not m.services:
        typer.echo(f"No services found under {root} (looked for pom.xml, go.mod, package.json, ...).", err=True)
        raise typer.Exit(2)
    dest = out or (root / DEFAULT_MAP_PATH)
    save_map(m, dest)
    for name, s in sorted(m.services.items()):
        calls = ", ".join(m.edges.get(name, [])) or "-"
        typer.echo(f"{name:<20} {s.family.value:<7} {','.join(s.frameworks) or '-':<22} calls: {calls}")
    typer.echo(f"Wrote {dest}")
```

Add a CLI test to `tests/test_cli.py`:
```python
def test_scan_writes_only_under_debugagent(mini_system):
    before = {p for p in mini_system.rglob("*")}
    r = R.invoke(app, ["scan", str(mini_system), "--no-history"])
    assert r.exit_code == 0 and "orders" in r.stdout and "calls: inventory" in r.stdout
    new = {p for p in mini_system.rglob("*")} - before
    assert new and all(".debugagent" in p.parts for p in new)
```
Move the `mini_system` fixture from `tests/scanner/conftest.py` to `tests/conftest.py` so both test packages see it.

- [ ] **Step 9: Run all tests to verify pass**

Run: `pytest -v`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add -A && git commit -m "feat: codebase scanner (services, frameworks, call graph) and scan CLI"
```

### Task 10: Root-cause aggregator: service attribution and cross-service root cause

**Files:**
- Modify: `src/debugagent/aggregator.py`, `src/debugagent/orchestrator.py` (add the `codebase` param), `src/debugagent/cli.py` (`diagnose --codebase`)
- Test: `tests/test_aggregator.py`

**Interfaces:**
- Consumes: `CodebaseMap.service_for_frame`, `CodebaseMap.calls`, `scan`, and `load_map` (Task 9); `Hypothesis.category` (Task 2).
- Produces:
  - `aggregate(hyps: Iterable[Hypothesis], codebase: CodebaseMap | None = None) -> tuple[Hypothesis, ...]`.
  - `diagnose(text, subagents, timeout_s=SUBAGENT_TIMEOUT_S, codebase: CodebaseMap | None = None) -> Diagnosis`.
  - Constants: `SYMPTOM_FACTOR = 0.6`, `NO_MAP_SYMPTOM_FACTOR = 0.8`, `SOURCE_BOOST = 0.05`, `CONFIDENCE_CAP = 0.99`.
  - CLI: `debugagent diagnose TRACE --codebase PATH`. PATH is a map JSON or a repo root; for a root it uses `ROOT/.debugagent/codebase.json` if present, otherwise it scans on the fly (`history=False`).

Rules:
1. Attribute each hypothesis to the first service that any of its `locations` maps to.
2. **With a map:** a `dependency`-category hypothesis in service A is a *symptom* when another non-dependency, non-unknown hypothesis exists in a service B that A calls (transitively). The symptom gets confidence × 0.6 and an evidence line. The source gets +0.05 (capped at 0.99) and an evidence line naming the callers.
3. **Without a map:** if any non-dependency, non-unknown hypothesis exists, every `dependency` hypothesis gets × 0.8 and the evidence line "usually a symptom".

- [ ] **Step 1: Write the failing tests** — `tests/test_aggregator.py`

```python
from debugagent.detect import normalize
from debugagent.models import Family
from debugagent.orchestrator import diagnose
from debugagent.scanner import scan
from debugagent.subagent import build_subagents

NODE_TIMEOUT = "AxiosError: timeout of 5000ms exceeded\n    at placeOrder (/srv/web/src/orders.ts:22:11)\n"
JAVA = open("tests/data/jvm_chained.txt").read()

# Review Focus #4: mixed multi-service input → source service wins, caller is a symptom
def test_cross_service_source_beats_symptom(mini_system):
    d = diagnose(NODE_TIMEOUT + JAVA, build_subagents(), codebase=scan(mini_system, history=False))
    assert d.top.pattern_id == "jvm.npe.helpful" and d.top.service == "orders"
    assert d.top.confidence == 0.95
    assert any("web" in e and "likely origin" in e for e in d.top.evidence)
    node = next(h for h in d.hypotheses if h.family is Family.NODE)
    assert node.service == "web" and node.confidence == 0.45
    assert "symptom" in node.evidence[0]

def test_without_map_dependency_errors_rank_below_code_errors():
    d = diagnose(NODE_TIMEOUT + JAVA, build_subagents())
    assert d.top.pattern_id == "jvm.npe.helpful" and d.top.service is None
    node = next(h for h in d.hypotheses if h.family is Family.NODE)
    assert node.confidence == 0.6 and "usually a symptom" in node.evidence[0]

def test_lone_dependency_error_is_untouched(mini_system):
    d = diagnose(NODE_TIMEOUT, build_subagents(), codebase=scan(mini_system, history=False))
    assert d.top.pattern_id == "node.timeout" and d.top.confidence == 0.75 and d.top.evidence == ()

def test_unrelated_services_are_not_linked(mini_system):
    # ledger does not call orders → no symptom demotion
    rust_timeout = ("thread 'main' panicked at src/ledger.rs:3:5:\n"
                    "called `Result::unwrap()` on an `Err` value: Elapsed(())\nstack backtrace:\n"
                    "   0: ledger_svc::post\n             at ./src/ledger.rs:3:5\n")
    d = diagnose(rust_timeout + JAVA, build_subagents(), codebase=scan(mini_system, history=False))
    rust = next(h for h in d.hypotheses if h.family is Family.RUST)
    assert rust.service == "ledger" and rust.confidence == 0.86

def test_attribution_for_python(mini_system):
    d = diagnose(open("tests/data/python_none.txt").read(), build_subagents(),
                 codebase=scan(mini_system, history=False))
    assert d.top.service == "billing"
```

Also add CLI tests to `tests/test_cli.py`:
```python
def test_diagnose_with_codebase_root(mini_system, tmp_path):
    p = tmp_path / "t.txt"
    p.write_text("AxiosError: timeout of 5000ms exceeded\n    at placeOrder (/srv/web/src/orders.ts:22:11)\n"
                 + open("tests/data/jvm_chained.txt").read())
    r = R.invoke(app, ["diagnose", str(p), "--codebase", str(mini_system)])
    assert r.exit_code == 0 and "Service: orders" in r.stdout and "likely origin" in r.stdout

def test_diagnose_with_bad_codebase_path():
    r = R.invoke(app, ["diagnose", "tests/data/python_none.txt", "--codebase", "nope/"])
    assert r.exit_code == 2 and "codebase" in r.output.lower()
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_aggregator.py -v`
Expected: FAIL with `TypeError: diagnose() got an unexpected keyword argument 'codebase'`

- [ ] **Step 3: Rewrite `aggregator.py`**

```python
from dataclasses import replace
from typing import Iterable
from debugagent.models import Hypothesis
from debugagent.scanner.models import CodebaseMap

SYMPTOM_FACTOR = 0.6
NO_MAP_SYMPTOM_FACTOR = 0.8
SOURCE_BOOST = 0.05
CONFIDENCE_CAP = 0.99
_NOT_SOURCE = ("dependency", "unknown")


def _key(h: Hypothesis) -> tuple:
    loc = h.locations[0] if h.locations else None
    return (h.pattern_id, loc.file if loc else None, loc.line if loc else None, h.service)


def _attribute(h: Hypothesis, cb: CodebaseMap) -> Hypothesis:
    if h.service:
        return h
    for f in h.locations:
        s = cb.service_for_frame(f)
        if s:
            return replace(h, service=s)
    return h


def _is_symptom_of(a: Hypothesis, b: Hypothesis, cb: CodebaseMap) -> bool:
    return (a.category == "dependency" and b.category not in _NOT_SOURCE
            and bool(a.service) and bool(b.service) and a.service != b.service
            and cb.calls(a.service, b.service))


def _with_map(hyps: list[Hypothesis], cb: CodebaseMap) -> list[Hypothesis]:
    out = []
    for h in hyps:
        sources = sorted({b.service for b in hyps if _is_symptom_of(h, b, cb)})
        callers = sorted({a.service for a in hyps if _is_symptom_of(a, h, cb)})
        if sources:
            h = replace(h, confidence=round(h.confidence * SYMPTOM_FACTOR, 4), evidence=h.evidence + (
                f"Likely a symptom: {h.service} calls {', '.join(sources)}, which failed at the same time",))
        if callers:
            h = replace(h, confidence=min(CONFIDENCE_CAP, round(h.confidence + SOURCE_BOOST, 4)),
                        evidence=h.evidence + (
                f"Callers {', '.join(callers)} failed with timeout/connection errors into "
                f"{h.service}: this is the likely origin",))
        out.append(h)
    return out


def _without_map(hyps: list[Hypothesis]) -> list[Hypothesis]:
    if not any(h.category not in _NOT_SOURCE for h in hyps):
        return hyps
    return [replace(h, confidence=round(h.confidence * NO_MAP_SYMPTOM_FACTOR, 4), evidence=h.evidence + (
                "Timeout/connection errors are usually a symptom; another error in this input is a "
                "more likely origin (pass --codebase for service-aware ranking)",))
            if h.category == "dependency" else h for h in hyps]


def aggregate(hyps: Iterable[Hypothesis], codebase: CodebaseMap | None = None) -> tuple[Hypothesis, ...]:
    hs = list(hyps)
    if codebase is not None:
        hs = _with_map([_attribute(h, codebase) for h in hs], codebase)
    else:
        hs = _without_map(hs)
    best: dict[tuple, Hypothesis] = {}
    for h in hs:
        k = _key(h)
        if k not in best or h.confidence > best[k].confidence:
            best[k] = h
    return tuple(sorted(best.values(), key=lambda h: (-h.confidence, h.pattern_id)))
```

- [ ] **Step 4: Thread `codebase` through `orchestrator.diagnose`**

Change the signature to `diagnose(text, subagents, timeout_s=SUBAGENT_TIMEOUT_S, codebase=None)` and the return line to `Diagnosis(aggregate(hyps, codebase), families, tuple(notes), tuple(timings))`. Import `CodebaseMap` for the type hint only.

- [ ] **Step 5: Add `--codebase` to the CLI**

```python
from debugagent.scanner import DEFAULT_MAP_PATH, load_map, scan as run_scan

def _load_codebase(path: Optional[Path]):
    if path is None:
        return None
    if path.is_file():
        return load_map(path)
    if path.is_dir():
        mp = path / DEFAULT_MAP_PATH
        return load_map(mp) if mp.is_file() else run_scan(path, history=False)
    typer.echo(f"Codebase path not found: {path}", err=True)
    raise typer.Exit(2)
```

Add `codebase: Optional[Path] = typer.Option(None, "--codebase", help="Codebase map JSON or repo root")` to `diagnose`, and call `run_diagnose(text, subagents, timeout_s=timeout, codebase=_load_codebase(codebase))`.

- [ ] **Step 6: Run all tests to verify pass**

Run: `pytest -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "feat: service attribution and cross-service root-cause aggregation"
```

### Task 11: Git-history bug mining and codebase-specific confidence boosts

**Files:**
- Create: `src/debugagent/scanner/history.py`
- Modify: `src/debugagent/scanner/store.py` (`scan(history=True)` fills `CodebaseMap.history`), `src/debugagent/aggregator.py` (history boost)
- Test: `tests/scanner/test_history.py`, add to `tests/test_aggregator.py`

**Interfaces:**
- Consumes: `ServiceInfo.path` and `CodebaseMap.history` (Task 9); `Hypothesis.tags` (Task 2).
- Produces:
  - `mine_history(root: Path, services: dict[str, ServiceInfo], max_commits: int = 2000) -> dict[str, dict[str, int]]` (service → tag → count of fix commits).
  - `TAG_KEYWORDS: dict[str, re.Pattern]`. Its keys use the **same tag vocabulary as the pattern YAML `tags`** (e.g. `null`, `timezone`, `timeout`, `pool`, `leak`, `concurrency`, `off-by-one`, `parsing`, `import`, `config`, `recursion`, `encoding`).
  - Constants `HISTORY_MIN_COUNT = 3` and `HISTORY_BOOST = 0.05`.
  - The aggregator adds +0.05 (cap 0.99) and the evidence line `"<svc> has <n> past fix commits tagged '<tag>' — a recurring weakness"` when a hypothesis's tags overlap a service tag with count ≥ 3. This covers the spec's "Codebase-Specific Learner", e.g. "In this Java codebase, NPE often comes from unchecked Optional usage".

- [ ] **Step 1: Write the failing tests** — `tests/scanner/test_history.py`

```python
import shutil
import subprocess
import pytest
from debugagent.scanner.history import mine_history
from debugagent.scanner.languages import scan_services

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

def _git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)

@pytest.fixture
def repo(mini_system):
    _git(mini_system, "init", "-q")
    _git(mini_system, "config", "user.email", "t@example.com")
    _git(mini_system, "config", "user.name", "t")
    _git(mini_system, "add", "-A")
    _git(mini_system, "commit", "-qm", "initial")
    target = mini_system / "services/billing/app/client.py"
    for i, msg in enumerate(["fix: handle None customer", "Fix NoneType on missing address",
                             "bugfix: null invoice total", "fix: UTC offset in due date", "feat: add export"]):
        target.write_text(f"# {i}\n")
        _git(mini_system, "commit", "-qam", msg)
    return mini_system

def test_counts_fix_commits_by_tag_per_service(repo):
    h = mine_history(repo, scan_services(repo))
    assert h["billing"]["null"] == 3
    assert h["billing"]["timezone"] == 1
    assert "orders" not in h or h["orders"] == {}

def test_non_git_dir_returns_empty(mini_system):
    assert mine_history(mini_system, scan_services(mini_system)) == {}
```

Add to `tests/test_aggregator.py`:
```python
from debugagent.scanner.models import CodebaseMap

def test_history_boost_for_recurring_weakness(mini_system):
    cb = scan(mini_system, history=False)
    cb.history = {"billing": {"null": 4}}
    d = diagnose(open("tests/data/python_none.txt").read(), build_subagents(), codebase=cb)
    assert d.top.service == "billing" and d.top.confidence == 0.9
    assert any("4 past fix commits tagged 'null'" in e for e in d.top.evidence)

def test_history_below_threshold_no_boost(mini_system):
    cb = scan(mini_system, history=False)
    cb.history = {"billing": {"null": 2}}
    d = diagnose(open("tests/data/python_none.txt").read(), build_subagents(), codebase=cb)
    assert d.top.confidence == 0.85
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/scanner/test_history.py tests/test_aggregator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'debugagent.scanner.history'`

- [ ] **Step 3: Implement `scanner/history.py`**

```python
import re
import subprocess
from pathlib import Path
from debugagent.scanner.models import ServiceInfo

_FIX = re.compile(r"\b(fix(e[sd])?|bug(fix)?|hotfix|patch|regression|revert)\b", re.I)
TAG_KEYWORDS: dict[str, re.Pattern[str]] = {k: re.compile(v, re.I) for k, v in {
    "null": r"\bnull\b|\bnil\b|\bnone(type)?\b|\bnpe\b|nullpointer|undefined|optional",
    "timezone": r"time ?zone|\btz\b|\butc\b|\bdst\b|offset",
    "timeout": r"timeout|timed out|deadline",
    "pool": r"\bpool\b|hikari|connection leak",
    "leak": r"leak|\boom\b|out of memory",
    "concurrency": r"\brace\b|deadlock|concurren|mutex|\block(ing)?\b|goroutine",
    "off-by-one": r"off[- ]by[- ]one|\bindex\b|bounds",
    "parsing": r"\bpars(e|ing)|json|deserializ|serializ",
    "import": r"\bimport\b|module not found|missing dependency",
    "config": r"\bconfig\b|env var|\bproperty\b|\bprofile\b",
    "recursion": r"recursion|stack ?overflow",
    "encoding": r"utf-?8|encoding|unicode",
}.items()}


def mine_history(root: Path, services: dict[str, ServiceInfo], max_commits: int = 2000) -> dict[str, dict[str, int]]:
    root = Path(root)
    probe = subprocess.run(["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
                           capture_output=True, text=True)
    if probe.returncode != 0:
        return {}
    out: dict[str, dict[str, int]] = {}
    for name, s in services.items():
        r = subprocess.run(
            ["git", "-C", str(root), "log", "--no-merges", f"-n{max_commits}", "--format=%s", "--", s.path],
            capture_output=True, text=True, timeout=30,
        )
        counts: dict[str, int] = {}
        for subject in r.stdout.splitlines():
            if not _FIX.search(subject):
                continue
            for tag, rx in TAG_KEYWORDS.items():
                if rx.search(subject):
                    counts[tag] = counts.get(tag, 0) + 1
        if counts:
            out[name] = counts
    return out
```

- [ ] **Step 4: Wire it into `scan`** (`scanner/store.py`):

```python
from debugagent.scanner.history import mine_history

def scan(root: Path, history: bool = True) -> CodebaseMap:
    root = Path(root).resolve()
    services = scan_services(root)
    hist = mine_history(root, services) if history else {}
    return CodebaseMap(str(root), services, build_edges(root, services), hist)
```

- [ ] **Step 5: Add the history boost** to `aggregator.py`, applied in `aggregate` right after `_attribute` and before `_with_map`:

```python
HISTORY_MIN_COUNT = 3
HISTORY_BOOST = 0.05


def _history_boost(h: Hypothesis, cb: CodebaseMap) -> Hypothesis:
    counts = cb.history.get(h.service or "", {})
    hits = sorted(((counts[t], t) for t in h.tags if counts.get(t, 0) >= HISTORY_MIN_COUNT), reverse=True)
    if not hits:
        return h
    n, tag = hits[0]
    return replace(h, confidence=min(CONFIDENCE_CAP, round(h.confidence + HISTORY_BOOST, 4)),
                   evidence=h.evidence + (f"{h.service} has {n} past fix commits tagged '{tag}' — a recurring weakness",))

# in aggregate():
#     hs = _with_map([_history_boost(_attribute(h, codebase), codebase) for h in hs], codebase)
```

- [ ] **Step 6: Run all tests to verify pass**

Run: `pytest -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "feat: mine git history for per-service bug tags and boost matching hypotheses"
```

### Task 12: Sample polyglot system, labeled trace corpus, and eval harness

**Files:**
- Create: `tests/sample_system.py` (the `SAMPLE_SYSTEM_FILES` dict), `fixtures/build_corpus.py`, the generated `fixtures/sample-system/**` and `fixtures/traces/**` (including `fixtures/traces/labels.yaml`), `src/debugagent/evaluation.py`
- Modify: `tests/conftest.py` (the `mini_system` fixture writes `SAMPLE_SYSTEM_FILES`); `tests/patterns/test_{python,jvm,node,go,rust}_patterns.py` (hoist each inline parametrize list into a module-level constant, `PY_CASES` / `JVM_CASES` / `NODE_CASES` / `GO_CASES` / `RUST_CASES`, and pass that constant to `@pytest.mark.parametrize`); `src/debugagent/cli.py` (the `eval` command)
- Test: `tests/test_evaluation.py`

**Interfaces:**
- Consumes: `diagnose` (Tasks 8/10), `build_subagents` (Task 3), `scan` (Task 9), and the golden case lists from Tasks 2 and 4–7.
- Produces:
  - `CaseResult(file: str, expected: str, got: str | None, service_expected: str | None, service_got: str | None, confidence: float, latency_s: float, correct: bool)`.
  - `EvalReport(results: list[CaseResult], accuracy: float, coverage: float, p95_latency_s: float, max_subagent_s: float, per_family: dict[str, float])`.
  - `evaluate(corpus_dir: Path, subagents, codebase: CodebaseMap | None = None) -> EvalReport`.
  - The CLI `debugagent eval CORPUS [--codebase PATH] [--min-accuracy 0.85] [--min-coverage 0.95] [--max-subagent-s 2.0]`. It exits `1` if any threshold fails.
  - Corpus layout: `labels.yaml` is `cases: [{file: <relative path>, expected: <pattern_id>, service: <name or null>}]`. **Task 14 reuses this format for real traces.**

**What this corpus is and isn't.** The corpus is generated from the golden case tables and rendered in three realistic noise variants (clean; log-prefixed; ANSI + CRLF), plus unknown-type cases, cross-service mixed cases, and the hand-written fixtures. It is a **regression gate** for the full pipeline (normalize → detect → parse → match → aggregate). It can't independently prove the 85% target, because the cases were written alongside the patterns. That judgment happens in **Task 14 on real traces**.

- [ ] **Step 1: Extract the sample system** into `tests/sample_system.py` as `SAMPLE_SYSTEM_FILES: dict[str, str]`, moving the `files` dict from the Task 9 fixture verbatim. Then rewrite the fixture:

```python
# tests/conftest.py
import pytest
from tests.sample_system import SAMPLE_SYSTEM_FILES

@pytest.fixture
def mini_system(tmp_path):
    root = tmp_path / "sys"
    for rel, content in SAMPLE_SYSTEM_FILES.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return root
```

Hoist the parametrize lists (e.g. `PY_CASES = [("AttributeError", "'NoneType' …", "python.attribute_error.none_type"), …]`), then run `pytest -v` and confirm it's still green before continuing.

- [ ] **Step 2: Write `fixtures/build_corpus.py`** (a deterministic generator; commit its output)

```python
"""Regenerate fixtures/sample-system and fixtures/traces. Run: python fixtures/build_corpus.py"""
import re
import shutil
import sys
from pathlib import Path
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # repo root, so `tests.*` imports work
from tests.patterns.test_go_patterns import GO_CASES
from tests.patterns.test_jvm_patterns import JVM_CASES
from tests.patterns.test_node_patterns import NODE_CASES
from tests.patterns.test_python_patterns import PY_CASES
from tests.patterns.test_rust_patterns import RUST_CASES
from tests.sample_system import SAMPLE_SYSTEM_FILES

HERE = Path(__file__).parent
TRACES = HERE / "traces"
SERVICE = {"python": "billing", "jvm": "orders", "node": "web", "go": "inventory", "rust": "ledger"}
FRAMES = {  # (file, line, function, module) innermost first, all inside the sample system
    "python": [("/srv/billing/app/invoice.py", 7, "build", None), ("/srv/billing/app/api.py", 20, "handle", None)],
    "jvm": [("Discounts.java", 18, "Discounts.forName", "com.acme.orders.pricing.Discounts"),
            ("Pricer.java", 52, "Pricer.price", "com.acme.orders.pricing.Pricer")],
    "node": [("/srv/web/src/users.ts", 14, "getUser", None), ("/srv/web/src/api.ts", 30, "handler", None)],
    "go": [("/srv/inventory/store.go", 42, "main.(*Store).Get", None), ("/srv/inventory/main.go", 18, "main.handler", None)],
    "rust": [("./src/ledger.rs", 27, "ledger_svc::post_entry", None), ("./src/main.rs", 9, "ledger_svc::main", None)],
}
UNKNOWN = {
    "python": ("WeirdCustomError", "flux capacitor overloaded"),
    "jvm": ("com.acme.FluxException", "flux capacitor overloaded"),
    "node": ("QuantumError", "flux capacitor overloaded"),
    "go": ("panic", "flux capacitor overloaded"),
    "rust": ("panic", "flux capacitor overloaded"),
}


def render(fam: str, etype: str, msg: str) -> list[str]:
    fr = FRAMES[fam]
    if fam == "python":
        out = ["Traceback (most recent call last):"]
        for f, ln, fn, _ in reversed(fr):
            out += [f'  File "{f}", line {ln}, in {fn}', "    pass"]
        return out + [f"{etype}: {msg}" if msg else etype]
    if fam == "jvm":
        return [f"{etype}: {msg}" if msg else etype] + [f"\tat {m}.{fn.split('.')[-1]}({f}:{ln})" for f, ln, fn, m in fr]
    if fam == "node":
        if etype == "FatalError":
            return [f"FATAL ERROR: {msg}"]
        code = re.match(r"\[(\w+)\] (.*)", msg)
        head = f"{etype} [{code[1]}]: {code[2]}" if code else f"{etype}: {msg}"
        return [head] + [f"    at {fn} ({f}:{ln}:5)" for f, ln, fn, _ in fr]
    if fam == "go":
        head = {"runtime error": f"panic: runtime error: {msg}", "fatal error": f"fatal error: {msg}"}.get(etype, f"panic: {msg}")
        body = []
        for f, ln, fn, _ in fr:
            body += [f"{fn}(...)", f"\t{f}:{ln} +0x1d"]
        return [head, "", "goroutine 1 [running]:"] + body
    f0, l0 = fr[0][0].lstrip("./"), fr[0][1]
    out = [f"thread 'main' panicked at {f0}:{l0}:5:", msg, "stack backtrace:",
           "   0: rust_begin_unwind", "             at /rustc/abc/library/std/src/panicking.rs:645:5"]
    for i, (f, ln, fn, _) in enumerate(fr, 1):
        out += [f"   {i}: {fn}", f"             at {f}:{ln}:5"]
    return out


VARIANTS = {
    "clean": lambda lines, svc: "\n".join(lines) + "\n",
    "logprefixed": lambda lines, svc: "\n".join(f"2026-09-26T10:00:00.000Z ERROR [{svc}] {ln}" for ln in lines) + "\n",
    "ansi_crlf": lambda lines, svc: "\r\n".join(f"\x1b[31m{ln}\x1b[0m" for ln in lines) + "\r\n",
}

MIXED = [  # (name, [(family, etype, msg)], expected, expected service): caller symptom first, source second
    ("web_timeout_orders_npe", [("node", "AxiosError", "timeout of 5000ms exceeded"),
                                ("jvm", "java.lang.NullPointerException", 'Cannot invoke "String.length()" because "n" is null')],
     "jvm.npe.helpful", "orders"),
    ("billing_json_ledger_unwrap", [("python", "json.decoder.JSONDecodeError", "Expecting value: line 1 column 1"),
                                    ("rust", "panic", "called `Option::unwrap()` on a `None` value")],
     "rust.unwrap_none", "ledger"),
    ("orders_timeout_inventory_nil", [("jvm", "java.net.SocketTimeoutException", "Read timed out"),
                                      ("go", "runtime error", "invalid memory address or nil pointer dereference")],
     "go.nil_pointer", "inventory"),
]

HANDWRITTEN = {  # tests/data file -> (expected, service)
    "python_none.txt": ("python.attribute_error.none_type", "billing"),
    "jvm_chained.txt": ("jvm.npe.helpful", "orders"),
    "node_cause.txt": ("node.econnrefused", "web"),
}


def main() -> None:
    sysdir = HERE / "sample-system"
    shutil.rmtree(sysdir, ignore_errors=True)
    for rel, content in SAMPLE_SYSTEM_FILES.items():
        p = sysdir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)

    shutil.rmtree(TRACES, ignore_errors=True)
    cases = []
    tables = {"python": PY_CASES, "jvm": JVM_CASES, "node": NODE_CASES, "go": GO_CASES,
              "rust": [("panic", m, e) for m, e in RUST_CASES]}
    for fam, rows in tables.items():
        rows = list(rows) + [(*UNKNOWN[fam], f"{fam}.unknown")]
        for etype, msg, expected in rows:
            for vname, v in VARIANTS.items():
                rel = f"{fam}/{expected.split('.', 1)[1]}__{vname}.txt"
                (TRACES / rel).parent.mkdir(parents=True, exist_ok=True)
                (TRACES / rel).write_bytes(v(render(fam, etype, msg), SERVICE[fam]).encode())
                frameless = fam == "node" and etype == "FatalError"   # V8 OOM has no frames → no service
                cases.append({"file": rel, "expected": expected, "service": None if frameless else SERVICE[fam]})
    for name, parts, expected, svc in MIXED:
        text = "".join(VARIANTS["logprefixed"](render(f, e, m), SERVICE[f]) for f, e, m in parts)
        rel = f"mixed/{name}.txt"
        (TRACES / rel).parent.mkdir(parents=True, exist_ok=True)
        (TRACES / rel).write_text(text)
        cases.append({"file": rel, "expected": expected, "service": svc})
    for src, (expected, svc) in HANDWRITTEN.items():
        rel = f"handwritten/{src}"
        (TRACES / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(HERE.parent / "tests" / "data" / src, TRACES / rel)
        cases.append({"file": rel, "expected": expected, "service": svc})
    (TRACES / "labels.yaml").write_text(yaml.safe_dump({"cases": cases}, sort_keys=False))
    print(f"wrote {len(cases)} cases")


if __name__ == "__main__":
    main()
```

Run: `python fixtures/build_corpus.py`
Expected: `wrote 216 cases` ((65 golden + 5 unknown) × 3 variants = 210, + 3 mixed + 3 handwritten). If you added golden rows, the count grows; anything ≥ 200 is fine. Then commit `fixtures/` in Step 7.

- [ ] **Step 3: Write the failing tests** — `tests/test_evaluation.py`

```python
from pathlib import Path
import yaml
from typer.testing import CliRunner
from debugagent.cli import app
from debugagent.evaluation import evaluate
from debugagent.scanner import scan
from debugagent.subagent import build_subagents

CORPUS = Path("fixtures/traces")
SYSTEM = Path("fixtures/sample-system")

def _mini_corpus(tmp_path):
    (tmp_path / "a.txt").write_text(open("tests/data/python_none.txt").read())
    (tmp_path / "b.txt").write_text(open("tests/data/python_none.txt").read())
    (tmp_path / "labels.yaml").write_text(yaml.safe_dump({"cases": [
        {"file": "a.txt", "expected": "python.attribute_error.none_type", "service": None},
        {"file": "b.txt", "expected": "python.key_error", "service": None}]}))
    return tmp_path

def test_accuracy_and_misses(tmp_path):
    r = evaluate(_mini_corpus(tmp_path), build_subagents())
    assert r.accuracy == 0.5 and r.coverage == 1.0
    assert [c.file for c in r.results if not c.correct] == ["b.txt"]

def test_cli_threshold_failure_exit_1(tmp_path):
    res = CliRunner().invoke(app, ["eval", str(_mini_corpus(tmp_path)), "--min-accuracy", "0.9"])
    assert res.exit_code == 1 and "accuracy 50.0% < 90.0%" in res.output

def test_corpus_has_top10_per_family():
    cases = yaml.safe_load((CORPUS / "labels.yaml").read_text())["cases"]
    for fam in ("python", "jvm", "node", "go", "rust"):
        known = {c["expected"] for c in cases if c["expected"].startswith(fam + ".") and not c["expected"].endswith(".unknown")}
        assert len(known) >= 10, fam

# The Stage 1 acceptance gate (spec targets, stricter values)
def test_committed_corpus_meets_stage1_targets():
    r = evaluate(CORPUS, build_subagents(), codebase=scan(SYSTEM, history=False))
    misses = [(c.file, c.expected, c.got, c.service_got) for c in r.results if not c.correct]
    assert r.accuracy >= 0.85, misses
    assert r.coverage >= 0.95, misses
    assert r.max_subagent_s < 2.0
    assert r.p95_latency_s < 5.0
```

- [ ] **Step 4: Run to verify failure**

Run: `pytest tests/test_evaluation.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'debugagent.evaluation'`

- [ ] **Step 5: Implement `evaluation.py`**

```python
import time
from dataclasses import dataclass
from pathlib import Path
import yaml
from debugagent.orchestrator import diagnose
from debugagent.scanner.models import CodebaseMap


@dataclass
class CaseResult:
    file: str
    expected: str
    got: str | None
    service_expected: str | None
    service_got: str | None
    confidence: float
    latency_s: float
    correct: bool


@dataclass
class EvalReport:
    results: list[CaseResult]
    accuracy: float
    coverage: float
    p95_latency_s: float
    max_subagent_s: float
    per_family: dict[str, float]


def _p95(xs: list[float]) -> float:
    s = sorted(xs)
    return s[min(len(s) - 1, int(round(0.95 * (len(s) - 1))))] if s else 0.0


def evaluate(corpus_dir: Path, subagents, codebase: CodebaseMap | None = None) -> EvalReport:
    corpus_dir = Path(corpus_dir)
    cases = yaml.safe_load((corpus_dir / "labels.yaml").read_text())["cases"]
    results: list[CaseResult] = []
    max_sub = 0.0
    for c in cases:
        text = (corpus_dir / c["file"]).read_bytes().decode("utf-8", errors="replace")
        t0 = time.perf_counter()
        d = diagnose(text, subagents, codebase=codebase)
        latency = time.perf_counter() - t0
        max_sub = max([max_sub] + [s for _, s in d.timings])
        top = d.top
        got, svc = (top.pattern_id, top.service) if top else (None, None)
        want_svc = c.get("service") if codebase is not None else None
        correct = got == c["expected"] and (want_svc is None or svc == want_svc)
        results.append(CaseResult(c["file"], c["expected"], got, want_svc, svc,
                                  top.confidence if top else 0.0, latency, correct))
    known = [r for r in results if not r.expected.endswith(".unknown")]
    per_family: dict[str, list[bool]] = {}
    for r in results:
        per_family.setdefault(r.expected.split(".", 1)[0], []).append(r.correct)
    return EvalReport(
        results=results,
        accuracy=sum(r.correct for r in results) / len(results) if results else 0.0,
        coverage=sum(1 for r in known if r.got and not r.got.endswith(".unknown")) / len(known) if known else 1.0,
        p95_latency_s=_p95([r.latency_s for r in results]),
        max_subagent_s=max_sub,
        per_family={k: sum(v) / len(v) for k, v in sorted(per_family.items())},
    )
```

Service is only checked when a codebase map is supplied, because without a map no hypothesis has a service.

- [ ] **Step 6: Add the `eval` command** to `cli.py`

```python
from debugagent.evaluation import evaluate

@app.command("eval")
def eval_cmd(
    corpus: Path = typer.Argument(..., exists=True, file_okay=False),
    codebase: Optional[Path] = typer.Option(None, "--codebase"),
    patterns: list[Path] = typer.Option([], "--patterns"),
    min_accuracy: float = typer.Option(0.85, "--min-accuracy"),
    min_coverage: float = typer.Option(0.95, "--min-coverage"),
    max_subagent_s: float = typer.Option(2.0, "--max-subagent-s"),
) -> None:
    """Measure accuracy, coverage and latency on a labeled trace corpus."""
    r = evaluate(corpus, build_subagents(patterns), codebase=_load_codebase(codebase))
    typer.echo(f"cases {len(r.results)}  accuracy {r.accuracy:.1%}  coverage {r.coverage:.1%}  "
               f"p95 {r.p95_latency_s * 1000:.0f} ms  max subagent {r.max_subagent_s * 1000:.0f} ms")
    for fam, acc in r.per_family.items():
        typer.echo(f"  {fam:<8} {acc:.1%}")
    for c in (c for c in r.results if not c.correct):
        typer.echo(f"  MISS {c.file}: expected {c.expected}"
                   f"{'@' + c.service_expected if c.service_expected else ''}, got {c.got}"
                   f"{'@' + c.service_got if c.service_got else ''}")
    failures = []
    if r.accuracy < min_accuracy:
        failures.append(f"accuracy {r.accuracy:.1%} < {min_accuracy:.1%}")
    if r.coverage < min_coverage:
        failures.append(f"coverage {r.coverage:.1%} < {min_coverage:.1%}")
    if r.max_subagent_s >= max_subagent_s:
        failures.append(f"max subagent {r.max_subagent_s:.2f}s >= {max_subagent_s:.2f}s")
    if failures:
        typer.echo("FAIL: " + "; ".join(failures), err=True)
        raise typer.Exit(1)
    typer.echo("PASS")
```

- [ ] **Step 7: Run everything, debug any misses, commit**

Run: `pytest -v && debugagent eval fixtures/traces --codebase fixtures/sample-system`
Expected: PASS, with accuracy ≥ 85% and coverage ≥ 95%. If there are misses, use **superpowers:systematic-debugging** to find the root cause (usually a parser edge case or a pattern regex) and add a failing test first, **before** changing any regex.

```bash
git add -A && git commit -m "feat: sample polyglot system, labeled trace corpus and eval harness with stage-1 gates"
```

### Task 13: Learning loop: fix log, first-try fix rate, promotion after 10 similar fixes

**Files:**
- Create: `src/debugagent/learning.py`
- Modify: `src/debugagent/cli.py` (`learn`, `promote`, `stats` commands; `diagnose`/`eval` auto-load `./.debugagent/patterns` when present)
- Test: `tests/test_learning.py`

**Interfaces:**
- Consumes: `Hypothesis` (Task 1), `diagnose` (Task 10), and `load_patterns`/`match_trace` (Task 2). The loader already honors `source:` from YAML, so learned files keep `source: learned`.
- Produces:
  - `message_signature(msg: str) -> str`: replaces UUIDs, hex, quoted strings, and numbers with `<uuid>`, `<hex>`, `<str>`, and `<n>`.
  - `signature_regex(sig: str) -> str`.
  - `record_fix(log: Path, h: Hypothesis, fix: str, worked: bool, fix_index: int | None = None) -> dict`.
  - `promote(log: Path, out_dir: Path, threshold: int = PROMOTION_THRESHOLD) -> list[Path]`.
  - `fix_stats(log: Path) -> dict[str, float]` (keys: `entries`, `first_try_rate`).
  - Constants: `PROMOTION_THRESHOLD = 10` (spec: "After 10 similar fixes, elevate to a pattern"), `DEFAULT_FIXLOG = Path(".debugagent/fixlog.jsonl")`, `DEFAULT_LEARNED_DIR = Path(".debugagent/patterns")`.
  - CLI:
    - `debugagent learn TRACE --fix TEXT [--fix-index N] [--failed] [--codebase PATH] [--log FILE]`
    - `debugagent promote [--log FILE] [--out DIR] [--threshold N]`
    - `debugagent stats [--log FILE]`

Promotion scope: only groups whose diagnosis was `<family>.unknown` and whose fixes **worked** get promoted. Known patterns aren't overwritten. "Manual pattern addition" (spec) means dropping a YAML file into `.debugagent/patterns/`; "automated" means `promote`.

- [ ] **Step 1: Write the failing tests** — `tests/test_learning.py`

```python
import yaml
from typer.testing import CliRunner
from debugagent.cli import app
from debugagent.learning import fix_stats, message_signature, promote, record_fix, signature_regex
from debugagent.models import Family, Frame, ParsedTrace
from debugagent.patterns.loader import load_patterns
from debugagent.patterns.matcher import match_trace

def _unknown(n: int):
    t = ParsedTrace(Family.PYTHON, "app.errors.OrderStuck", f"order {n} stuck in state 'PENDING'",
                    (Frame("/srv/billing/app/orders.py", 10, "advance"),))
    return match_trace(t, [])

def test_signature_normalizes_variable_parts():
    assert message_signature("order 12345 stuck in state 'PENDING'") == "order <n> stuck in state <str>"
    assert message_signature("id 0x1F and 3f2b8c1e-1d2a-4b3c-9d8e-0a1b2c3d4e5f") == "id <hex> and <uuid>"
    assert __import__("re").search(signature_regex("order <n> stuck in state <str>"), "order 7 stuck in state 'X'")

def test_nine_is_not_enough_ten_promotes_once(tmp_path):
    log, out = tmp_path / "fix.jsonl", tmp_path / "learned"
    for i in range(9):
        record_fix(log, _unknown(i), "Re-run the state machine sweeper", worked=True)
    assert promote(log, out) == []
    record_fix(log, _unknown(99), "Re-run the state machine sweeper", worked=True)
    [path] = promote(log, out)
    data = yaml.safe_load(path.read_text())
    assert data["source"] == "learned" and len(data["fixes"]) == 2
    assert promote(log, out) == []                           # idempotent

def test_learned_pattern_matches_new_occurrence(tmp_path):
    log, out = tmp_path / "fix.jsonl", tmp_path / "learned"
    for i in range(10):
        record_fix(log, _unknown(i), "Re-run the state machine sweeper", worked=True)
    promote(log, out)
    pats = load_patterns(out)
    h = match_trace(ParsedTrace(Family.PYTHON, "app.errors.OrderStuck", "order 555 stuck in state 'PAID'",
                                (Frame("x.py", 1, "f"),)), pats)
    assert h.pattern_id.startswith("python.learned.") and h.confidence == 0.75

def test_failed_fixes_and_known_patterns_do_not_promote(tmp_path):
    log, out = tmp_path / "fix.jsonl", tmp_path / "learned"
    for i in range(12):
        record_fix(log, _unknown(i), "try X", worked=False)
    assert promote(log, out) == []

def test_first_try_rate(tmp_path):
    log = tmp_path / "fix.jsonl"
    record_fix(log, _unknown(1), "a", worked=True, fix_index=1)
    record_fix(log, _unknown(2), "b", worked=True, fix_index=2)
    record_fix(log, _unknown(3), "a", worked=False, fix_index=1)
    record_fix(log, _unknown(4), "a", worked=True, fix_index=1)
    assert fix_stats(log) == {"entries": 4, "first_try_rate": 0.5}

def test_cli_learn_promote_then_diagnose_uses_learned(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = CliRunner()
    trace = tmp_path / "t.txt"
    for i in range(10):
        trace.write_text('Traceback (most recent call last):\n  File "/srv/billing/app/orders.py", line 10, in advance\n'
                         f"app.errors.OrderStuck: order {i} stuck in state 'PENDING'\n")
        assert r.invoke(app, ["learn", str(trace), "--fix", "Re-run the sweeper"]).exit_code == 0
    assert r.invoke(app, ["promote"]).exit_code == 0
    out = r.invoke(app, ["diagnose", str(trace)])
    assert out.exit_code == 0 and "python.learned." in out.stdout
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_learning.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'debugagent.learning'`

- [ ] **Step 3: Implement `learning.py`**

```python
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import yaml
from debugagent.models import Hypothesis

PROMOTION_THRESHOLD = 10
DEFAULT_FIXLOG = Path(".debugagent/fixlog.jsonl")
DEFAULT_LEARNED_DIR = Path(".debugagent/patterns")
_PLACEHOLDERS = ("<uuid>", "<hex>", "<str>", "<n>")
_SUBS = [
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I), "<uuid>"),
    (re.compile(r"\b0x[0-9a-f]+\b", re.I), "<hex>"),
    (re.compile(r"'[^']*'|\"[^\"]*\"|`[^`]*`"), "<str>"),
    (re.compile(r"\b\d+(?:\.\d+)*\b"), "<n>"),
]


def message_signature(msg: str) -> str:
    s = msg.strip()[:300]
    for rx, rep in _SUBS:
        s = rx.sub(rep, s)
    return re.sub(r"\s+", " ", s)


def signature_regex(sig: str) -> str:
    parts = re.split(r"(<uuid>|<hex>|<str>|<n>)", sig)
    return "^" + "".join(".+?" if p in _PLACEHOLDERS else re.escape(p) for p in parts)


def record_fix(log: Path, h: Hypothesis, fix: str, worked: bool, fix_index: int | None = None) -> dict:
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "family": h.family.value, "error_type": h.error_type, "signature": message_signature(h.message),
        "pattern_id": h.pattern_id, "service": h.service, "fix": fix.strip(),
        "fix_index": fix_index, "worked": worked,
    }
    log = Path(log)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def _entries(log: Path) -> list[dict]:
    log = Path(log)
    return [json.loads(ln) for ln in log.read_text().splitlines() if ln.strip()] if log.is_file() else []


def promote(log: Path, out_dir: Path, threshold: int = PROMOTION_THRESHOLD) -> list[Path]:
    groups: dict[tuple[str, str, str], list[dict]] = {}
    for e in _entries(log):
        if e["worked"] and e["pattern_id"].endswith(".unknown"):
            groups.setdefault((e["family"], e["error_type"], e["signature"]), []).append(e)
    written: list[Path] = []
    for (fam, etype, sig), es in sorted(groups.items()):
        if len(es) < threshold:
            continue
        key = hashlib.sha1(f"{fam}|{etype}|{sig}".encode()).hexdigest()[:10]
        path = Path(out_dir) / fam / f"learned_{key}.yaml"
        if path.exists():
            continue
        top = Counter(e["fix"] for e in es).most_common(3)
        fixes = [{"summary": f, "tradeoff": f"Resolved {n} of {len(es)} past incidents"} for f, n in top]
        if len(fixes) < 2:
            fixes.append({"summary": f"Review the {len(es)} past incidents in the fix log for variants",
                          "tradeoff": "Manual and slower, but shows the context of each occurrence"})
        services = sorted({e["service"] for e in es if e.get("service")})
        data = {
            "id": f"{fam}.learned.{key}", "family": fam, "error_type": re.escape(etype),
            "message_regex": signature_regex(sig), "category": "code",
            "root_cause": (f"Learned from {len(es)} resolved incidents"
                           f"{' in ' + ', '.join(services) if services else ''}: {etype}: {sig}. "
                           f"Most common fix: {top[0][0]}"),
            "base_confidence": 0.75, "fixes": fixes, "tags": ["learned"], "source": "learned",
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(data, sort_keys=False))
        written.append(path)
    return written


def fix_stats(log: Path) -> dict[str, float]:
    es = _entries(log)
    indexed = [e for e in es if e.get("fix_index") is not None]
    first = [e for e in indexed if e["fix_index"] == 1 and e["worked"]]
    return {"entries": len(es), "first_try_rate": len(first) / len(indexed) if indexed else 0.0}
```

- [ ] **Step 4: Add the CLI commands** and auto-load learned patterns

```python
from debugagent.learning import DEFAULT_FIXLOG, DEFAULT_LEARNED_DIR, fix_stats, promote as run_promote, record_fix

def _pattern_dirs(extra: list[Path]) -> list[Path]:
    return [*extra, *([DEFAULT_LEARNED_DIR] if DEFAULT_LEARNED_DIR.is_dir() else [])]
# diagnose and eval now call build_subagents(_pattern_dirs(patterns))

@app.command()
def learn(
    source: str = typer.Argument(..., help="Trace file that was fixed"),
    fix: str = typer.Option(..., "--fix", help="What actually fixed it"),
    fix_index: Optional[int] = typer.Option(None, "--fix-index", help="Which suggested fix (1-based) was applied"),
    failed: bool = typer.Option(False, "--failed", help="The fix did NOT work"),
    codebase: Optional[Path] = typer.Option(None, "--codebase"),
    log: Path = typer.Option(DEFAULT_FIXLOG, "--log"),
) -> None:
    """Record the outcome of a fix (feeds first-try accuracy and pattern promotion)."""
    d = run_diagnose(_read_input(source), build_subagents(_pattern_dirs([])), codebase=_load_codebase(codebase))
    if d.top is None:
        typer.echo("No stack trace found in input.", err=True)
        raise typer.Exit(2)
    e = record_fix(log, d.top, fix, worked=not failed, fix_index=fix_index)
    typer.echo(f"Recorded {'failed' if failed else 'working'} fix for {e['pattern_id']} ({e['signature']})")

@app.command()
def promote(
    log: Path = typer.Option(DEFAULT_FIXLOG, "--log"),
    out: Path = typer.Option(DEFAULT_LEARNED_DIR, "--out"),
    threshold: int = typer.Option(10, "--threshold"),
) -> None:
    """Promote recurring, successfully-fixed unknown errors into learned patterns."""
    written = run_promote(log, out, threshold)
    for p in written:
        typer.echo(f"Learned pattern: {p}")
    typer.echo(f"{len(written)} new pattern(s)")

@app.command()
def stats(log: Path = typer.Option(DEFAULT_FIXLOG, "--log")) -> None:
    """Show fix-log stats (spec metric: proposed fixes that work on first try)."""
    s = fix_stats(log)
    typer.echo(f"entries {s['entries']}  first-try fix rate {s['first_try_rate']:.1%}")
```

- [ ] **Step 5: Run all tests to verify pass**

Run: `pytest -v --cov=debugagent --cov-report=term-missing`
Expected: PASS, with total coverage > 80% (spec).

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: learning loop (fix log, first-try rate, promotion after 10 fixes)"
```

### Task 14: Real-repo validation (sample first, then real)

This is a procedure, not new code. Its only code changes are TDD fixes for misses it uncovers.

**Files:**
- Create: `docs/stage1-validation.md` (aggregate numbers only; never commit real traces)
- Private, outside git: `~/debug-agent-private/real-corpus/` (traces + `labels.yaml` in the Task 12 format)
- Possibly modify: parsers or patterns (via TDD, with a **redacted minimal** trace added under `tests/data/`), and `<your repo>/.debugagent/patterns/*.yaml` for repo-specific manual patterns

- [ ] **Step 1: Get the real repo path(s) from the user and scan them**

```bash
debugagent scan /path/to/your/services
```
Check the output against reality: every service found, the right family, frameworks detected, and the `calls:` edges matching the architecture (docker-compose / k8s / service mesh). For each gap, first add a failing scanner test that reproduces the layout under `tests/scanner/`, then fix it.

- [ ] **Step 2: Build the real corpus**

From ELK/Datadog/incident tickets, collect **≥ 30 resolved incidents**, with at least 5 per language family that you actually run. **Redact** secrets, tokens, emails, and customer IDs before saving. Have the engineer who resolved each incident write its `labels.yaml` entry: `expected` is the pattern id matching the true root cause (or `<family>.unknown` if none fits), and `service` is the true origin service.

- [ ] **Step 3: Evaluate**

```bash
debugagent eval ~/debug-agent-private/real-corpus --codebase /path/to/your/services
```

- [ ] **Step 4: Debug every miss with superpowers:systematic-debugging**

Put each miss in one of four classes: parser miss (trace not parsed), pattern miss (parsed but unknown or wrong), attribution miss (right pattern, wrong service), or label error. Fix each with a failing test first. Generic patterns go into the built-in DB; codebase-specific ones go into `<repo>/.debugagent/patterns/`. Re-run Step 3.

- [ ] **Step 5: Live check on fresh incidents**

For the next 5 real errors, run `debugagent diagnose` as soon as the trace is available. Record the time to hypothesis (target < 5 min; expected < 5 s), and log each outcome with `debugagent learn … --fix-index N [--failed]`. Then run `debugagent stats` to get the first-try fix rate.

- [ ] **Step 6: Write `docs/stage1-validation.md` and commit**

Include the case count, accuracy, coverage, p95 and max subagent latency, per-family accuracy, a table of misses by class (no raw traces), and the first-try rate.

```bash
git add docs/stage1-validation.md && git commit -m "docs: stage 1 validation against real services"
```

**Stage 1 exit criteria** (all must hold on the real corpus):
- accuracy ≥ 85%
- coverage ≥ 95%
- max subagent < 2 s
- all tests green
- coverage > 80%

If accuracy stays below 85% after two debug iterations, that is the evidence-based trigger to add optional Claude-backed refinement (Stage 1.5) behind the existing `LanguageSubagent` seam, not before.

---

## Roadmap after Stage 1 (each gets its own brainstorm → spec → plan cycle)

Stage 1 deliberately produces the contracts the later stages consume:
- the `render_json` diagnosis schema
- `.debugagent/codebase.json` (`CodebaseMap`)
- `.debugagent/fixlog.jsonl`
- the pattern `tags` vocabulary

**Stage 2: CI/CD Loop (spec weeks 5–8).**
- Observation engine for your CI (GitHub Actions / GitLab / Jenkins API).
- Flaky-test and slow-stage detection after 20 and 50 runs, and risky-deploy scoring after 100.
- Remediations: isolate/retry flaky tests, cache, canary.
- The spec's guardrails: never skip a test that has failed before, audit-log every decision, human review for prod pipeline changes.
- Failed test logs feed into `debugagent diagnose`.
- Resolve first: the spec defines "flaky" in two different ways ("fail <80% of time" and "Tests failing <95% of time") that need one precise definition.

**Stage 3: On-Call Agent (spec weeks 9–12).**
- Alert ingestion and the triage decision tree.
- Remediations from the spec's allow-list only: restart, clear cache, scale out, failover, rollback. Schema, permission, and data changes are forbidden.
- Health checks after 30 s, with rollback and escalation.
- The escalation format from the spec, with Debug Agent evidence and CI/CD deploy correlation.
- Rollout: advisory mode first.

**Stage 4: Continuous Learning.**
- Close the loop: on-call resolutions call `record_fix`, `promote` runs on a schedule, and CI/CD outcomes refine the risk scores.

---

## Spec coverage (Stage 1)

| Spec requirement | Task |
|---|---|
| 5 language families: JVM, Python, Node, Go, Rust | 2, 4, 5, 6, 7 |
| Pattern DB per family, top 10 error types | 2, 4–7 (≥ 12 each) |
| Codebase Scanner: languages, frameworks, dependencies, dependency graph, queryable store | 9 |
| Failure patterns from git history ("this service has timezone bugs") | 11 |
| Codebase-specific learner | 11 (history boosts), 13 (learned patterns) |
| Multi-language orchestrator, parallel subagents, < 2 s each | 8 |
| Root Cause Aggregator across services | 10 |
| Output: diagnosis + confidence, 2–3 fixes with trade-offs, locations, repro test | 2, 3 |
| Learning loop: manual, then automated after 10 fixes | 13 |
| Metrics: diagnosis time, accuracy, coverage, subagent latency | 12 (eval), 13 (first-try rate), 14 |
| Test suite with 10+ error types; unit coverage > 80% | 2–7, 12, 13 |
| Start with a sample project, then real microservices | 12, 14 |
| Read-only rollout ("shows diagnostics, doesn't act") | Global Constraints; `scan` test in 9 |

## Execution recommendation

**Native** (one implementer in-session, then a single whole-branch review). The 14 tasks are sequential, and later tasks change the signatures of earlier ones (`diagnose` and `aggregate` grow in Tasks 8, 10, and 11). One implementer holding that context avoids interface drift. A mistake is also cheap to catch here: the tool is offline and read-only, and the Task 12 eval gate catches regressions. Use **Subagent-driven** instead if you want an independent reviewer gate on every task.

**Before execution:** create the repo at `~/code/debug-agent` (Task 1). Pass the executing session the spec path and this plan. When anything misbehaves during implementation, use **superpowers:systematic-debugging** before changing code.
