import codecs
import sys
from pathlib import Path
from typing import Optional

import typer

from debugagent.orchestrator import diagnose as run_diagnose
from debugagent.parsers import PARSERS
from debugagent.patterns.loader import PatternError
from debugagent.render import DEFAULT_JSON_LIMIT, render_json, render_text
from debugagent.scanner import DEFAULT_MAP_PATH, load_map, save_map, scan as run_scan
from debugagent.subagent import build_subagents

app = typer.Typer(no_args_is_help=True, add_completion=False)

# Longest BOMs first so UTF-32-LE isn't mistaken for UTF-16-LE.
_BOMS = (
    (codecs.BOM_UTF32_LE, "utf-32"), (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16"), (codecs.BOM_UTF16_BE, "utf-16"),
)


@app.callback()
def main() -> None:
    """Debug Agent: diagnose stack traces across JVM, Python, Node, Go, and Rust services."""


def _fail(msg: str, code: int) -> typer.Exit:
    typer.echo(msg, err=True)
    return typer.Exit(code)


def _decode(data: bytes) -> str:
    """Decode input bytes, honouring a BOM (UTF-8/16/32) so Windows/PowerShell logs work."""
    for bom, enc in _BOMS:
        if data.startswith(bom):
            return data.decode(enc, errors="replace")
    # BOM-less UTF-16: many NUL bytes in alternating positions.
    if len(data) >= 4 and data.count(0) > len(data) // 4:
        even, odd = data[0::2].count(0), data[1::2].count(0)
        if odd > 2 * even:
            return data.decode("utf-16-le", errors="replace")
        if even > 2 * odd:
            return data.decode("utf-16-be", errors="replace")
    return data.decode("utf-8", errors="replace")


def _read_input(source: str | None) -> str:
    if source in (None, "-"):
        if sys.stdin.isatty():
            raise _fail("No input: pass a file path or pipe a stack trace on stdin "
                        "(e.g. `debugagent diagnose trace.txt` or `... | debugagent diagnose`).", 2)
        data = sys.stdin.buffer.read() if hasattr(sys.stdin, "buffer") else sys.stdin.read().encode()
    else:
        p = Path(source)
        if p.is_dir():
            raise _fail(f"Input is a directory, not a file: {source}", 2)
        if not p.exists():
            raise _fail(f"Input file not found: {source}", 2)
        try:
            data = p.read_bytes()
        except OSError as e:
            raise _fail(f"Cannot read input file {source}: {e.strerror or e}", 2) from None
    text = _decode(data)
    if not text.strip():
        raise _fail("No input: pass a file path or pipe a stack trace on stdin.", 2)
    return text


def _load_codebase(path: Optional[Path]):
    if path is None:
        return None
    if path.is_file():
        return load_map(path)
    if path.is_dir():
        mp = path / DEFAULT_MAP_PATH
        return load_map(mp) if mp.is_file() else run_scan(path, history=False)
    raise _fail(f"Codebase path not found: {path}", 2)


@app.command()
def diagnose(
    source: str | None = typer.Argument(None, help="File containing a trace/log; '-' or omitted reads stdin"),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON"),
    patterns: list[Path] = typer.Option([], "--patterns", help="Extra pattern directories"),  # noqa: B008
    limit: int = typer.Option(DEFAULT_JSON_LIMIT, "--limit", min=1,
                              help="Max hypotheses in JSON output"),
    timeout: float = typer.Option(2.0, "--timeout", help="Per-subagent timeout in seconds"),
    codebase: Optional[Path] = typer.Option(None, "--codebase", help="Codebase map JSON or repo root"),
) -> None:
    """Diagnose a stack trace or error log."""
    for pdir in patterns:
        if not pdir.is_dir():
            raise _fail(f"Pattern directory not found: {pdir}", 1)
    text = _read_input(source)
    try:
        subagents = build_subagents(patterns)
    except PatternError as e:
        raise _fail(f"Pattern database error: {e}", 1) from None
    d = run_diagnose(text, subagents, timeout_s=timeout, codebase=_load_codebase(codebase))
    if d.top is None:
        unsupported = sorted(f.value for f in d.families if f not in subagents)
        if unsupported:
            raise _fail(f"Detected {', '.join(unsupported)} trace(s), but no analyzer is available "
                        f"for {'it' if len(unsupported) == 1 else 'them'} yet.", 2)
        supported = ", ".join(sorted(f.value for f in PARSERS))
        raise _fail(f"No stack trace found in input (supported: {supported}).", 2)
    typer.echo(render_json(d, limit=limit) if json_out else render_text(d))


@app.command()
def scan(
    root: Path = typer.Argument(..., help="Repo or monorepo root to scan"),
    out: Optional[Path] = typer.Option(None, "--out", help="Map file (default ROOT/.debugagent/codebase.json)"),
    history: bool = typer.Option(True, "--history/--no-history", help="Mine git history for bug tags"),
) -> None:
    """Scan services, languages, frameworks and the call graph (read-only)."""
    if not root.is_dir():
        raise _fail(f"Root directory not found: {root}", 2)
    m = run_scan(root, history=history)
    if not m.services:
        raise _fail(
            f"No services found under {root} (looked for pom.xml, go.mod, package.json, ...).", 2
        )
    dest = out or (root / DEFAULT_MAP_PATH)
    save_map(m, dest)
    for name, s in sorted(m.services.items()):
        calls = ", ".join(m.edges.get(name, [])) or "-"
        typer.echo(f"{name:<20} {s.family.value:<7} {','.join(s.frameworks) or '-':<22} calls: {calls}")
    typer.echo(f"Wrote {dest}")


@app.command("eval")
def eval_cmd(
    corpus: Path = typer.Argument(..., help="Directory containing traces and labels.yaml"),
    codebase: Optional[Path] = typer.Option(None, "--codebase"),
    patterns: list[Path] = typer.Option([], "--patterns"),  # noqa: B008
    min_accuracy: float = typer.Option(0.85, "--min-accuracy"),
    min_coverage: float = typer.Option(0.95, "--min-coverage"),
    max_subagent_s: float = typer.Option(2.0, "--max-subagent-s"),
) -> None:
    """Measure accuracy, coverage and latency on a labeled trace corpus."""
    from debugagent.evaluation import evaluate
    if not corpus.is_dir():
        raise _fail(f"Corpus directory not found: {corpus}", 2)
    r = evaluate(corpus, build_subagents(patterns), codebase=_load_codebase(codebase))
    typer.echo(
        f"cases {len(r.results)}  accuracy {r.accuracy:.1%}  coverage {r.coverage:.1%}  "
        f"p95 {r.p95_latency_s * 1000:.0f} ms  max subagent {r.max_subagent_s * 1000:.0f} ms"
    )
    for fam, acc in r.per_family.items():
        typer.echo(f"  {fam:<8} {acc:.1%}")
    for c in (c for c in r.results if not c.correct):
        typer.echo(
            f"  MISS {c.file}: expected {c.expected}"
            f"{'@' + c.service_expected if c.service_expected else ''}, "
            f"got {c.got}{'@' + c.service_got if c.service_got else ''}"
        )
    failures = []
    if r.accuracy < min_accuracy:
        failures.append(f"accuracy {r.accuracy:.1%} < {min_accuracy:.1%}")
    if r.coverage < min_coverage:
        failures.append(f"coverage {r.coverage:.1%} < {min_coverage:.1%}")
    if r.max_subagent_s >= max_subagent_s:
        failures.append(f"max subagent {r.max_subagent_s:.2f}s >= {max_subagent_s:.2f}s")
    if failures:
        typer.echo("FAIL: " + "; ".join(failures), err=True)
        raise typer.Exit(1)
    typer.echo("PASS")
