import re
from dataclasses import dataclass, field

from debugagent.models import Family, Frame, ParsedTrace

# Exception type: a dotted FQN (any Capitalised last segment, e.g. com.acme.PaymentDeclined,
# com.a.Outer$InnerException) or an undotted name with an exception-like suffix (MyException).
_TYPE = (
    r"(?:[a-z_$][\w$]*\.)+[A-Z][\w$]*"
    r"|[A-Z][\w$]*(?:Exception|Error|Throwable)"
)
_HEADER = re.compile(
    r'^(?P<caused>Caused by:\s*)?(?P<thread>Exception in thread "[^"]*"\s+)?'
    rf"(?P<type>{_TYPE})(?::\s?(?P<msg>.*))?\s*$"
)
_SUFFIXED = re.compile(r"(?:Exception|Error|Throwable)$")
# "at" frames. Optional classloader/module prefixes: "java.base/", "java.base@17.0.2/", "app//".
# Hidden-class lambdas carry a "/0x…" suffix on the class name.
_FRAME = re.compile(
    r"^\s*at (?:[\w.-]+(?:@[\w.-]+)?/{1,2}(?!0x))*(?P<qual>[\w$.<>]+?)(?:/0x[0-9a-fA-F]+)?"
    r"\.(?P<method>[\w$<>-]+)\((?P<file>[^:()]+)(?::(?P<line>\d+))?\)"
)
_MORE = re.compile(r"^\s*\.\.\. \d+ (?:more|common frames omitted)")
_SUPPRESSED = re.compile(r"^(?P<indent>\s*)Suppressed:")
MAX_MESSAGE_CONTINUATION = 10


def _indent(line: str) -> int:
    expanded = line.expandtabs(4)
    return len(expanded) - len(expanded.lstrip())


@dataclass
class _Seg:
    etype: str
    msg: str
    strong: bool                         # "Exception in thread", or dotted …Exception/Error/Throwable
    frames: list[Frame] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)   # possible message continuation lines


def _fold(segments: list[_Seg]) -> ParsedTrace:
    assert segments
    cause: ParsedTrace | None = None
    for s in reversed(segments):
        cause = ParsedTrace(Family.JVM, s.etype, s.msg, tuple(s.frames), cause=cause)
    assert cause is not None
    return cause


def parse(text: str) -> list[ParsedTrace]:
    results: list[ParsedTrace] = []
    segments: list[_Seg] = []
    suppressed_at: int | None = None     # indent of an active "Suppressed:" block

    def flush() -> None:
        nonlocal suppressed_at
        # Frameless traces are kept only on a strong signal: OOM often has no stack at all.
        if segments and (any(s.frames for s in segments) or segments[0].strong):
            results.append(_fold(segments))
        segments.clear()
        suppressed_at = None

    for line in text.split("\n"):
        if suppressed_at is not None:
            if not line.strip() or _indent(line) > suppressed_at:
                continue                 # inside the suppressed block (incl. its own Caused by)
            suppressed_at = None         # dedent: back to the main trace
        sm = _SUPPRESSED.match(line)
        if sm and segments:
            suppressed_at = _indent(line)
            continue
        fm = _FRAME.match(line)
        if fm:
            if segments:
                seg = segments[-1]
                if seg.pending:          # lines between header and first frame were message
                    seg.msg = "\n".join([seg.msg, *seg.pending]).strip()
                    seg.pending.clear()
                cls = fm["qual"]
                seg.frames.append(Frame(
                    file=fm["file"], line=int(fm["line"]) if fm["line"] else None,
                    function=f"{cls.rsplit('.', 1)[-1]}.{fm['method']}", module=cls,
                ))
            continue
        if _MORE.match(line):
            continue
        hm = _HEADER.match(line.strip())
        if hm:
            etype = hm["type"]
            seg = _Seg(etype, (hm["msg"] or "").strip(),
                       strong=bool(hm["thread"] or ("." in etype and _SUFFIXED.search(etype))))
            if not (hm["caused"] and segments):
                flush()
            elif segments[-1].pending:
                segments[-1].pending.clear()
            segments.append(seg)
            continue
        if not line.strip():
            continue
        # Other non-empty line: message continuation if we're still before the first frame,
        # otherwise the end of this trace.
        if segments and not segments[-1].frames and len(segments[-1].pending) < MAX_MESSAGE_CONTINUATION:
            segments[-1].pending.append(line.strip())
            continue
        flush()
    flush()
    return results
