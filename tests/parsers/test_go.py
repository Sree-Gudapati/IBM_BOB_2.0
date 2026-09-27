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


# --- Task 6 review fixes -----------------------------------------------------

from debugagent.detect import detect_families
from debugagent.models import Family

FATAL_DEADLOCK = ("fatal error: all goroutines are asleep - deadlock!\n\n"
            "goroutine 1 [chan receive]:\nmain.main()\n\t/srv/app/main.go:5 +0x2\n")

def test_fatal_error_survives_normalize():
    assert normalize(FATAL_DEADLOCK) == FATAL_DEADLOCK
    [t] = parse(normalize(FATAL_DEADLOCK))
    assert t.error_type == "fatal error" and t.message == "all goroutines are asleep - deadlock"

def test_log_wrapped_fatal_error():
    wrapped = "\n".join(f"2026-09-26T10:00:00Z ERROR [inv] {ln}" for ln in FATAL_DEADLOCK.splitlines())
    [t] = parse(normalize(wrapped))
    assert t.error_type == "fatal error" and t.frames[0].file == "/srv/app/main.go"

def test_gotraceback_system_header_and_frame_fields():
    text = ("panic: runtime error: integer divide by zero\n\n"
            "goroutine 1 gp=0xc000002380 m=0 mp=0x5a2b40 [running]:\n"
            "main.div(...)\n\t/srv/app/d.go:3 +0x1d fp=0xc00006ef50 sp=0xc00006ef40 pc=0x45e0fd\n")
    assert Family.GO in detect_families(text)
    [t] = parse(text)
    assert (t.frames[0].file, t.frames[0].line) == ("/srv/app/d.go", 3)

def test_frameless_runtime_failures_are_kept():
    [t] = parse("fatal error: runtime: out of memory\n")
    assert t.message == "runtime: out of memory" and t.frames == ()
    [t] = parse("panic: runtime error: invalid memory address or nil pointer dereference\n")
    assert t.error_type == "runtime error"

def test_stack_overflow_runtime_stack_section_skipped():
    text = ("runtime: goroutine stack exceeds 1000000000-byte limit\nfatal error: stack overflow\n\n"
            "runtime stack:\nruntime.throw({0x4a0f40?, 0x0?})\n\t/usr/local/go/src/runtime/panic.go:1023 +0x5c\n\n"
            "goroutine 1 [running]:\nmain.f(0x0?)\n\t/srv/app/rec.go:4 +0x3c\n...additional frames elided...\n")
    [t] = parse(text)
    assert [f.file for f in t.frames] == ["/srv/app/rec.go"]

def test_path_with_spaces():
    [t] = parse("panic: runtime error: x\n\ngoroutine 1 [running]:\nmain.main()\n\t/Users/a b/app/main.go:3 +0x1\n")
    assert t.frames[0].file == "/Users/a b/app/main.go"

@pytest.mark.parametrize("text", ["  panic: boom\n", "fatal error: x\n"])
def test_detection_variants(text):
    assert Family.GO in detect_families(text)

def test_prose_panic_not_detected():
    assert detect_families("don't panic: it's fine\n") == frozenset()
