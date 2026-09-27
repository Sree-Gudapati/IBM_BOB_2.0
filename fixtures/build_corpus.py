"""
Regenerate fixtures/sample-system and fixtures/traces.
Run: python fixtures/build_corpus.py
"""
import re
import shutil
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.conftest import SAMPLE_SYSTEM_FILES
from tests.patterns.test_go_patterns import GO_CASES
from tests.patterns.test_jvm_patterns import JVM_CASES
from tests.patterns.test_node_patterns import NODE_CASES
from tests.patterns.test_python_patterns import PY_CASES
from tests.patterns.test_rust_patterns import RUST_CASES

HERE = Path(__file__).parent
TRACES = HERE / "traces"
SERVICE = {
    "python": "billing",
    "jvm": "orders",
    "node": "web",
    "go": "inventory",
    "rust": "ledger",
}
FRAMES = {
    "python": [
        ("/srv/billing/app/invoice.py", 7, "build", None),
        ("/srv/billing/app/api.py", 20, "handle", None),
    ],
    "jvm": [
        ("Discounts.java", 18, "Discounts.forName", "com.acme.orders.pricing.Discounts"),
        ("Pricer.java", 52, "Pricer.price", "com.acme.orders.pricing.Pricer"),
    ],
    "node": [
        ("/srv/web/src/users.ts", 14, "getUser", None),
        ("/srv/web/src/api.ts", 30, "handler", None),
    ],
    "go": [
        ("/srv/inventory/store.go", 42, "main.(*Store).Get", None),
        ("/srv/inventory/main.go", 18, "main.handler", None),
    ],
    "rust": [
        ("./src/ledger.rs", 27, "ledger_svc::post_entry", None),
        ("./src/main.rs", 9, "ledger_svc::main", None),
    ],
}
UNKNOWN = {
    "python": ("WeirdCustomError", "flux capacitor overloaded"),
    "jvm": ("com.acme.FluxException", "flux capacitor overloaded"),
    "node": ("QuantumError", "flux capacitor overloaded"),
    "go": ("panic", "flux capacitor overloaded"),
    "rust": ("panic", "flux capacitor overloaded"),
}


def render(fam: str, etype: str, msg: str) -> list[str]:
    fr = FRAMES[fam]
    if fam == "python":
        out = ["Traceback (most recent call last):"]
        for f, ln, fn, _ in reversed(fr):
            out += [f'  File "{f}", line {ln}, in {fn}', "    pass"]
        return out + [f"{etype}: {msg}" if msg else etype]
    if fam == "jvm":
        lines = [f"{etype}: {msg}" if msg else etype]
        for f, ln, fn, m in fr:
            lines.append(f"\tat {m}.{fn.split('.')[-1]}({f}:{ln})")
        return lines
    if fam == "node":
        if etype == "FatalError":
            return [f"FATAL ERROR: {msg}"]
        code = re.match(r"\[(\w+)\] (.*)", msg)
        head = f"{etype} [{code[1]}]: {code[2]}" if code else f"{etype}: {msg}"
        return [head] + [f"    at {fn} ({f}:{ln}:5)" for f, ln, fn, _ in fr]
    if fam == "go":
        emap = {"runtime error": f"panic: runtime error: {msg}", "fatal error": f"fatal error: {msg}"}
        head = emap.get(etype, f"panic: {msg}")
        body: list[str] = []
        for f, ln, fn, _ in fr:
            body += [f"{fn}(...)", f"\t{f}:{ln} +0x1d"]
        return [head, "", "goroutine 1 [running]:"] + body
    # rust
    f0, l0 = fr[0][0].lstrip("./"), fr[0][1]
    out = [
        f"thread 'main' panicked at {f0}:{l0}:5:",
        msg,
        "stack backtrace:",
        "   0: rust_begin_unwind",
        "             at /rustc/abc/library/std/src/panicking.rs:645:5",
    ]
    for i, (f, ln, fn, _) in enumerate(fr, 1):
        out += [f"   {i}: {fn}", f"             at {f}:{ln}:5"]
    return out


