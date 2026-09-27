import pytest
from debugagent.models import Family, Frame, ParsedTrace
from debugagent.patterns.loader import DEFAULT_PATTERN_DIR, load_patterns
from debugagent.patterns.matcher import match_trace

PATS = load_patterns(DEFAULT_PATTERN_DIR)
F = (Frame("/srv/inventory/store.go", 42, "main.(*Store).Get"),)


@pytest.mark.parametrize("etype,msg,expected", [
    ("runtime error", "invalid memory address or nil pointer dereference", "go.nil_pointer"),
    ("runtime error", "index out of range [5] with length 3", "go.index_out_of_range"),
    ("runtime error", "slice bounds out of range [:5] with capacity 3", "go.slice_bounds"),
    ("runtime error", "integer divide by zero", "go.divide_by_zero"),
    ("fatal error", "all goroutines are asleep - deadlock", "go.deadlock"),
    ("fatal error", "concurrent map writes", "go.concurrent_map"),
    ("fatal error", "stack overflow", "go.stack_overflow"),
    ("fatal error", "runtime: out of memory", "go.oom"),
    ("panic", "interface conversion: interface {} is string, not int", "go.interface_conversion"),
    ("panic", "send on closed channel", "go.send_closed_channel"),
    ("panic", "close of closed channel", "go.close_closed_channel"),
    ("panic", "assignment to entry in nil map", "go.nil_map_write"),
    ("panic", "context deadline exceeded", "go.deadline_exceeded"),
    ("panic", "dial tcp 10.0.0.5:5432: connect: connection refused", "go.connection_refused"),
])
def test_each_go_pattern_matches(etype, msg, expected):
    h = match_trace(ParsedTrace(Family.GO, etype, msg, F), PATS)
    assert h.pattern_id == expected and 2 <= len(h.fixes) <= 3 and "func TestRepro_Get" in h.repro_test


def test_go_patterns_meet_minimum_10():
    go_pats = [p for p in PATS if p.family is Family.GO]
    assert len(go_pats) >= 10


def test_unrecognized_go_error_is_unknown():
    h = match_trace(ParsedTrace(Family.GO, "panic", "something totally unknown", F), PATS)
    assert h.pattern_id == "go.unknown" and h.confidence == 0.1


def test_end_to_end_nil_deref_via_parser():
    from debugagent.parsers.go import parse

    text = (
        "panic: runtime error: invalid memory address or nil pointer dereference\n\n"
        "goroutine 1 [running]:\nmain.(*Store).Get(0x0)\n"
        "\t/srv/inventory/store.go:42 +0x1c\n"
    )
    [t] = parse(text)
    h = match_trace(t, PATS)
    assert h.pattern_id == "go.nil_pointer"
    assert h.locations[0].function == "main.(*Store).Get"
