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


def evaluate(
    corpus_dir: Path,
    subagents,
    codebase: CodebaseMap | None = None,
) -> EvalReport:
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
        results.append(CaseResult(
            c["file"], c["expected"], got, want_svc, svc,
            top.confidence if top else 0.0, latency, correct,
        ))
    known = [r for r in results if not r.expected.endswith(".unknown")]
    per_family: dict[str, list[bool]] = {}
    for r in results:
        per_family.setdefault(r.expected.split(".", 1)[0], []).append(r.correct)
    return EvalReport(
        results=results,
        accuracy=sum(r.correct for r in results) / len(results) if results else 0.0,
        coverage=(
            sum(1 for r in known if r.got and not r.got.endswith(".unknown")) / len(known)
            if known else 1.0
        ),
        p95_latency_s=_p95([r.latency_s for r in results]),
        max_subagent_s=max_sub,
        per_family={k: sum(v) / len(v) for k, v in sorted(per_family.items())},
    )
