from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from debugagent.models import Family, Hypothesis, ParsedTrace
from debugagent.parsers import PARSERS
from debugagent.patterns.loader import DEFAULT_PATTERN_DIR, Pattern, load_patterns
from debugagent.patterns.matcher import match_trace


@dataclass
class LanguageSubagent:
    family: Family
    parse: Callable[[str], list[ParsedTrace]]
    patterns: list[Pattern]

    def run(self, text: str) -> list[Hypothesis]:
        return [match_trace(t, self.patterns) for t in self.parse(text)]


def build_subagents(extra_pattern_dirs: Sequence[Path] = ()) -> dict[Family, LanguageSubagent]:
    pats = load_patterns(DEFAULT_PATTERN_DIR, *extra_pattern_dirs)
    return {
        fam: LanguageSubagent(fam, parser, [p for p in pats if p.family is fam])
        for fam, parser in PARSERS.items()
    }
