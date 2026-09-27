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
**Fix:** Each prefix component now ends with a single literal space (` `), and the whole pattern ends with `(?=\S)` so the regex only fires when non-space payload follows. Payload indentation is never touched.
**Also fixed in same change:** `_ANSI` extended to strip OSC sequences (terminal title/link codes); level matching made case-insensitive (`re.IGNORECASE`).
**Pinning test:** `test_normalize_preserves_indentation_after_prefix_strip`

### Fix 2 — Node ECONNREFUSED traces not detected (High)

**Root cause:** The `NODE` signature only matched frames ending in `.js`/`.ts`/etc. Node.js internal frames (`node:net:1555:16`, `node:internal/stream_base_commons:183:27`) have no file extension and were silently skipped, causing the whole trace to go undetected. This would have broken Review Focus #4 (mixed Node+Java cross-service diagnosis).
**Fix:** `NODE` signature now includes an alternative branch: `node:[\w/.-]+:\d+:\d+`.
**Pinning tests:** `test_detects_node_internal_frames`, `test_detects_node_internal_plus_java`

### Test results after fixes

```
10 passed in 0.02s
```

### Deferred items (to be fixed in their owning tasks)

| # | Severity | Item | Owning task |
|---|---|---|---|
| 3 | Medium | JVM `(Native Method)` / `(Unknown Source)` frames not detected | Task 4 |
| 4 | Medium | `short_error_type` doesn't split on `::` for Rust | Task 7 |
| 5a | Low | Message starting with a level word loses that word | Task 1 cleanup (acceptable) |
| 5b | Low | `[main] INFO x` not stripped (service tag before level) | Future |
| 5c | Low | Lowercase levels not stripped | Fixed in Fix 1 above (`re.IGNORECASE`) |
| 5d | Low | OSC ANSI sequences survive | Fixed in Fix 1 above |
| 5e | Low | `File "<string>"` / `File "<stdin>"` don't match Python sig alone | Task 2 |

---
