import sys
from pathlib import Path
from typing import Optional
import typer
from debugagent.orchestrator import diagnose as run_diagnose
from debugagent.patterns.loader import PatternError
from debugagent.render import render_json, render_text
from debugagent.subagent import build_subagents

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.callback()
def main() -> None:
    """Debug Agent: diagnose stack traces across JVM, Python, Node, Go, and Rust services."""


def _read_input(source: Optional[str]) -> str:
    if source in (None, "-"):
        data = sys.stdin.buffer.read() if hasattr(sys.stdin, "buffer") else sys.stdin.read().encode()
    else:
        p = Path(source)
        if not p.is_file():
            typer.echo(f"Input file not found: {source}", err=True)
            raise typer.Exit(2)
        data = p.read_bytes()
    text = data.decode("utf-8", errors="replace")
    if not text.strip():
        typer.echo("No input: pass a file path or pipe a stack trace on stdin.", err=True)
        raise typer.Exit(2)
    return text


@app.command()
def diagnose(
    source: Optional[str] = typer.Argument(None, help="File containing a trace/log; '-' or omitted reads stdin"),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON"),
    patterns: list[Path] = typer.Option([], "--patterns", help="Extra pattern directories"),
) -> None:
    """Diagnose a stack trace or error log."""
    text = _read_input(source)
    try:
        subagents = build_subagents(patterns)
    except PatternError as e:
        typer.echo(f"Pattern database error: {e}", err=True)
        raise typer.Exit(1)
    d = run_diagnose(text, subagents)
    if d.top is None:
        typer.echo("No stack trace found in input (supported: JVM, Python, Node, Go, Rust).", err=True)
        raise typer.Exit(2)
    typer.echo(render_json(d) if json_out else render_text(d))
