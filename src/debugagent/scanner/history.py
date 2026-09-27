import re
import subprocess
from pathlib import Path

from debugagent.scanner.models import ServiceInfo

_FIX = re.compile(r"\b(fix(e[sd])?|bug(fix)?|hotfix|patch|regression|revert)\b", re.I)
TAG_KEYWORDS: dict[str, re.Pattern[str]] = {
    k: re.compile(v, re.I)
    for k, v in {
        "null": r"\bnull\b|\bnil\b|\bnone(type)?\b|\bnpe\b|nullpointer|undefined|optional",
        "timezone": r"time ?zone|\btz\b|\butc\b|\bdst\b|offset",
        "timeout": r"timeout|timed out|deadline",
        "pool": r"\bpool\b|hikari|connection leak",
        "leak": r"leak|\boom\b|out of memory",
        "concurrency": r"\brace\b|deadlock|concurren|mutex|\block(ing)?\b|goroutine",
        "off-by-one": r"off[- ]by[- ]one|\bindex\b|bounds",
        "parsing": r"\bpars(e|ing)|json|deserializ|serializ",
        "import": r"\bimport\b|module not found|missing dependency",
        "config": r"\bconfig\b|env var|\bproperty\b|\bprofile\b",
        "recursion": r"recursion|stack ?overflow",
        "encoding": r"utf-?8|encoding|unicode",
    }.items()
}


def mine_history(
    root: Path,
    services: dict[str, ServiceInfo],
    max_commits: int = 2000,
) -> dict[str, dict[str, int]]:
    root = Path(root)
    probe = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0:
        return {}
    out: dict[str, dict[str, int]] = {}
    for name, s in services.items():
        r = subprocess.run(
            ["git", "-C", str(root), "log", "--no-merges",
             f"-n{max_commits}", "--format=%s", "--", s.path],
            capture_output=True,
            text=True,
            timeout=30,
        )
        counts: dict[str, int] = {}
        for subject in r.stdout.splitlines():
            if not _FIX.search(subject):
                continue
            for tag, rx in TAG_KEYWORDS.items():
                if rx.search(subject):
                    counts[tag] = counts.get(tag, 0) + 1
        if counts:
            out[name] = counts
    return out
