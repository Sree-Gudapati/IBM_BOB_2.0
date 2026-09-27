from pathlib import Path

import pytest

from debugagent.models import Family, Frame, ParsedTrace
from debugagent.patterns.loader import DEFAULT_PATTERN_DIR, load_patterns
from debugagent.patterns.matcher import match_trace

PATS = load_patterns(DEFAULT_PATTERN_DIR)
F = (Frame("Orders.java", 10, "Orders.place", "com.acme.Orders"),)

@pytest.mark.parametrize("etype,msg,expected", [
    ("java.lang.NullPointerException", 'Cannot invoke "String.length()" because "n" is null', "jvm.npe.helpful"),
    ("java.lang.NullPointerException", "", "jvm.npe"),
    ("java.util.NoSuchElementException", "No value present", "jvm.optional_get_empty"),
    ("java.lang.ClassCastException", "class A cannot be cast to class B", "jvm.class_cast"),
    ("java.sql.SQLTransientConnectionException", "HikariPool-1 - Connection is not available, request timed out after 30000ms.", "jvm.pool_exhausted"),
    ("java.net.SocketTimeoutException", "Read timed out", "jvm.socket_timeout"),
    ("java.net.ConnectException", "Connection refused", "jvm.connection_refused"),
    ("java.lang.OutOfMemoryError", "Java heap space", "jvm.oom"),
    ("java.util.ConcurrentModificationException", "", "jvm.concurrent_modification"),
    ("java.lang.StackOverflowError", "", "jvm.stack_overflow"),
    ("org.springframework.beans.factory.NoSuchBeanDefinitionException", "No qualifying bean of type 'X'", "jvm.spring_missing_bean"),
    ("java.time.format.DateTimeParseException", "Text '2026-09-26T10:00' could not be parsed", "jvm.datetime_parse"),
    ("java.lang.ArrayIndexOutOfBoundsException", "Index 3 out of bounds for length 3", "jvm.index_out_of_bounds"),
    ("java.lang.IllegalStateException", "not started", "jvm.illegal_argument_state"),
])
def test_each_jvm_pattern_matches(etype, msg, expected):
    h = match_trace(ParsedTrace(Family.JVM, etype, msg, F), PATS)
    assert h.pattern_id == expected and 2 <= len(h.fixes) <= 3 and "@Test" in h.repro_test

# Review Focus #2 for JVM: wrapper exceptions resolve to the innermost cause
def test_chained_fixture_diagnoses_root_npe():
    from debugagent.detect import normalize
    from debugagent.parsers.jvm import parse
    [t] = parse(normalize(Path("tests/data/jvm_chained.txt").read_text()))
    h = match_trace(t, PATS)
    assert h.pattern_id == "jvm.npe.helpful"
    assert h.locations[0].function == "Discounts.forName"   # library frames skipped


def test_kotlin_npe_matches_npe_pattern():
    from debugagent.orchestrator import diagnose
    from debugagent.subagent import build_subagents
    d = diagnose("kotlin.KotlinNullPointerException\n\tat com.a.MainKt.main(Main.kt:3)\n", build_subagents())
    assert d.top.pattern_id == "jvm.npe"

def test_frameless_oom_diagnosed():
    from debugagent.orchestrator import diagnose
    from debugagent.subagent import build_subagents
    d = diagnose('Exception in thread "main" java.lang.OutOfMemoryError: Java heap space\n', build_subagents())
    assert d.top.pattern_id == "jvm.oom"
