from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum


class Family(str, Enum):
    JVM = "jvm"
    PYTHON = "python"
    NODE = "node"
    GO = "go"
    RUST = "rust"


@dataclass(frozen=True)
class Frame:
    file: str
    line: int | None
    function: str
    module: str | None = None


@dataclass(frozen=True)
class ParsedTrace:
    family: Family
    error_type: str
    message: str
    frames: tuple[Frame, ...]          # innermost (where it blew up) FIRST
    cause: ParsedTrace | None = None

    def root(self) -> ParsedTrace:
        t = self
        while t.cause is not None:
            t = t.cause
        return t

    @property
    def short_error_type(self) -> str:
        return self.error_type.rsplit(".", 1)[-1]


@dataclass(frozen=True)
class FixOption:
    summary: str
    tradeoff: str


@dataclass(frozen=True)
class Hypothesis:
    family: Family
    pattern_id: str                    # "<family>.unknown" when nothing matched
    category: str                      # "code" | "dependency" | "resource" | "config" | "unknown"
    root_cause: str
    confidence: float                  # 0.0–1.0
    error_type: str
    message: str
    fixes: tuple[FixOption, ...]
    locations: tuple[Frame, ...]       # app frames only, innermost first, max 3
    repro_test: str
    tags: tuple[str, ...] = ()
    service: str | None = None
    evidence: tuple[str, ...] = field(default=())


@dataclass(frozen=True)
class Diagnosis:
    hypotheses: tuple[Hypothesis, ...]  # sorted by confidence desc
    families: frozenset[Family]
    notes: tuple[str, ...] = ()         # truncation, subagent timeouts/crashes

    @property
    def top(self) -> Hypothesis | None:
        return self.hypotheses[0] if self.hypotheses else None
