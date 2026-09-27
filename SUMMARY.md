# Debug Agent — Implementation Summary

> Auto-updated after each completed task. See `PLAN/snuggly-squishing-patterson.md` for the full plan.

---

## Task 1 — Project Skeleton, Core Models, Input Normalization, and Family Detection

**Status:** ✅ Complete  
**Commit:** `4c4ab21`

### What was done

Set up the full project skeleton and implemented the foundational data models and input pipeline that every subsequent task depends on.

### Files created

| File | Description |
|---|---|
| `pyproject.toml` | Project metadata; runtime deps (`typer>=0.12`, `pyyaml>=6.0`); dev deps (`pytest>=8`, `pytest-cov>=5`); `debugagent` CLI entry point; hatchling build backend |
| `src/debugagent/__init__.py` | Package marker |
| `src/debugagent/models.py` | Core data models: `Family` (str Enum: jvm, python, node, go, rust), `Frame`, `ParsedTrace` (with `.root()` chain walker and `.short_error_type`), `FixOption`, `Hypothesis`, `Diagnosis` (with `.top`) |
| `src/debugagent/detect.py` | `normalize()` — strips ANSI codes, CRLF line endings, log prefixes (timestamp / level / service), and caps input at 5 MB tail. `detect_families()` — regex signatures for all 5 language families. `MAX_INPUT_CHARS = 5_000_000` |
| `tests/test_models.py` | 2 tests: `.root()` walks full cause chain to innermost; `.short_error_type` strips package prefix |
| `tests/test_detect.py` | 5 tests: detects each family individually; detects mixed multi-family input; empty/binary garbage returns empty set; log-wrapped traces normalize correctly (Review Focus #1); oversized input keeps tail |
| `docs/superpowers/specs/2026-09-26-microservices-ai-workflow-design.md` | Original spec copied into repo |
| `.gitignore` | Ignores `.venv`, `__pycache__`, `*.egg-info`, `.debugagent`, `.pytest_cache` |

### Test results

```
7 passed in 0.01s
```

### Key design decisions

- `frames[0]` = innermost frame (parsers printing outermost-first must reverse the list)
- `normalize()` truncates from the **tail** to preserve the most recent/relevant log lines
- All family-detection regexes tolerate leading `\s*` so stripped log prefixes don't break indentation matching


---

## Task 1 — Post-merge Fixes (commit `36e1b0d`)

**Status:** ✅ Complete

Two high-severity bugs found by extended test review were fixed before Task 2 began, since Task 2's Python parser depends on correct indentation from `normalize()`.

### Fix 1 — `normalize()` was eating payload indentation (High)

**Root cause:** `_PREFIX` used `\s+` at the end of each component, so `ERROR [billing]   File "app.py"` consumed the two-space indent that belongs to the `File` line.
**First attempt (commit `36e1b0d`) introduced two regressions:** a trailing `(?=\S)` lookahead made the regex back off on indented payloads, leaving `[billing]   File "app.py"` with the service tag still attached; and `re.IGNORECASE` turned the payload's own `Error:` / `Warning:` into a "level", so `Error: boom` became `boom`.
**Final fix (uncommitted):** Each prefix component consumes exactly one literal space and the lookahead is gone, so extra indentation stays with the payload. Levels match only as UPPERCASE (optional brackets/colon) or lowercase *without* a colon; mixed-case `Error:` is never stripped. `_ANSI` also strips OSC sequences (terminal title/link codes).
**Pinning tests:** `test_normalize_preserves_indentation_after_prefix_strip` (now exact line equality), `test_normalize_preserves_tab_indentation_after_prefix_strip`, `test_normalize_strips_lowercase_and_uppercase_colon_levels`, `test_normalize_never_eats_payload_error_type`

### Fix 2 — Node ECONNREFUSED traces not detected (High)

**Root cause:** The `NODE` signature only matched frames ending in `.js`/`.ts`/etc. Node.js internal frames (`node:net:1555:16`, `node:internal/stream_base_commons:183:27`) have no file extension and were silently skipped, causing the whole trace to go undetected. This would have broken Review Focus #4 (mixed Node+Java cross-service diagnosis).
**Fix:** `NODE` signature now includes an alternative branch: `node:[\w/.-]+:\d+:\d+`.
**Pinning tests:** `test_detects_node_internal_frames`, `test_detects_node_internal_plus_java`

### Test results after fixes

```
13 passed in 0.05s  (coverage 99%, mypy --strict clean)
```

### Deferred items (to be fixed in their owning tasks)

| # | Severity | Item | Owning task |
|---|---|---|---|
| 3 | Medium | JVM `(Native Method)` / `(Unknown Source)` frames not detected | Task 4 |
| 4 | Medium | `short_error_type` doesn't split on `::` for Rust | Task 7 |
| 5a | Low | Message starting with a level word loses that word | Task 1 cleanup (acceptable) |
| 5b | Low | `[main] INFO x` not stripped (service tag before level) | Future |
| 5c | Low | Lowercase levels not stripped | Fixed in Fix 1 (lowercase without colon) |
| 5d | Low | OSC ANSI sequences survive | Fixed in Fix 1 above |
| 5e | Low | `File "<string>"` / `File "<stdin>"` don't match Python sig alone | Task 2 |
| 5f | Low | Node paths with spaces; indented raw `panic:` not detected | Tasks 5 / 6 |
| 5g | Low | 10 auto-fixable ruff style issues | Task 1 cleanup |

---

## Task 2 — Python Parser, Pattern DB, Matcher, Repro Templates, and 13 Python Patterns

**Status:** ✅ Complete
**Commit:** `3d19482`

### What was done

Built the full pattern-matching pipeline that takes raw Python tracebacks all the way to ranked hypotheses with fixes and repro test skeletons. This is the first vertical slice: Python traces → hypotheses.

### Files created

| File | Description |
|---|---|
| `src/debugagent/parsers/python.py` | Stateful line-by-line parser: detects `Traceback` headers, `File` frame lines, caret markers, chained-exception separators, and exception lines. Reverses frame list so `frames[0]` is innermost. Returns a list of `ParsedTrace` with `.cause` chains for chained exceptions. |
| `src/debugagent/parsers/__init__.py` | `PARSERS: dict[Family, Callable]` registry — Python only for now; Tasks 4–7 add the rest. |
| `src/debugagent/patterns/repro.py` | `render_repro()` using `string.Template`. `FAMILY_REPRO` dict holds one template per language family (Python, JVM, Node, Go, Rust) for use in later tasks. |
| `src/debugagent/patterns/loader.py` | `Pattern` dataclass, `PatternError`, `DEFAULT_PATTERN_DIR`, `load_patterns(*dirs)` — validates required fields, confidence range (0,1), 2–3 fixes, regex compilation; assigns `source` as `"builtin"` or `"manual"`. |
| `src/debugagent/patterns/matcher.py` | `match_trace()` — walks `.root()`, scores patterns (specific message match beats higher-confidence generic by priority tier, generic discounted by 0.85), returns `<family>.unknown` at confidence 0.1 for no match. `is_library_frame()` — path/module heuristics for all 5 families. |
| `src/debugagent/patterns/data/python/*.yaml` | 13 Python patterns (see table below) |
| `tests/parsers/test_python.py` | 6 parser tests |
| `tests/patterns/test_loader.py` | 8 loader tests (valid load, 4 invalid mutations, duplicate ids, missing dir, ≥10 builtins) |
| `tests/patterns/test_matcher.py` | 7 matcher tests (specific beats generic, generic discounted, root cause not wrapper, unknown, library frame skip, repro rendered, `is_library_frame`) |
| `tests/patterns/test_python_patterns.py` | 13 golden tests — one per pattern |
| `tests/__init__.py`, `tests/parsers/__init__.py`, `tests/patterns/__init__.py` | Package markers for cross-test imports |

### Python patterns (13)

| Pattern ID | Error type | Message regex | Category | Confidence |
|---|---|---|---|---|
| `python.attribute_error.none_type` | `AttributeError` | `'NoneType' object has no attribute` | code | 0.85 |
| `python.attribute_error.missing_attr` | `AttributeError` | `has no attribute` | code | 0.60 |
| `python.import_error.module_not_found` | `ModuleNotFoundError` | `No module named` | config | 0.85 |
| `python.import_error.cannot_import_name` | `ImportError` | `cannot import name` | code | 0.80 |
| `python.key_error` | `KeyError` | _(generic)_ | code | 0.70 |
| `python.type_error.none_not_subscriptable` | `TypeError` | `'NoneType' object is not …` | code | 0.85 |
| `python.type_error.call_signature` | `TypeError` | missing/extra args pattern | code | 0.85 |
| `python.index_error` | `IndexError` | `index out of range` | code | 0.80 |
| `python.recursion_error` | `RecursionError` | `maximum recursion depth exceeded` | code | 0.85 |
| `python.timeout` | `TimeoutError\|ReadTimeout\|…` | _(generic)_ | dependency | 0.75 |
| `python.connection_refused` | `ConnectionRefusedError\|…` | `Connection refused\|Errno 111\|…` | dependency | 0.80 |
| `python.json_decode` | `JSONDecodeError` | _(generic)_ | dependency | 0.75 |
| `python.unbound_local` | `UnboundLocalError` | _(generic)_ | code | 0.85 |

### Test results

```
47 passed in 0.45s
```

### Key design decisions

- **Specific-beats-generic scoring:** a pattern with a `message_regex` match is always preferred over one without, regardless of `base_confidence`. Generic matches are discounted by factor 0.85.
- **Root cause matching:** `match_trace()` calls `.root()` so chained exceptions are always diagnosed at the original cause, not the outer wrapper.
- **Library frame filtering:** `is_library_frame()` uses path heuristics for Python/Node/Go/Rust and package-prefix heuristics for JVM. Locations exposed in `Hypothesis` are app frames only (max 3), falling back to the first frame if all are library frames.
- **`FAMILY_REPRO` templates pre-written for all 5 families** so Tasks 4–7 get repro rendering for free.

---

## Task 2 — Post-Review Fixes

**Status:** ✅ Complete (uncommitted)

Extended review (≈60 probe cases on top of the suite) found one data bug and several inputs that were silently dropped or mis-parsed. All fixed before Task 3, since `diagnose` builds directly on the parser and loader.

### Fix 1 — `tags: [null]` loaded as Python `None` (High)

**Root cause:** YAML parses unquoted `null` as `None`, so `attribute_error.none_type` and `type_error.none_not_subscriptable` had `tags == (None,)`, which would crash or print `None` in the Task 3 renderer.
**Fix:** Quoted as `"null"` in both files; the loader now rejects non-string tags with a hint to quote YAML keywords (`null`/`yes`/`no`).

### Fix 2 — Tracebacks dropped entirely, not even `unknown` (High)

Violated Review Focus #3 (unrecognized errors must still get a 0.1 `<family>.unknown`).

| Input | Root cause | Fix |
|---|---|---|
| `socket.timeout: timed out` | `_EXC` required the last name segment to be Capitalised | Dotted names may end lowercase; `timeout` added to `python.timeout` `error_type` |
| `app.errors.PaymentDeclined` (no message) | Bare names were only accepted with an `Error`/`Exception`/… suffix | Dotted names are accepted without a message |
| `File "x.py", line 3` (no `, in func`) | `_FRAME` required `, in <func>` | `, in` optional; function recorded as `<unknown>` |
| Header-less SyntaxError output | Parsing only began at `Traceback …` | A `File` line also opens a trace |
| Exception groups (3.11+ `+`/`\|` box format) | Gutters and separators were not understood | Gutters stripped, separators skipped; first sub-exception becomes the group's `cause`, later sub-exceptions are separate traces |

### Fix 3 — SyntaxError pointed at the importing file (Medium)

**Root cause:** the syntax-error location line has no `, in`, so it was skipped and `frames[0]` was the importer.
**Fix:** covered by the optional-`, in` change above; `frames[0]` is now the broken file.

### Fix 4 — Indented source lines taken as the exception (Medium)

**Root cause:** a source line like `    Foo: int = 3` matched `_EXC`, ending the trace before the real exception line.
**Fix:** only unindented lines can be exception lines (CPython's format). This relies on Task 1's indentation-preserving `normalize()`.

### Fix 5 — Malformed manual patterns crashed with raw errors (Medium)

**Root cause:** a fix without `tradeoff` raised `KeyError`; a non-string `root_cause` raised `AttributeError`.
**Fix:** the loader validates each fix's `summary`/`tradeoff`, the string fields `id`/`root_cause`/`error_type`, `message_regex`, and `tags`, raising `PatternError` with the file name.

### Other changes

- `types-PyYAML>=6.0` added to dev deps; `dict[str, Any]` annotations added, so `mypy --strict` is clean.

### New tests (14)

- `tests/parsers/test_python.py`: dotted lowercase type, dotted custom exception without a message, indented source line, SyntaxError innermost frame, header-less SyntaxError, exception group root
- `tests/patterns/test_loader.py`: 5 parametrized malformed-field cases, built-in tags are all strings
- `tests/patterns/test_matcher.py`: previously-dropped traces now get a hypothesis
- `tests/patterns/test_python_patterns.py`: `socket.timeout` → `python.timeout`

### Test results after fixes

```
61 passed in 0.15s  (coverage 96%, mypy --strict clean)
Perf: 7.1 MB log / 1,409 traces in 0.49 s
```

### Deferred items

| Severity | Item | Owning task |
|---|---|---|
| Low | A user pattern with a built-in's `id` is rejected as a duplicate (override policy undecided) | Task 13 |
| Low | Multi-line exception messages keep only the first line | Future |
| Low | 19 auto-fixable ruff style issues | Cleanup |

---

## Task 3 — Language Subagent, Sequential Diagnose, Renderers, and the Diagnose CLI

**Status:** ✅ Complete
**Commit:** `cc6cdf4`

### What was done

Wired the parser + pattern pipeline into a working CLI. `debugagent diagnose` now runs end-to-end for Python: reads a file or stdin, normalizes, detects families, dispatches subagents, aggregates hypotheses, and outputs a full diagnosis in text or JSON.

### Files created

| File | Description |
|---|---|
| `src/debugagent/subagent.py` | `LanguageSubagent` dataclass with `.run(text) -> list[Hypothesis]`; `build_subagents()` loads patterns and wires each registered parser to its family's pattern slice |
| `src/debugagent/aggregator.py` | `aggregate()` deduplicates hypotheses by `(pattern_id, file, line, service)` keeping the highest-confidence copy, then sorts by confidence desc |
| `src/debugagent/orchestrator.py` | Sequential `diagnose()`: normalizes input, detects families, runs each subagent, aggregates, attaches truncation note if input exceeded 5 MB |
| `src/debugagent/render.py` | `render_text()` — full output contract (confidence %, root cause, locations, fixes with trade-offs, repro test); `render_json()` — round-trippable JSON |
| `src/debugagent/cli.py` | `typer` app: `diagnose [SOURCE\|-] [--json] [--patterns DIR]...`; exit 0 = diagnosed, 1 = pattern DB error, 2 = no input / no trace / file not found |
| `tests/data/python_none.txt` | Fixture: Python `AttributeError: 'NoneType' object has no attribute 'zip'` traceback |
| `tests/test_subagent.py` | 2 tests: family isolation, one hypothesis per trace |
| `tests/test_orchestrator.py` | 4 tests: end-to-end Python, deduplication, no-trace empty diagnosis, truncation note |
| `tests/test_render.py` | 2 tests: text output contract sections, JSON round-trip |
| `tests/test_cli.py` | 7 tests: file input, stdin JSON, empty stdin exit 2, binary garbage exit 2, missing file exit 2, bad pattern dir exit 1, large log within 5 s budget |

### Test results

```
76 passed in 2.07s
```

### Key design decisions

- **`CliRunner()` without `mix_stderr`** — this typer version already merges stderr into stdout by default; the `mix_stderr` kwarg was removed.
- **Deduplication key** is `(pattern_id, file, line, service)` — the same exception at the same location appearing twice (e.g. log replay) produces exactly one hypothesis.
- **Exit codes** strictly follow the spec: 0 = diagnosis produced, 1 = pattern DB broken, 2 = bad/missing input or no recognizable trace.
- **`diagnose` is still sequential** — Task 8 parallelizes it with a thread pool and per-subagent timeouts. The interface (`diagnose(text, subagents)`) is unchanged so Task 8 is a drop-in replacement.

---

## Task 3 — Post-Review Fixes

**Status:** ✅ Complete (uncommitted)

### Fixes

| Severity | Issue | Fix |
|---|---|---|
| High | Unreadable input file crashed with a raw traceback (Review Focus #5) | `cli._read_input` catches `OSError`: "Cannot read input file …", exit 2 |
| High | Directory as input said "file not found" | "Input is a directory, not a file", exit 2 |
| Medium | Misspelled `--patterns` dir silently ignored | "Pattern directory not found", exit 1 |
| Medium | Trace from a language with no analyzer yet reported "No stack trace found (supported: JVM, …)" | CLI: "Detected jvm trace(s), but no analyzer is available…"; the orchestrator adds the same note when other families were diagnosed; "supported" list now comes from `PARSERS` |
| Medium | UTF-16 input (Windows/PowerShell logs) came back as no trace | `_decode()` honours UTF-8/16/32 BOMs and sniffs BOM-less UTF-16 LE/BE |
| Medium | 3 `mypy --strict` errors | Typed `_Key` alias in `aggregator.py`; `dict[str, Any]` in `render.py` |
| Low | Text output printed multi-MB messages in full | Clipped to 500 chars with "… [N more chars]"; JSON keeps the full message |
| Low | JSON unbounded (5,001 hypotheses = 6.8 MB) | `--limit` (default 50) with a "showing top N of M" note |
| Low | Slow user regexes like `(A+)+B` could hang a diagnosis | Loader rejects nested quantifiers; matcher only regex-searches the first 4,096 message chars (Task 8 timeouts remain the second guard) |
| Low | Interactive `diagnose` with no file waited on the keyboard | A TTY on stdin gives a usage hint, exit 2 |
| Low | 30 ruff issues | All fixed (`noqa: B008` on the idiomatic typer default) |

### New tests (19)

- `tests/test_cli.py`: unreadable file, directory, missing `--patterns` dir, unsupported family, 5 encodings, `--limit`, TTY stdin
- `tests/test_render.py`: message clipping, service/evidence/others/notes sections, empty diagnosis
- `tests/test_orchestrator.py`: unsupported-family note
- `tests/patterns/test_loader.py`: 4 nested-quantifier regexes rejected

### Test results after fixes

```
95 passed in 3.26s  (coverage 98%, mypy --strict clean, ruff clean)
48 MB log end-to-end: 0.29 s
```

---
