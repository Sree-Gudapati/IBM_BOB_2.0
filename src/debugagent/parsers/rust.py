import re
from debugagent.models import Family, Frame, ParsedTrace

_NEW = re.compile(r"^thread '[^']*' panicked at (?P<file>[^\s']+?):(?P<line>\d+):\d+:\s*$")
_OLD = re.compile(r"^thread '[^']*' panicked at '(?P<msg>.*)', (?P<file>\S+?):(?P<line>\d+):\d+\s*$")
_BT_START = re.compile(r"^\s*stack backtrace:\s*$")
_BT_FUNC = re.compile(r"^\s*\d+:\s+(?:0x[0-9a-f]+ - )?(?P<func>\S.*?)\s*$")
_BT_AT = re.compile(r"^\s*at (?P<file>\S+?):(?P<line>\d+)(?::\d+)?\s*$")
_HASH = re.compile(r"::h[0-9a-f]{16}$")


def parse(text: str) -> list[ParsedTrace]:
    results: list[ParsedTrace] = []
    cur: dict | None = None  # {"file", "line", "msg", "frames", "in_bt", "pending"}

    def flush() -> None:
        nonlocal cur
        if cur and cur["msg"] is not None:
            frames = cur["frames"] or [Frame(cur["file"], cur["line"], "<panic>")]
            results.append(ParsedTrace(Family.RUST, "panic", cur["msg"], tuple(frames)))
        cur = None

    for line in text.split("\n"):
        s = line.strip()
        m = _NEW.match(s) or _OLD.match(s)
        if m:
            flush()
            cur = {
                "file": m["file"],
                "line": int(m["line"]),
                "msg": m.groupdict().get("msg"),
                "frames": [],
                "in_bt": False,
                "pending": None,
            }
            continue
        if cur is None or not s:
            continue
        if cur["msg"] is None:
            cur["msg"] = s
            continue
        if _BT_START.match(s):
            cur["in_bt"] = True
            continue
        if s.startswith("note:"):
            continue
        if cur["in_bt"]:
            at = _BT_AT.match(s)
            if at:
                if cur["pending"]:
                    cur["frames"].append(Frame(at["file"], int(at["line"]), cur["pending"]))
                cur["pending"] = None
                continue
            fn = _BT_FUNC.match(s)
            if fn:
                cur["pending"] = _HASH.sub("", fn["func"])
                continue
            flush()  # backtrace ended by an unrecognized line
    flush()
    return results
