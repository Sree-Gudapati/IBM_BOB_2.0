import re

from debugagent.models import Family

MAX_INPUT_CHARS = 5_000_000

# Strip ANSI CSI sequences (colours, cursor moves) and OSC sequences (title/link).
_ANSI = re.compile(r"\x1b(?:\[[0-9;]*[A-Za-z]|\][^\x07\x1b]*(?:\x07|\x1b\\))")

# Match structured-log prefixes at the START of a line.  Each component
# consumes exactly ONE separator space, so any further indentation belongs to
# the payload and is preserved (Python "  File …", Java "\tat …").
#
# Accepted components (all optional, in order):
#   timestamp – ISO-8601 date+time, optional brackets/timezone
#   level     – UPPERCASE level with optional brackets/colon, or a lowercase
#               level WITHOUT a colon.  Mixed case ("Error:", "Warning:") is
#               never a level: it is the payload's own error type (JS/Node).
#   service   – [tag] or [tag:detail]
_LEVELS = "TRACE|DEBUG|INFO|WARN|WARNING|ERROR|SEVERE|FATAL|CRITICAL"
_PREFIX = re.compile(
    r"^(?:\[?\d{4}-\d{2}-\d{2}[T ][\d:.,]+(?:Z|[+-]\d{2}:?\d{2})?\]? )?"
    rf"(?:\[?(?:{_LEVELS})\]?:? |\[?(?:{_LEVELS.lower()})\]? )?"
    r"(?:\[[\w.@:/-]+\] )?"
)

_SIGNATURES: dict[Family, re.Pattern[str]] = {
    Family.PYTHON: re.compile(
        r'^\s*Traceback \(most recent call last\):|^\s*File "[^"]+\.py", line \d+',
        re.MULTILINE,
    ),
    Family.JVM: re.compile(
        r'^\s*at [\w$.<>/]+\([\w$]+\.(?:java|kt|scala):\d+\)|^Exception in thread "',
        re.MULTILINE,
    ),
    # Matches extension-bearing paths (.js/.ts/etc.), Node.js internal frames
    # (node:net:1555:16), V8 fatal heap OOM, and UnhandledPromiseRejection.
    Family.NODE: re.compile(
        r"^\s*at (?:.+ \()?(?:file://)?[^\s()]+\.(?:js|mjs|cjs|ts|tsx|jsx):\d+:\d+\)?\s*(?:\{)?\s*$"
        r"|node:[\w/.-]+:\d+:\d+"
        r"|^FATAL ERROR: .*heap out of memory"
        r"|^\[UnhandledPromiseRejection: ",
        re.MULTILINE,
    ),
    Family.GO: re.compile(r"^panic: |^fatal error: |^goroutine \d+ \[", re.MULTILINE),
    Family.RUST: re.compile(r"^thread '[^']*' panicked at ", re.MULTILINE),
}


def normalize(text: str) -> str:
    if len(text) > MAX_INPUT_CHARS:
        text = text[-MAX_INPUT_CHARS:]
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(_PREFIX.sub("", _ANSI.sub("", ln)) for ln in text.split("\n"))


def detect_families(text: str) -> frozenset[Family]:
    return frozenset(f for f, rx in _SIGNATURES.items() if rx.search(text))
