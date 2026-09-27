import re
from dataclasses import dataclass
from pathlib import Path
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


def _build(path: Path, d: dict, source: str) -> Pattern:
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
    try:
        etype = re.compile(d["error_type"])
        mrx = re.compile(d["message_regex"]) if d.get("message_regex") else None
    except re.error as e:
        raise PatternError(f"{path}: bad message_regex/error_type: {e}") from None
    return Pattern(
        id=d["id"], family=family, error_type=etype, message_regex=mrx,
        category=d["category"], root_cause=d["root_cause"].strip(), base_confidence=float(conf),
        fixes=tuple(FixOption(f["summary"], f["tradeoff"]) for f in fixes),
        repro_template=d.get("repro_template") or FAMILY_REPRO[family],
        tags=tuple(d.get("tags", ())), source=d.get("source", source),
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
