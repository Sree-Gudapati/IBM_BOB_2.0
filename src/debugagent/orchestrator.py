import threading
import time
from typing import TYPE_CHECKING

from debugagent.aggregator import aggregate
from debugagent.detect import MAX_INPUT_CHARS, detect_families, normalize
from debugagent.models import Diagnosis, Family, Hypothesis
from debugagent.subagent import LanguageSubagent

if TYPE_CHECKING:
    from debugagent.scanner.models import CodebaseMap

SUBAGENT_TIMEOUT_S = 2.0


def _run_parallel(
    fams: list[Family],
    subagents: dict[Family, LanguageSubagent],
    text: str,
    timeout_s: float,
) -> tuple[dict[Family, tuple], list[Family]]:
    results: dict[Family, tuple] = {}

    def worker(fam: Family) -> None:
        t0 = time.perf_counter()
        try:
            results[fam] = ("ok", subagents[fam].run(text), time.perf_counter() - t0)
        except Exception as e:  # noqa: BLE001 — isolate any subagent failure
            results[fam] = ("err", e, time.perf_counter() - t0)

    threads = {
        f: threading.Thread(target=worker, args=(f,), daemon=True, name=f"subagent-{f.value}")
        for f in fams
    }
    for t in threads.values():
        t.start()
    deadline = time.monotonic() + timeout_s
    for t in threads.values():
        t.join(max(0.0, deadline - time.monotonic()))
    return results, [f for f, t in threads.items() if t.is_alive()]


def diagnose(
    text: str,
    subagents: dict[Family, LanguageSubagent],
    timeout_s: float = SUBAGENT_TIMEOUT_S,
    codebase: "CodebaseMap | None" = None,
) -> Diagnosis:
    notes: list[str] = []
    if len(text) > MAX_INPUT_CHARS:
        notes.append(f"input truncated to its last {MAX_INPUT_CHARS:,} characters")
    clean = normalize(text)
    families = detect_families(clean)
    fams = sorted((f for f in families if f in subagents), key=lambda f: f.value)
    unregistered = sorted(f.value for f in families if f not in subagents)
    for fv in unregistered:
        notes.append(f"detected {fv} trace(s) but no {fv} analyzer is available yet")
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
    return Diagnosis(aggregate(hyps, codebase), families, tuple(notes), tuple(timings))
