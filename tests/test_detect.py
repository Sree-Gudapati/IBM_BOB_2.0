from debugagent.detect import MAX_INPUT_CHARS, detect_families, normalize
from debugagent.models import Family

PY = 'Traceback (most recent call last):\n  File "app/svc.py", line 3, in run\n    x.y\nAttributeError: \'NoneType\' object has no attribute \'y\'\n'
JAVA = 'Exception in thread "main" java.lang.NullPointerException\n\tat com.acme.Orders.place(Orders.java:42)\n'
NODE = "TypeError: Cannot read properties of undefined (reading 'id')\n    at handler (/srv/web/src/api.ts:10:5)\n"
GO = "panic: runtime error: invalid memory address or nil pointer dereference\n\ngoroutine 1 [running]:\nmain.main()\n\t/srv/inv/main.go:9 +0x1d\n"
RUST = "thread 'main' panicked at src/main.rs:4:37:\ncalled `Option::unwrap()` on a `None` value\n"

# Node ECONNREFUSED trace containing only node: internal frames (no .js/.ts extension)
NODE_INTERNAL = (
    "Error: connect ECONNREFUSED 127.0.0.1:5432\n"
    "    at TCPConnectWrap.afterConnect [as oncomplete] (node:net:1555:16)\n"
    "    at node:internal/stream_base_commons:183:27\n"
)


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

# Fix 1: normalize() must preserve payload indentation after stripping log prefix
def test_normalize_preserves_indentation_after_prefix_strip():
    """'  File "app/svc.py"' indentation must survive prefix stripping."""
    wrapped = "\n".join(
        f"2026-09-26T10:00:00Z ERROR [billing] {ln}" for ln in PY.splitlines()
    )
    out = normalize(wrapped)
    # Exact line equality: the whole prefix is gone AND indentation survives
    assert out.splitlines() == PY.splitlines()
    assert detect_families(out) == {Family.PYTHON}


def test_normalize_preserves_tab_indentation_after_prefix_strip():
    line = "\tat com.acme.Orders.place(Orders.java:42)"
    assert normalize(f"2026-09-26T10:00:00Z ERROR [svc] {line}") == line


def test_normalize_strips_lowercase_and_uppercase_colon_levels():
    assert normalize("2026-09-26T10:00:00Z error [svc] x") == "x"
    assert normalize("ERROR: Traceback (most recent call last):") == (
        "Traceback (most recent call last):"
    )


def test_normalize_never_eats_payload_error_type():
    for s in ("Error: boom", "Warning: x", "Error: connect ECONNREFUSED 127.0.0.1:5432"):
        assert normalize(s) == s
    assert normalize("2026-09-26T10:00:00Z ERROR [web] Error: boom") == "Error: boom"

# Fix 2: Node ECONNREFUSED traces with only node: internal frames must be detected
def test_detects_node_internal_frames():
    """node:net and node:internal/... frames (no extension) must count as Node."""
    assert detect_families(NODE_INTERNAL) == {Family.NODE}

# Fix 2 (Review Focus #4 prerequisite): mixed Node+Java log detects both families
def test_detects_node_internal_plus_java():
    assert detect_families(NODE_INTERNAL + "\n" + JAVA) == {Family.NODE, Family.JVM}
