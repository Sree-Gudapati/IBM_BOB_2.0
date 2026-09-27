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
