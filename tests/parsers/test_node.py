from pathlib import Path

import pytest

from debugagent.detect import detect_families, normalize
from debugagent.models import Family
from debugagent.parsers.node import parse

CAUSE = Path("tests/data/node_cause.txt").read_text()


def test_simple_typeerror_frames_and_anonymous():
    text = ("TypeError: Cannot read properties of undefined (reading 'id')\n"
            "    at getUser (/srv/web/src/users.ts:14:22)\n"
            "    at Layer.handle [as handle_request] (/srv/web/node_modules/express/lib/router/layer.js:95:5)\n"
            "    at /srv/web/src/anon.js:3:1\n")
    [t] = parse(text)
    assert (t.error_type, t.message) == ("TypeError", "Cannot read properties of undefined (reading 'id')")
    assert t.frames[0].function == "getUser" and t.frames[0].line == 14
    assert t.frames[2].function == "<anonymous>" and t.frames[2].file == "/srv/web/src/anon.js"

# Review Focus #2: chained causes → innermost
def test_cause_chain_root_is_econnrefused():
    [t] = parse(CAUSE)
    assert t.message == "failed to load user 42"
    assert t.cause.error_type == "TypeError"
    assert t.root().message == "connect ECONNREFUSED 10.0.3.7:8080"

def test_error_code_bracket_is_kept_in_message():
    text = ("Error [ERR_MODULE_NOT_FOUND]: Cannot find package 'zod' imported from /srv/web/src/a.mjs\n"
            "    at new NodeError (node:internal/errors:405:5)\n")
    [t] = parse(text)
    assert t.error_type == "Error" and t.message.startswith("[ERR_MODULE_NOT_FOUND] Cannot find package")

def test_cjs_loader_preamble_then_error():
    text = ("node:internal/modules/cjs/loader:1080\n  throw err;\n  ^\n\n"
            "Error: Cannot find module 'express'\nRequire stack:\n- /srv/web/src/index.js\n"
            "    at Module._resolveFilename (node:internal/modules/cjs/loader:1077:15)\n")
    [t] = parse(text)
    assert t.message == "Cannot find module 'express'"

def test_heap_oom_without_frames():
    text = "FATAL ERROR: Reached heap limit Allocation failed - JavaScript heap out of memory\n"
    assert detect_families(text) == {Family.NODE}
    [t] = parse(text)
    assert t.error_type == "FatalError" and "heap out of memory" in t.message

def test_error_line_without_frames_is_ignored():
    assert parse("Error: something happened\nINFO fine\n") == []

def test_unhandled_rejection_without_frames_is_kept():
    text = ("node:internal/process/promises:288\n    triggerUncaughtException(err, true);\n    ^\n\n"
            '[UnhandledPromiseRejection: This error originated either by throwing inside of an async '
            'function without a catch block. The promise rejected with the reason "oops".] {\n'
            "  code: 'ERR_UNHANDLED_REJECTION'\n}\n")
    assert detect_families(text) == {Family.NODE}
    [t] = parse(text)
    assert t.error_type == "UnhandledPromiseRejection"


# --- Beyond the plan: real-world variants found in earlier reviews -------------

# Review Focus #1
def test_log_wrapped_cause_chain_parses_like_clean():
    wrapped = "\r\n".join(f"2026-09-26T10:00:00Z ERROR [web] \x1b[31m{ln}\x1b[0m" for ln in CAUSE.splitlines())
    [t] = parse(normalize(wrapped))
    assert t.root().message == "connect ECONNREFUSED 10.0.3.7:8080"

@pytest.mark.parametrize("frame,file,func", [
    ("    at f (C:\\srv\\web\\a.js:1:2)", "C:\\srv\\web\\a.js", "f"),
    ("    at f (/Users/a b/app.js:1:2)", "/Users/a b/app.js", "f"),
    ("    at f (file:///srv/web/a.mjs:1:2)", "/srv/web/a.mjs", "f"),
    ("    at async g (/srv/web/a.ts:1:2)", "/srv/web/a.ts", "g"),
    ("    at new Foo (/srv/web/a.ts:1:2)", "/srv/web/a.ts", "new Foo"),
])
def test_frame_variants(frame, file, func):
    [t] = parse("TypeError: x\n" + frame + "\n")
    assert (t.frames[0].file, t.frames[0].function) == (file, func)

def test_locationless_frames_do_not_end_the_trace():
    text = ("Error: boom\n    at a (/srv/web/a.ts:1:2)\n    at async Promise.all (index 0)\n"
            "    at new Promise (<anonymous>)\n    at b (/srv/web/b.ts:3:4)\n")
    [t] = parse(text)
    assert [f.file for f in t.frames] == ["/srv/web/a.ts", "/srv/web/b.ts"]

def test_custom_error_class_and_uncaught_prefix():
    [t] = parse("Uncaught ValidationError: bad email\n    at v (/srv/web/v.ts:1:2)\n")
    assert t.error_type == "ValidationError"

def test_aggregate_error_sub_errors_do_not_replace_the_trace():
    text = ("AggregateError: All promises were rejected\n    at a (/srv/web/a.ts:1:2) {\n"
            "  [errors]: [\n    Error: first\n        at x (/srv/web/x.ts:1:1),\n  ]\n}\n")
    [t] = parse(text)
    assert t.error_type == "AggregateError" and len(t.frames) == 1

def test_two_traces_separated_by_log_line():
    one = "TypeError: a\n    at f (/srv/web/a.ts:1:2)\n"
    assert len(parse(one + "INFO next request\n" + one)) == 2

def test_node_colon_text_in_prose_is_not_detected():
    assert detect_families("see node:x:1:2 in the docs\n") == frozenset()

def test_python_and_jvm_traces_are_not_node():
    assert parse('Traceback (most recent call last):\n  File "/a.py", line 1, in f\n    x\nKeyError: 1\n') == []
    assert parse("java.lang.IllegalStateException: x\n\tat com.a.B.c(B.java:1)\n") == []
