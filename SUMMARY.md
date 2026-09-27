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
