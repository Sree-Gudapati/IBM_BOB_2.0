import re
from debugagent.models import Family

MAX_INPUT_CHARS = 5_000_000

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_PREFIX = re.compile(
    r"^(?:\[?\d{4}-\d{2}-\d{2}[T ][\d:.,]+(?:Z|[+-]\d{2}:?\d{2})?\]?\s+)?"
    r"(?:\[?(?:TRACE|DEBUG|INFO|WARN|WARNING|ERROR|SEVERE|FATAL|CRITICAL)\]?:?\s+)?"
    r"(?:\[[\w.@:/-]+\]\s+)?"
)

_SIGNATURES: dict[Family, re.Pattern[str]] = {
    Family.PYTHON: re.compile(r'^\s*Traceback \(most recent call last\):|^\s*File "[^"]+\.py", line \d+', re.M),
    Family.JVM: re.compile(r"^\s*at [\w$.<>/]+\([\w$]+\.(?:java|kt|scala):\d+\)|^Exception in thread \"", re.M),
    Family.NODE: re.compile(r"^\s*at (?:.+ \()?(?:file://)?[^\s()]+\.(?:js|mjs|cjs|ts|tsx|jsx):\d+:\d+\)?\s*$", re.M),
    Family.GO: re.compile(r"^panic: |^fatal error: |^goroutine \d+ \[", re.M),
    Family.RUST: re.compile(r"^thread '[^']*' panicked at ", re.M),
}


def normalize(text: str) -> str:
    if len(text) > MAX_INPUT_CHARS:
        text = text[-MAX_INPUT_CHARS:]
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(_PREFIX.sub("", _ANSI.sub("", ln), count=1) for ln in text.split("\n"))


def detect_families(text: str) -> frozenset[Family]:
    return frozenset(f for f, rx in _SIGNATURES.items() if rx.search(text))
