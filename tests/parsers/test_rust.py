from debugagent.parsers.rust import parse

NEW = (
    "thread 'main' panicked at src/ledger.rs:27:18:\n"
    "called `Option::unwrap()` on a `None` value\n"
    "note: run with `RUST_BACKTRACE=1` environment variable to display a backtrace\n"
)
OLD = "thread 'main' panicked at 'called `Option::unwrap()` on a `None` value', src/ledger.rs:27:18\n"
BT = """thread 'tokio-runtime-worker' panicked at src/ledger.rs:27:18:
called `Result::unwrap()` on an `Err` value: Os { code: 111, kind: ConnectionRefused, message: "Connection refused" }
stack backtrace:
   0: rust_begin_unwind
             at /rustc/90c541806f23a127002de5b4038be731ba1458ca/library/std/src/panicking.rs:645:5
   1: core::panicking::panic_fmt
             at /rustc/90c541806f23a127002de5b4038be731ba1458ca/library/core/src/panicking.rs:72:14
   2: core::result::unwrap_failed
   3: ledger::post_entry::h0123456789abcdef
             at ./src/ledger.rs:27:18
   4: ledger::main
             at ./src/main.rs:9:5
note: Some details are omitted, run with `RUST_BACKTRACE=full` for a verbose backtrace.
"""


def test_new_format():
    [t] = parse(NEW)
    assert t.error_type == "panic" and t.message == "called `Option::unwrap()` on a `None` value"
    assert (t.frames[0].file, t.frames[0].line, t.frames[0].function) == ("src/ledger.rs", 27, "<panic>")


def test_old_format():
    [t] = parse(OLD)
    assert t.message == "called `Option::unwrap()` on a `None` value" and t.frames[0].line == 27


def test_backtrace_frames_with_location_only_and_hash_stripped():
    [t] = parse(BT)
    assert t.message.startswith("called `Result::unwrap()` on an `Err` value")
    assert [f.function for f in t.frames] == [
        "rust_begin_unwind", "core::panicking::panic_fmt", "ledger::post_entry", "ledger::main"
    ]


def test_two_panics():
    assert len(parse(NEW + "INFO restarting\n" + NEW)) == 2


def test_no_backtrace_gets_single_panic_frame():
    text = "thread 'main' panicked at src/app.rs:5:3:\ncalled `Option::unwrap()` on a `None` value\n"
    [t] = parse(text)
    assert t.frames[0].file == "src/app.rs" and t.frames[0].line == 5
    assert t.frames[0].function == "<panic>"


def test_no_panic_returns_empty():
    assert parse("INFO all good\n") == []
