import re
from dataclasses import dataclass, field

from debugagent.models import Family, Frame, ParsedTrace

# Leading whitespace tolerated: raw logs sometimes indent the panic line. A nested
# re-panic ("\tpanic: second") only ever appears before the dump and is ignored there.
_PANIC = re.compile(r"^\s*panic: (?P<body>.*?)(?: \[recovered\])?\s*$")
_FATAL = re.compile(r"^\s*fatal error: (?P<body>.*?)!?\s*$")
# GOTRACEBACK=system adds fields: "goroutine 1 gp=0xc000002380 m=0 mp=0x5a2b40 [running]:"
_GOROUTINE = re.compile(r"^goroutine \d+ (?:\S+ )*\[[^\]]*\]:?\s*$")
# "\t/path/file.go:42 +0x26", optionally with " fp=0x… sp=0x… pc=0x…"; paths may contain spaces.
_FILE = re.compile(
    r"^\s+(?P<file>\S(?:.*?\S)?\.go):(?P<line>\d+)(?:\s+\+0x[0-9a-f]+)?(?:\s+\w+=0x[0-9a-f]+)*\s*$"
)
_CREATED = re.compile(r"^\s*created by ")


def _func_name(s: str) -> str:
    i = s.rfind("(")
    return s[:i] if i > 0 and s.endswith(")") else s


def _strip_hash(name: str) -> str:
    """Strip a ::h<hex> symbol-mangling suffix (seen in cgo/Rust-linked frames)."""
    return re.sub(r"::h[0-9a-f]+$", "", name)


def _classify(kind: str, body: str) -> tuple[str, str]:
    if kind == "fatal":
        return "fatal error", body
    if body.startswith("runtime error: "):
        return "runtime error", body[len("runtime error: "):]
    return "panic", body


@dataclass
class _Cur:
    etype: str
    msg: str
    state: str = "await"            # "await" (before the goroutine dump) | "frames"
    frames: list[Frame] = field(default_factory=list)
    pending: str | None = None      # function line waiting for its file:line


def parse(text: str) -> list[ParsedTrace]:
    results: list[ParsedTrace] = []
    cur: _Cur | None = None

    def flush() -> None:
        nonlocal cur
        # Frameless traces are kept only for runtime-generated failures ("fatal error:",
        # "panic: runtime error:"): OOM and GOTRACEBACK=none print no goroutine dump.
        # A bare "panic: <text>" without a dump may just be a log line, so it is dropped.
        if cur is not None and (cur.frames or cur.etype != "panic"):
            results.append(ParsedTrace(Family.GO, cur.etype, cur.msg, tuple(cur.frames)))
        cur = None

    for line in text.split("\n"):
        m = _FATAL.match(line) or _PANIC.match(line)
        if m and not (cur and cur.state == "frames" and line[:1].isspace()):
            if cur and cur.state == "await":
                continue            # nested panic before the dump (recovered): keep the original
            flush()
            etype, msg = _classify("fatal" if m.re is _FATAL else "panic", m["body"])
            cur = _Cur(etype, msg)
            continue
        if cur is None:
            continue
        if _GOROUTINE.match(line.strip()):
            if cur.state == "await":
                cur.state = "frames"
            else:
                flush()             # second goroutine block: only the panicking one matters
            continue
        if cur.state != "frames":
            continue                # "runtime stack:" section, [signal …] line, etc.
        if not line.strip():
            flush()
            continue
        fl = _FILE.match(line)
        if fl:
            if cur.pending:
                cur.frames.append(Frame(fl["file"], int(fl["line"]), cur.pending))
            cur.pending = None
            continue
        if _CREATED.match(line) or line.lstrip().startswith("..."):
            cur.pending = None      # spawner frame / "...additional frames elided..."
        else:
            cur.pending = _strip_hash(_func_name(line.strip()))
    flush()
    return results
