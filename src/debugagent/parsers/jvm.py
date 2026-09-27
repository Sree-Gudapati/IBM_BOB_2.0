import re
from debugagent.models import Family, Frame, ParsedTrace

_HEADER = re.compile(
    r'^(?P<caused>Caused by:\s*)?(?:Exception in thread "[^"]*"\s+)?'
    r"(?P<type>(?:[a-z_$][\w$]*\.)+[A-Z][\w$]*(?:Exception|Error|Throwable|Failure)[\w$]*)"
    r"(?::\s?(?P<msg>.*))?\s*$"
)
_FRAME = re.compile(
    r"^\s*at (?:[\w.-]+/)?(?P<qual>[\w$.<>]+)\.(?P<method>[\w$<>-]+)"
    r"\((?P<file>[^:()]+)(?::(?P<line>\d+))?\)"
)
_MORE = re.compile(r"^\s*\.\.\. \d+ (?:more|common frames omitted)")
_SUPPRESSED = re.compile(r"^\s*Suppressed:")


def _fold(segments: list[tuple[str, str, list[Frame]]]) -> ParsedTrace:
    cause = None
    for etype, msg, frames in reversed(segments):
        cause = ParsedTrace(Family.JVM, etype, msg, tuple(frames), cause=cause)
    return cause


def parse(text: str) -> list[ParsedTrace]:
    results: list[ParsedTrace] = []
    segments: list[tuple[str, str, list[Frame]]] = []
    in_suppressed = False

    def flush() -> None:
        if segments and any(fr for _, _, fr in segments):
            results.append(_fold(segments))
        segments.clear()

    for line in text.split("\n"):
        if _SUPPRESSED.match(line):
            in_suppressed = True
            continue
        fm = _FRAME.match(line)
        if fm:
            if segments and not in_suppressed:
                cls = fm["qual"]
                segments[-1][2].append(Frame(
                    file=fm["file"], line=int(fm["line"]) if fm["line"] else None,
                    function=f"{cls.rsplit('.', 1)[-1]}.{fm['method']}", module=cls,
                ))
            continue
        if _MORE.match(line):
            continue
        hm = _HEADER.match(line.strip())
        if hm:
            if hm["caused"] and segments:
                in_suppressed = False
                segments.append((hm["type"], (hm["msg"] or "").strip(), []))
            else:
                flush()
                in_suppressed = False
                segments.append((hm["type"], (hm["msg"] or "").strip(), []))
            continue
        if line.strip():
            flush()          # any other non-empty line ends the current trace
    flush()
    return results
