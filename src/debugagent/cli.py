import codecs
import sys
from pathlib import Path

import typer

from debugagent.orchestrator import diagnose as run_diagnose
from debugagent.parsers import PARSERS
from debugagent.patterns.loader import PatternError
from debugagent.render import DEFAULT_JSON_LIMIT, render_json, render_text
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


@app.command()
def diagnose(
    source: str | None = typer.Argument(None, help="File containing a trace/log; '-' or omitted reads stdin"),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON"),
    patterns: list[Path] = typer.Option([], "--patterns", help="Extra pattern directories"),  # noqa: B008
    limit: int = typer.Option(DEFAULT_JSON_LIMIT, "--limit", min=1,
                              help="Max hypotheses in JSON output"),
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
    d = run_diagnose(text, subagents)
    if d.top is None:
        unsupported = sorted(f.value for f in d.families if f not in subagents)
        if unsupported:
            raise _fail(f"Detected {', '.join(unsupported)} trace(s), but no analyzer is available "
                        f"for {'it' if len(unsupported) == 1 else 'them'} yet.", 2)
        supported = ", ".join(sorted(f.value for f in PARSERS))
        raise _fail(f"No stack trace found in input (supported: {supported}).", 2)
    typer.echo(render_json(d, limit=limit) if json_out else render_text(d))
