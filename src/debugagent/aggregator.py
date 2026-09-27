from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from debugagent.models import Hypothesis

if TYPE_CHECKING:
    from debugagent.scanner.models import CodebaseMap

_Key = tuple[str, str | None, int | None, str | None]


def _key(h: Hypothesis) -> _Key:
    loc = h.locations[0] if h.locations else None
    return (h.pattern_id, loc.file if loc else None, loc.line if loc else None, h.service)


def aggregate(hyps: Iterable[Hypothesis], codebase: "CodebaseMap | None" = None) -> tuple[Hypothesis, ...]:
    best: dict[_Key, Hypothesis] = {}
    for h in hyps:
        k = _key(h)
        if k not in best or h.confidence > best[k].confidence:
            best[k] = h
    return tuple(sorted(best.values(), key=lambda h: (-h.confidence, h.pattern_id)))
