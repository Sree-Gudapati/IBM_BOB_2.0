import re
from dataclasses import replace

from debugagent.models import Family, Frame, ParsedTrace

# "Traceback …" and the 3.11+ "+ Exception Group Traceback …" header.
_HEADER = re.compile(r"^\s*(?:\+ )?(?:Exception Group )?Traceback \(most recent call last\):\s*$")
# ", in <func>" is optional: SyntaxError location lines omit it.
_FRAME = re.compile(r'^\s*File "(?P<file>[^"]+)", line (?P<line>\d+)(?:, in (?P<func>.+?))?\s*$')
_CHAIN = re.compile(r"^\s*(The above exception was the direct cause|During handling of the above exception)")
_MARKER = re.compile(r"^\s*[~^]+\s*$")
# Exception-group box drawing: "  | " gutters and "+-+---- 1 ----" / "+----" separators.
_GUTTER = re.compile(r"^\s*\| ?")
_GROUP_SEP = re.compile(r"^\s*\+[-+]*(?:\s*\d+\s*-*|\s*\.\.\.[^+]*-*)?\s*$")
# Dotted names may end lowercase (socket.timeout); undotted names must be Capitalised.
_EXC = re.compile(
    r"^(?P<type>(?:[A-Za-z_]\w*\.)+[A-Za-z_]\w*|[A-Z]\w*)(?::\s?(?P<msg>.*))?$"
)
_EXC_SUFFIXES = ("Error", "Exception", "Warning", "Interrupt", "Exit", "StopIteration", "Group")
_GROUP_TYPES = ("ExceptionGroup", "BaseExceptionGroup")
_NO_FUNC = "<unknown>"


def _exception_line(line: str) -> re.Match[str] | None:
    # CPython prints the exception line unindented; indented lines are source code
    # (e.g. "    Foo: int = 3") and must never be taken as the exception.
    if line[:1].isspace():
        return None
    m = _EXC.match(line.rstrip())
    if not m:
        return None
    etype = m.group("type")
    if m.group("msg") is None and "." not in etype and not etype.endswith(_EXC_SUFFIXES):
        return None
    return m


def parse(text: str) -> list[ParsedTrace]:
    results: list[ParsedTrace] = []
    frames: list[Frame] | None = None
    chained = False
    group_idx: int | None = None   # index in results of an open ExceptionGroup
    for raw in text.split("\n"):
        in_group = bool(_GUTTER.match(raw)) or raw.lstrip().startswith("+")
        if _GROUP_SEP.match(raw):
            continue
        line = _GUTTER.sub("", raw, count=1)
        if _CHAIN.match(line):
            chained = True
            continue
        if _HEADER.match(line):
            frames = []
            continue
        fm = _FRAME.match(line)
        if fm:
            if frames is None:
                frames = []          # header-less SyntaxError output starts at a File line
            frames.append(Frame(fm["file"], int(fm["line"]), (fm["func"] or _NO_FUNC).strip()))
            continue
        if frames is None:
            continue
        if not line.strip() or _MARKER.match(line):
            continue
        em = _exception_line(line)
        if em is None:
            continue  # a source line
        cause = results.pop() if chained and results and group_idx is None else None
        trace = ParsedTrace(
            Family.PYTHON, em["type"], (em["msg"] or "").strip(),
            tuple(reversed(frames)), cause=cause,
        )
        if group_idx is not None and in_group:
            # First sub-exception of a group becomes the group's cause, so .root()
            # lands on the real failure instead of the ExceptionGroup wrapper.
            results[group_idx] = replace(results[group_idx], cause=trace)
            group_idx = None
        else:
            results.append(trace)
            if trace.short_error_type in _GROUP_TYPES:
                group_idx = len(results) - 1
        frames, chained = None, False
    return results
