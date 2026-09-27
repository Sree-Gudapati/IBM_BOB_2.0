import re
from debugagent.models import Family, Frame, ParsedTrace

_HEADER = re.compile(r"^\s*Traceback \(most recent call last\):\s*$")
_FRAME = re.compile(r'^\s*File "(?P<file>[^"]+)", line (?P<line>\d+), in (?P<func>.+?)\s*$')
_CHAIN = re.compile(r"^\s*(The above exception was the direct cause|During handling of the above exception)")
_MARKER = re.compile(r"^\s*[~^]+\s*$")
_EXC = re.compile(r"^(?P<type>(?:[A-Za-z_]\w*\.)*[A-Z]\w*)(?::\s?(?P<msg>.*))?$")
_EXC_SUFFIXES = ("Error", "Exception", "Warning", "Interrupt", "Exit", "StopIteration")


def _exception_line(line: str) -> re.Match[str] | None:
    m = _EXC.match(line.strip())
    if not m:
        return None
    if m.group("msg") is None and not m.group("type").endswith(_EXC_SUFFIXES):
        return None
    return m


def parse(text: str) -> list[ParsedTrace]:
    results: list[ParsedTrace] = []
    frames: list[Frame] | None = None
    chained = False
    for line in text.split("\n"):
        if _CHAIN.match(line):
            chained = True
            continue
        if _HEADER.match(line):
            frames = []
            continue
        if frames is None:
            continue
        fm = _FRAME.match(line)
        if fm:
            frames.append(Frame(fm["file"], int(fm["line"]), fm["func"].strip()))
            continue
        if not line.strip() or _MARKER.match(line) or not frames:
            continue
        em = _exception_line(line)
        if em is None:
            continue  # a source line
        cause = results.pop() if chained and results else None
        results.append(ParsedTrace(
            Family.PYTHON, em["type"], (em["msg"] or "").strip(),
            tuple(reversed(frames)), cause=cause,
        ))
        frames, chained = None, False
    return results
