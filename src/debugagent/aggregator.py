from collections.abc import Iterable

from debugagent.models import Hypothesis

_Key = tuple[str, str | None, int | None, str | None]


def _key(h: Hypothesis) -> _Key:
    loc = h.locations[0] if h.locations else None
    return (h.pattern_id, loc.file if loc else None, loc.line if loc else None, h.service)


def aggregate(hyps: Iterable[Hypothesis]) -> tuple[Hypothesis, ...]:
    best: dict[_Key, Hypothesis] = {}
    for h in hyps:
        k = _key(h)
        if k not in best or h.confidence > best[k].confidence:
            best[k] = h
    return tuple(sorted(best.values(), key=lambda h: (-h.confidence, h.pattern_id)))
