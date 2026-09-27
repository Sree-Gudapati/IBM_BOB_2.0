from collections.abc import Iterable
from dataclasses import replace
from typing import TYPE_CHECKING

from debugagent.models import Hypothesis

if TYPE_CHECKING:
    from debugagent.scanner.models import CodebaseMap

_Key = tuple[str, str | None, int | None, str | None]

SYMPTOM_FACTOR = 0.6
NO_MAP_SYMPTOM_FACTOR = 0.8
SOURCE_BOOST = 0.05
CONFIDENCE_CAP = 0.99
HISTORY_MIN_COUNT = 3
HISTORY_BOOST = 0.05
_NOT_SOURCE = ("dependency", "unknown")


def _key(h: Hypothesis) -> _Key:
    loc = h.locations[0] if h.locations else None
    return (h.pattern_id, loc.file if loc else None, loc.line if loc else None, h.service)


def _attribute(h: Hypothesis, cb: "CodebaseMap") -> Hypothesis:
    if h.service:
        return h
    for f in h.locations:
        s = cb.service_for_frame(f)
        if s:
            return replace(h, service=s)
    return h


def _is_symptom_of(a: Hypothesis, b: Hypothesis, cb: "CodebaseMap") -> bool:
    return (
        a.category == "dependency"
        and b.category not in _NOT_SOURCE
        and bool(a.service)
        and bool(b.service)
        and a.service != b.service
        and cb.calls(a.service, b.service)
    )


def _with_map(hyps: list[Hypothesis], cb: "CodebaseMap") -> list[Hypothesis]:
    out = []
    for h in hyps:
        sources = sorted({b.service for b in hyps if _is_symptom_of(h, b, cb)})
        callers = sorted({a.service for a in hyps if _is_symptom_of(a, h, cb)})
        if sources:
            h = replace(
                h,
                confidence=round(h.confidence * SYMPTOM_FACTOR, 4),
                evidence=h.evidence + (
                    f"Likely a symptom: {h.service} calls {', '.join(sources)}, "
                    f"which failed at the same time",
                ),
            )
        if callers:
            h = replace(
                h,
                confidence=min(CONFIDENCE_CAP, round(h.confidence + SOURCE_BOOST, 4)),
                evidence=h.evidence + (
                    f"Callers {', '.join(callers)} failed with timeout/connection errors into "
                    f"{h.service}: this is the likely origin",
                ),
            )
        out.append(h)
    return out


def _without_map(hyps: list[Hypothesis]) -> list[Hypothesis]:
    if not any(h.category not in _NOT_SOURCE for h in hyps):
        return hyps
    return [
        replace(
            h,
            confidence=round(h.confidence * NO_MAP_SYMPTOM_FACTOR, 4),
            evidence=h.evidence + (
                "Timeout/connection errors are usually a symptom; another error in this input is a "
                "more likely origin (pass --codebase for service-aware ranking)",
            ),
        )
        if h.category == "dependency"
        else h
        for h in hyps
    ]


def _history_boost(h: Hypothesis, cb: "CodebaseMap") -> Hypothesis:
    counts = cb.history.get(h.service or "", {})
    hits = sorted(
        ((counts[t], t) for t in h.tags if counts.get(t, 0) >= HISTORY_MIN_COUNT),
        reverse=True,
    )
    if not hits:
        return h
    n, tag = hits[0]
    return replace(
        h,
        confidence=min(CONFIDENCE_CAP, round(h.confidence + HISTORY_BOOST, 4)),
        evidence=h.evidence + (
            f"{h.service} has {n} past fix commits tagged '{tag}' — a recurring weakness",
        ),
    )


def aggregate(
    hyps: Iterable[Hypothesis],
    codebase: "CodebaseMap | None" = None,
) -> tuple[Hypothesis, ...]:
    hs = list(hyps)
    if codebase is not None:
        hs = _with_map(
            [_history_boost(_attribute(h, codebase), codebase) for h in hs],
            codebase,
        )
    else:
        hs = _without_map(hs)
    best: dict[_Key, Hypothesis] = {}
    for h in hs:
        k = _key(h)
        if k not in best or h.confidence > best[k].confidence:
            best[k] = h
    return tuple(sorted(best.values(), key=lambda h: (-h.confidence, h.pattern_id)))
