import pytest
from debugagent.detect import normalize
from debugagent.parsers.go import parse


NIL = """panic: runtime error: invalid memory address or nil pointer dereference
[signal SIGSEGV: segmentation violation code=0x1 addr=0x0 pc=0x4a1b2c]

goroutine 7 [running]:
main.(*Store).Get(0x0, {0x4c3e2a, 0x3})
\t/srv/inventory/store.go:42 +0x1c
main.handler(...)
\t/srv/inventory/main.go:18
created by net/http.(*Server).Serve in goroutine 1
\t/usr/local/go/src/net/http/server.go:3086 +0x5cb

goroutine 1 [IO wait]:
internal/poll.runtime_pollWait(0x7f, 0x72)
\t/usr/local/go/src/runtime/netpoll.go:343 +0x85
exit status 2
"""

DEADLOCK = """fatal error: all goroutines are asleep - deadlock!

goroutine 1 [chan receive]:
main.main()
\t/srv/inventory/main.go:9 +0x2d
"""


def test_runtime_error_nil_deref():
    [t] = parse(NIL)
    assert (t.error_type, t.message) == ("runtime error", "invalid memory address or nil pointer dereference")
    assert [f.function for f in t.frames] == ["main.(*Store).Get", "main.handler"]
    assert t.frames[0].file == "/srv/inventory/store.go" and t.frames[0].line == 42


def test_only_first_goroutine_and_created_by_skipped():
    [t] = parse(NIL)
    assert all("netpoll" not in f.file and "server.go" not in f.file for f in t.frames)


def test_fatal_error_deadlock():
    [t] = parse(DEADLOCK)
    assert (t.error_type, t.message) == ("fatal error", "all goroutines are asleep - deadlock")
    assert t.frames[0].function == "main.main"


def test_custom_panic_and_recovered_suffix():
    text = (
        "panic: interface conversion: interface {} is string, not int [recovered]\n\n"
        "panic: again\n\n"
        "goroutine 1 [running]:\nmain.f()\n\t/srv/a/f.go:3 +0x1\n"
    )
    [t] = parse(text)
    assert t.error_type == "panic" and t.message == "interface conversion: interface {} is string, not int"


def test_log_prefixed_panic():
    wrapped = "\n".join(
        f"2026-09-26T10:00:00Z ERROR [inventory] {ln}" for ln in DEADLOCK.splitlines()
    )
    [t] = parse(normalize(wrapped))
    assert t.frames[0].line == 9


def test_panic_word_in_log_without_goroutine_dump_is_ignored():
    assert parse("panic: this is just a log message\nINFO ok\n") == []


def test_hash_suffix_stripped_from_function_name():
    text = (
        "panic: runtime error: invalid memory address or nil pointer dereference\n\n"
        "goroutine 1 [running]:\nmain.doWork::h0123456789abcdef()\n"
        "\t/srv/app/main.go:10 +0x1\n"
    )
    [t] = parse(text)
    assert t.frames[0].function == "main.doWork"


def test_two_independent_panics():
    one = "panic: runtime error: nil pointer dereference\n\ngoroutine 1 [running]:\nmain.f()\n\t/a/b.go:1 +0x1\n"
    assert len(parse(one + "\n" + one)) == 2


def test_inline_frame_no_line_number_ignored():
    """A function line without a following file/line pair produces no frame."""
    text = (
        "panic: something bad\n\n"
        "goroutine 1 [running]:\nsome.func()\n"
        "\t/srv/app/x.go:5 +0x1\n"
        "other.func()\n"  # no following file line — should be ignored
    )
    [t] = parse(text)
    assert len(t.frames) == 1
    assert t.frames[0].function == "some.func"
