from debugagent.aggregator import aggregate
from debugagent.detect import MAX_INPUT_CHARS, detect_families, normalize
from debugagent.models import Diagnosis, Family, Hypothesis
from debugagent.subagent import LanguageSubagent


def diagnose(text: str, subagents: dict[Family, LanguageSubagent]) -> Diagnosis:
    notes: list[str] = []
    if len(text) > MAX_INPUT_CHARS:
        notes.append(f"input truncated to its last {MAX_INPUT_CHARS:,} characters")
    clean = normalize(text)
    families = detect_families(clean)
    hyps: list[Hypothesis] = []
    for fam in sorted(families, key=lambda f: f.value):
        if fam in subagents:
            hyps.extend(subagents[fam].run(clean))
        else:
            notes.append(f"detected {fam.value} trace(s) but no {fam.value} analyzer is available yet")
    return Diagnosis(aggregate(hyps), families, tuple(notes))
