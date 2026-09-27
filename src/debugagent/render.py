import json
import textwrap
from debugagent.models import Diagnosis, Frame, Hypothesis


def _loc(f: Frame) -> str:
    return f"{f.file}:{f.line if f.line is not None else '?'} in {f.function}"


def _hyp_block(h: Hypothesis) -> list[str]:
    lines = [f"Top diagnosis (confidence {h.confidence:.0%}) — {h.pattern_id} [{h.category}]"]
    if h.service:
        lines.append(f"Service: {h.service}")
    lines += [f"Error: {h.error_type}: {h.message}", f"Root cause: {h.root_cause}", "Where:"]
    lines += [f"  {i}. {_loc(f)}" for i, f in enumerate(h.locations, 1)] or ["  (no frames)"]
    if h.fixes:
        lines.append("Fixes:")
        lines += [f"  {i}. {fx.summary}\n     trade-off: {fx.tradeoff}" for i, fx in enumerate(h.fixes, 1)]
    if h.evidence:
        lines.append("Evidence:")
        lines += [f"  - {e}" for e in h.evidence]
    if h.repro_test:
        lines += ["Repro test:", textwrap.indent(h.repro_test.rstrip(), "    ")]
    return lines


def render_text(d: Diagnosis, limit: int = 3) -> str:
    if d.top is None:
        return "No stack trace found."
    lines = _hyp_block(d.top)
    others = d.hypotheses[1:limit]
    if others:
        lines.append("Other hypotheses:")
        lines += [f"  - {h.pattern_id} ({h.confidence:.0%})"
                  f"{' in ' + h.service if h.service else ''}: {h.error_type}" for h in others]
    if d.notes:
        lines.append("Notes:")
        lines += [f"  - {n}" for n in d.notes]
    return "\n".join(lines)


def _h(h: Hypothesis) -> dict:
    return {
        "pattern_id": h.pattern_id, "family": h.family.value, "category": h.category,
        "confidence": h.confidence, "service": h.service, "error_type": h.error_type,
        "message": h.message, "root_cause": h.root_cause,
        "fixes": [{"summary": f.summary, "tradeoff": f.tradeoff} for f in h.fixes],
        "locations": [{"file": f.file, "line": f.line, "function": f.function, "module": f.module}
                      for f in h.locations],
        "repro_test": h.repro_test, "tags": list(h.tags), "evidence": list(h.evidence),
    }


def render_json(d: Diagnosis) -> str:
    return json.dumps({
        "families": sorted(f.value for f in d.families),
        "hypotheses": [_h(h) for h in d.hypotheses],
        "notes": list(d.notes),
    }, indent=2)
