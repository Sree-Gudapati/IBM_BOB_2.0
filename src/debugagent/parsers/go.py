import re
from debugagent.models import Family, Frame, ParsedTrace

_PANIC = re.compile(r"^panic: (?P<body>.*?)(?: \[recovered\])?\s*$")
_FATAL = re.compile(r"^fatal error: (?P<body>.*?)!?\s*$")
_GOROUTINE = re.compile(r"^goroutine \d+ \[[^\]]*\]:?\s*$")
_FILE = re.compile(r"^\s*(?P<file>\S+\.go):(?P<line>\d+)(?:\s+\+0x[0-9a-f]+)?\s*$")
_CREATED = re.compile(r"^\s*created by ")


def _func_name(s: str) -> str:
    i = s.rfind("(")
    return s[:i] if i > 0 and s.endswith(")") else s


def _strip_hash(name: str) -> str:
    """Strip ::h<hex> mangling suffix from function names."""
    return re.sub(r"::h[0-9a-f]+$", "", name)


def _classify(kind: str, body: str) -> tuple[str, str]:
    if kind == "fatal":
        return "fatal error", body
    if body.startswith("runtime error: "):
        return "runtime error", body[len("runtime error: "):]
    return "panic", body


def parse(text: str) -> list[ParsedTrace]:
    results: list[ParsedTrace] = []
    cur: dict | None = None  # {"etype", "msg", "frames", "state", "pending"}

    def flush() -> None:
        nonlocal cur
        if cur and cur["frames"]:
            results.append(ParsedTrace(Family.GO, cur["etype"], cur["msg"], tuple(cur["frames"])))
        cur = None

    for line in text.split("\n"):
        at_col0 = not line[:1].isspace()
        pm = _PANIC.match(line) if at_col0 else None
        fm = _FATAL.match(line) if at_col0 else None
        if pm or fm:
            if cur and cur["state"] == "await":
                # nested panic before the dump (recovered): keep the first (original)
                continue
            flush()
            etype, msg = _classify("fatal" if fm else "panic", (fm or pm)["body"])
            cur = {"etype": etype, "msg": msg, "frames": [], "state": "await", "pending": None}
            continue
        if cur is None:
            continue
        if _GOROUTINE.match(line.strip()):
            if cur["state"] == "await":
                cur["state"] = "frames"
            else:
                flush()  # second goroutine block: stop
            continue
        if cur["state"] != "frames":
            continue
        if not line.strip():
            flush()
            continue
        fl = _FILE.match(line)
        if fl:
            if cur["pending"]:
                cur["frames"].append(Frame(fl["file"], int(fl["line"]), cur["pending"]))
            cur["pending"] = None
            continue
        if _CREATED.match(line):
            cur["pending"] = None
        else:
            cur["pending"] = _strip_hash(_func_name(line.strip()))
    flush()
    return results
