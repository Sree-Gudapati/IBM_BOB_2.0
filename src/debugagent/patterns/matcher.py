import re
from collections.abc import Sequence

from debugagent.models import Family, Frame, Hypothesis, ParsedTrace
from debugagent.patterns.loader import Pattern
from debugagent.patterns.repro import render_repro

GENERIC_DISCOUNT = 0.85
UNKNOWN_CONFIDENCE = 0.1
# Only the head of a message is regex-matched: bounds cost on multi-MB messages.
MATCH_MESSAGE_LIMIT = 4096

_LIB_PATH = re.compile(
    r"site-packages/|dist-packages/|/lib/python\d[\d.]*/|<frozen |node_modules/|^node:|^internal/"
    r"|/usr/local/go/src/|/go/pkg/mod/|^runtime/|\.cargo/registry/|^/rustc/|/library/(?:std|core|alloc)/"
)
_GO_LIB_FUNCS = ("runtime.", "internal/", "sync.", "testing.")
_JVM_LIB = re.compile(
    r"^(?:java|javax|jdk|sun|com\.sun|kotlin|kotlinx|scala"
    r"|org\.springframework|io\.netty|org\.apache|com\.zaxxer"
    r"|io\.quarkus|reactor)\."
)


def is_library_frame(frame: Frame, family: Family) -> bool:
    if family is Family.JVM:
        return bool(frame.module and _JVM_LIB.match(frame.module))
    if family is Family.GO and (frame.function == "panic" or frame.function.startswith(_GO_LIB_FUNCS)):
        return True     # runtime frames, wherever GOROOT lives (Homebrew, /usr/lib/go, …)
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
        if p.message_regex is not None and not p.message_regex.search(root.message[:MATCH_MESSAGE_LIMIT]):
            continue
        key = (1 if p.message_regex is not None else 0, p.base_confidence, p)
        if best is None or key[:2] > best[:2]:
            best = key
    if best is None:
        return Hypothesis(
            family=root.family, pattern_id=f"{root.family.value}.unknown", category="unknown",
            root_cause=(
                f"Unrecognized {root.error_type}: {root.message[:200]}. No pattern matched; "
                f"add one under patterns/data/{root.family.value}/."
            ),
            confidence=UNKNOWN_CONFIDENCE, error_type=root.error_type, message=root.message,
            fixes=(), locations=locs, repro_test="",
        )
    specific, _, p = best
    conf = p.base_confidence if specific else round(p.base_confidence * GENERIC_DISCOUNT, 4)
    return Hypothesis(
        family=root.family, pattern_id=p.id, category=p.category, root_cause=p.root_cause,
        confidence=conf, error_type=root.error_type, message=root.message, fixes=p.fixes,
        locations=locs,
        repro_test=render_repro(p.repro_template, p.id, root, locs[0] if locs else None),
        tags=p.tags,
    )
