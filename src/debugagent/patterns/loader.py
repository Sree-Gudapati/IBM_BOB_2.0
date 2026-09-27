import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import yaml
from debugagent.models import Family, FixOption
from debugagent.patterns.repro import FAMILY_REPRO

DEFAULT_PATTERN_DIR = Path(__file__).parent / "data"
CATEGORIES = {"code", "dependency", "resource", "config"}
_REQUIRED = ("id", "family", "error_type", "category", "root_cause", "base_confidence", "fixes")


class PatternError(ValueError):
    pass


@dataclass(frozen=True)
class Pattern:
    id: str
    family: Family
    error_type: re.Pattern[str]
    message_regex: re.Pattern[str] | None
    category: str
    root_cause: str
    base_confidence: float
    fixes: tuple[FixOption, ...]
    repro_template: str
    tags: tuple[str, ...]
    source: str            # "builtin" | "manual" | "learned"


def _str_field(path: Path, d: dict[str, Any], key: str) -> str:
    v = d[key]
    if not isinstance(v, str) or not v.strip():
        raise PatternError(f"{path}: '{key}' must be a non-empty string, got {v!r}")
    return v


def _build(path: Path, d: dict[str, Any], source: str) -> Pattern:
    if not isinstance(d, dict):
        raise PatternError(f"{path}: top level must be a mapping")
    for k in _REQUIRED:
        if k not in d:
            raise PatternError(f"{path}: missing required key '{k}'")
    try:
        family = Family(d["family"])
    except ValueError:
        raise PatternError(f"{path}: unknown family {d['family']!r}") from None
    if d["category"] not in CATEGORIES:
        raise PatternError(f"{path}: category must be one of {sorted(CATEGORIES)}")
    conf = d["base_confidence"]
    if not isinstance(conf, (int, float)) or not 0 < conf < 1:
        raise PatternError(f"{path}: base_confidence must be in (0, 1), got {conf!r}")
    fixes = d["fixes"]
    if not isinstance(fixes, list) or not 2 <= len(fixes) <= 3:
        raise PatternError(
            f"{path}: need 2-3 fixes with trade-offs, got "
            f"{len(fixes) if isinstance(fixes, list) else fixes!r}"
        )
    for i, f in enumerate(fixes):
        if not (isinstance(f, dict) and all(isinstance(f.get(k), str) and f[k].strip()
                                            for k in ("summary", "tradeoff"))):
            raise PatternError(f"{path}: fixes[{i}] needs non-empty 'summary' and 'tradeoff' strings")
    tags = d.get("tags") or []
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        raise PatternError(f"{path}: tags must be a list of strings (quote YAML words like null/yes/no)")
    pid, root_cause, etype_src = (_str_field(path, d, k) for k in ("id", "root_cause", "error_type"))
    mrx_src = d.get("message_regex")
    if mrx_src is not None and not isinstance(mrx_src, str):
        raise PatternError(f"{path}: 'message_regex' must be a string, got {mrx_src!r}")
    try:
        etype = re.compile(etype_src)
        mrx = re.compile(mrx_src) if mrx_src else None
    except re.error as e:
        raise PatternError(f"{path}: bad message_regex/error_type: {e}") from None
    return Pattern(
        id=pid, family=family, error_type=etype, message_regex=mrx,
        category=d["category"], root_cause=root_cause.strip(), base_confidence=float(conf),
        fixes=tuple(FixOption(f["summary"], f["tradeoff"]) for f in fixes),
        repro_template=d.get("repro_template") or FAMILY_REPRO[family],
        tags=tuple(tags), source=d.get("source", source),
    )


def load_patterns(*dirs: Path) -> list[Pattern]:
    out: dict[str, Pattern] = {}
    for base in dirs:
        base = Path(base)
        if not base.is_dir():
            continue
        source = "builtin" if base.resolve() == DEFAULT_PATTERN_DIR.resolve() else "manual"
        for path in sorted(base.rglob("*.yaml")):
            try:
                data = yaml.safe_load(path.read_text())
            except yaml.YAMLError as e:
                raise PatternError(f"{path}: invalid YAML: {e}") from None
            p = _build(path, data, source)
            if p.id in out:
                raise PatternError(f"{path}: duplicate id {p.id!r}")
            out[p.id] = p
    return list(out.values())
