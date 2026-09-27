import pytest
from debugagent.models import Family, Frame, ParsedTrace
from debugagent.parsers.rust import parse
from debugagent.patterns.loader import DEFAULT_PATTERN_DIR, load_patterns
from debugagent.patterns.matcher import match_trace

PATS = load_patterns(DEFAULT_PATTERN_DIR)
F = (Frame("src/ledger.rs", 27, "ledger::post_entry"),)

RUST_CASES = [
    ("called `Option::unwrap()` on a `None` value", "rust.unwrap_none"),
    ("called `Result::unwrap()` on an `Err` value: ParseIntError { kind: InvalidDigit }", "rust.unwrap_err"),
    ("index out of bounds: the len is 3 but the index is 5", "rust.index_oob"),
    ("attempt to subtract with overflow", "rust.overflow"),
    ("attempt to divide by zero", "rust.divide_by_zero"),
    ("already mutably borrowed: BorrowError", "rust.refcell_borrow"),
    ("byte index 3 is not a char boundary; it is inside 'é' (bytes 2..4) of `café`", "rust.str_slice"),
    ("Cannot start a runtime from within a runtime.", "rust.nested_runtime"),
    ("called `Result::unwrap()` on an `Err` value: PoisonError { .. }", "rust.mutex_poisoned"),
    ("not yet implemented", "rust.explicit"),
    ('called `Result::unwrap()` on an `Err` value: Os { code: 111, kind: ConnectionRefused, message: "Connection refused" }', "rust.connection_refused"),
    ("called `Result::unwrap()` on an `Err` value: Elapsed(())", "rust.timeout"),
]


@pytest.mark.parametrize("msg,expected", RUST_CASES)
def test_each_rust_pattern_matches(msg, expected):
    h = match_trace(ParsedTrace(Family.RUST, "panic", msg, F), PATS)
    assert h.pattern_id == expected and 2 <= len(h.fixes) <= 3 and "#[should_panic" in h.repro_test


def test_backtrace_locations_skip_std_frames():
    from tests.parsers.test_rust import BT
    [t] = parse(BT)
    h = match_trace(t, PATS)
    assert h.locations[0].function == "ledger::post_entry"


def test_rust_patterns_meet_minimum_10():
    rust_pats = [p for p in PATS if p.family is Family.RUST]
    assert len(rust_pats) >= 10


def test_unrecognized_rust_error_is_unknown():
    h = match_trace(ParsedTrace(Family.RUST, "panic", "flux capacitor overloaded", F), PATS)
    assert h.pattern_id == "rust.unknown" and h.confidence == 0.1