VARIANTS = {
    "clean": lambda lines, svc: "\n".join(lines) + "\n",
    "logprefixed": lambda lines, svc: "\n".join(
        f"2026-09-26T10:00:00.000Z ERROR [{svc}] {ln}" for ln in lines
    ) + "\n",
    "ansi_crlf": lambda lines, svc: "\r\n".join(
        f"\x1b[31m{ln}\x1b[0m" for ln in lines
    ) + "\r\n",
}

MIXED = [
    (
        "web_timeout_orders_npe",
        [
            ("node", "AxiosError", "timeout of 5000ms exceeded"),
            ("jvm", "java.lang.NullPointerException", 'Cannot invoke "String.length()" because "n" is null'),
        ],
        "jvm.npe.helpful", "orders",
    ),
    (
        "billing_json_ledger_unwrap",
        [
            ("python", "json.decoder.JSONDecodeError", "Expecting value: line 1 column 1"),
            ("rust", "panic", "called `Option::unwrap()` on a `None` value"),
        ],
        "rust.unwrap_none", "ledger",
    ),
    (
        "orders_timeout_inventory_nil",
        [
            ("jvm", "java.net.SocketTimeoutException", "Read timed out"),
            ("go", "runtime error", "invalid memory address or nil pointer dereference"),
        ],
        "go.nil_pointer", "inventory",
    ),
]

HANDWRITTEN = {
    "python_none.txt": ("python.attribute_error.none_type", "billing"),
    "jvm_chained.txt": ("jvm.npe.helpful", "orders"),
    "node_cause.txt": ("node.econnrefused", "web"),
}


def main() -> None:
    sysdir = HERE / "sample-system"
    shutil.rmtree(sysdir, ignore_errors=True)
    for rel, content in SAMPLE_SYSTEM_FILES.items():
        p = sysdir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)

    shutil.rmtree(TRACES, ignore_errors=True)
    cases = []

    # rust cases use (msg, expected) tuples — add the etype
    tables = {
        "python": PY_CASES,
        "jvm": JVM_CASES,
        "node": NODE_CASES,
        "go": GO_CASES,
        "rust": [("panic", m, e) for m, e in RUST_CASES],
    }
    for fam, rows in tables.items():
        rows = list(rows) + [(*UNKNOWN[fam], f"{fam}.unknown")]
        for etype, msg, expected in rows:
            for vname, v in VARIANTS.items():
                rel = f"{fam}/{expected.split('.', 1)[1]}__{vname}.txt"
                (TRACES / rel).parent.mkdir(parents=True, exist_ok=True)
                (TRACES / rel).write_bytes(v(render(fam, etype, msg), SERVICE[fam]).encode())
                frameless = fam == "node" and etype == "FatalError"
                cases.append({
                    "file": rel,
                    "expected": expected,
                    "service": None if frameless else SERVICE[fam],
                })

    for name, parts, expected, svc in MIXED:
        text = "".join(
            VARIANTS["logprefixed"](render(f, e, m), SERVICE[f]) for f, e, m in parts
        )
        rel = f"mixed/{name}.txt"
        (TRACES / rel).parent.mkdir(parents=True, exist_ok=True)
        (TRACES / rel).write_text(text)
        cases.append({"file": rel, "expected": expected, "service": svc})

    for src, (expected, svc) in HANDWRITTEN.items():
        rel = f"handwritten/{src}"
        (TRACES / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(HERE.parent / "tests" / "data" / src, TRACES / rel)
        cases.append({"file": rel, "expected": expected, "service": svc})

    (TRACES / "labels.yaml").write_text(yaml.safe_dump({"cases": cases}, sort_keys=False))
    print(f"wrote {len(cases)} cases")


if __name__ == "__main__":
    main()
