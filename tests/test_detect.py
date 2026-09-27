from debugagent.detect import detect_families, normalize, MAX_INPUT_CHARS
from debugagent.models import Family

PY = 'Traceback (most recent call last):\n  File "app/svc.py", line 3, in run\n    x.y\nAttributeError: \'NoneType\' object has no attribute \'y\'\n'
JAVA = 'Exception in thread "main" java.lang.NullPointerException\n\tat com.acme.Orders.place(Orders.java:42)\n'
NODE = "TypeError: Cannot read properties of undefined (reading 'id')\n    at handler (/srv/web/src/api.ts:10:5)\n"
GO = "panic: runtime error: invalid memory address or nil pointer dereference\n\ngoroutine 1 [running]:\nmain.main()\n\t/srv/inv/main.go:9 +0x1d\n"
RUST = "thread 'main' panicked at src/main.rs:4:37:\ncalled `Option::unwrap()` on a `None` value\n"

def test_detects_each_family():
    assert detect_families(PY) == {Family.PYTHON}
    assert detect_families(JAVA) == {Family.JVM}
    assert detect_families(NODE) == {Family.NODE}
    assert detect_families(GO) == {Family.GO}
    assert detect_families(RUST) == {Family.RUST}

def test_detects_mixed_input():
    assert detect_families(NODE + "\n" + JAVA) == {Family.NODE, Family.JVM}

def test_empty_and_garbage_detect_nothing():
    assert detect_families("") == frozenset()
    assert detect_families("\x00\xff binary junk \x01") == frozenset()

# Review Focus #1: log-wrapped traces parse like clean ones
def test_normalize_strips_timestamp_level_service_prefix_ansi_crlf():
    wrapped = "\r\n".join(
        f"2026-09-26T10:00:00.123Z ERROR [billing] \x1b[31m{ln}\x1b[0m" for ln in PY.splitlines()
    )
    out = normalize(wrapped)
    assert "Traceback (most recent call last):" in out
    assert "AttributeError: 'NoneType' object has no attribute 'y'" in out
    assert "\x1b" not in out and "\r" not in out
    assert detect_families(out) == {Family.PYTHON}

def test_normalize_keeps_tail_of_oversized_input():
    big = "x" * (MAX_INPUT_CHARS + 10) + PY
    out = normalize(big)
    assert len(out) <= MAX_INPUT_CHARS
    assert "AttributeError: 'NoneType' object has no attribute 'y'" in out
