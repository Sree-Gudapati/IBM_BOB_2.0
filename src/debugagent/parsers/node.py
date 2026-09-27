import re
from dataclasses import dataclass, field

from debugagent.models import Family, Frame, ParsedTrace

# Error types: built-ins and custom classes ending in Error/Exception (TypeError, AxiosError,
# FetchError, ValidationException…) plus Node's frameless UnhandledPromiseRejection.
_TYPE = r"(?P<type>(?:[A-Z][\w$]*)?(?:Error|Exception)|UnhandledPromiseRejection)"
# "[ERR_X]" codes, and DOMException's "[TimeoutError]"/"[AbortError]" names.
_CODE = r"(?: \[(?P<code>[A-Za-z0-9_]+)\])?"
_HEADER = re.compile(rf"^(?:Uncaught\s+)?\[?{_TYPE}{_CODE}:\s?(?P<msg>.*?)\]?\s*(?:\{{)?\s*$")
_CAUSE = re.compile(rf"^\s*\[cause\]:\s*{_TYPE}{_CODE}:\s?(?P<msg>.*?)\s*(?:\{{)?\s*$")
# "at fn (file:L:C)" — file may contain spaces (inside parens) or a Windows drive letter;
# "at file:L:C" — anonymous, no parens, no spaces.
_FRAME = re.compile(
    r"^\s*at (?:async )?(?:"
    r"(?P<func>.+?) \((?:file://)?(?P<pfile>[^()]+?):(?P<pline>\d+):(?P<pcol>\d+)\)"
    r"|(?:file://)?(?P<file>[^\s()]+?):(?P<line>\d+):(?P<col>\d+)"
    r")\s*(?:\{)?\s*$"
)
# Frame-shaped lines without a location: "at async Promise.all (index 0)", "at <anonymous>",
# "at new Promise (<anonymous>)". Part of the stack; skipped without ending the trace.
_OTHER_FRAME = re.compile(r"^\s*at \S")
_FATAL = re.compile(r"^FATAL ERROR: (?P<msg>.*heap out of memory.*)$")
# Inspector output after a frame block: "{", "}", "errno: -111,", "code: 'X'", "Require stack:".
_IGNORABLE = re.compile(r"^\s*(?:[{}\]]|\w+: .*,?|- .*|Require stack:)\s*$")
_ERRORS_BLOCK = re.compile(r"^(?P<indent>\s*)\[errors\]: \[\s*$")
_FRAMELESS_OK = ("UnhandledPromiseRejection",)


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _msg(m: re.Match[str]) -> str:
    msg = (m["msg"] or "").strip()
    return f"[{m['code']}] {msg}" if m["code"] else msg


@dataclass
class _Seg:
    etype: str
    msg: str
    frames: list[Frame] = field(default_factory=list)


def _fold(segs: list[_Seg]) -> ParsedTrace:
    cause: ParsedTrace | None = None
    for s in reversed(segs):
        cause = ParsedTrace(Family.NODE, s.etype, s.msg, tuple(s.frames), cause=cause)
    assert cause is not None
    return cause


def parse(text: str) -> list[ParsedTrace]:
    results: list[ParsedTrace] = []
    segs: list[_Seg] = []
    errors_at: int | None = None       # indent of an open AggregateError "[errors]: [" block

    def flush() -> None:
        nonlocal errors_at
        # Node prints unhandled rejections with no frames, so keep them anyway.
        if segs and (segs[0].frames or segs[0].etype in _FRAMELESS_OK):
            results.append(_fold(segs))
        segs.clear()
        errors_at = None

    for line in text.split("\n"):
        if errors_at is not None:
            if line.strip() == "]" and _indent(line) == errors_at:
                errors_at = None
            continue                    # sub-errors of an AggregateError: not part of the chain
        em = _ERRORS_BLOCK.match(line)
        if em and segs:
            errors_at = len(em["indent"])
            continue
        fm = _FRAME.match(line)
        if fm:
            if segs:
                file = fm["pfile"] or fm["file"]
                ln = fm["pline"] or fm["line"]
                segs[-1].frames.append(Frame(file, int(ln), (fm["func"] or "<anonymous>").strip()))
            continue
        if segs and _OTHER_FRAME.match(line):
            continue
        cm = _CAUSE.match(line)
        if cm and segs:
            segs.append(_Seg(cm["type"], _msg(cm)))
            continue
        fatal = _FATAL.match(line.strip())
        if fatal:
            flush()
            results.append(ParsedTrace(Family.NODE, "FatalError", fatal["msg"].strip(), ()))
            continue
        hm = _HEADER.match(line.strip())
        if hm:
            flush()
            segs.append(_Seg(hm["type"], _msg(hm)))
            continue
        if not line.strip() or (segs and _IGNORABLE.match(line)):
            continue
        flush()
    flush()
    return results
