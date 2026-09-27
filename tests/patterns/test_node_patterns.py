from pathlib import Path

import pytest

from debugagent.models import Family, Frame, ParsedTrace
from debugagent.orchestrator import diagnose
from debugagent.parsers.node import parse
from debugagent.patterns.loader import DEFAULT_PATTERN_DIR, load_patterns
from debugagent.patterns.matcher import match_trace
from debugagent.subagent import build_subagents

PATS = load_patterns(DEFAULT_PATTERN_DIR)
F = (Frame("/srv/web/src/api.ts", 3, "handler"),)

@pytest.mark.parametrize("etype,msg,expected", [
    ("TypeError", "Cannot read properties of undefined (reading 'id')", "node.undefined_property"),
    ("TypeError", "client.fetchUser is not a function", "node.not_a_function"),
    ("ReferenceError", "window is not defined", "node.reference_error"),
    ("Error", "connect ECONNREFUSED 10.0.3.7:8080", "node.econnrefused"),
    ("AxiosError", "timeout of 5000ms exceeded", "node.timeout"),
    ("Error", "socket hang up", "node.econnreset"),
    ("Error", "Cannot find module 'express'", "node.module_not_found"),
    ("SyntaxError", "Unexpected token '<', \"<!DOCTYPE \"... is not valid JSON", "node.json_parse"),
    ("RangeError", "Maximum call stack size exceeded", "node.max_call_stack"),
    ("Error", "listen EADDRINUSE: address already in use :::3000", "node.eaddrinuse"),
    ("FatalError", "Reached heap limit Allocation failed - JavaScript heap out of memory", "node.heap_oom"),
    ("Error", "[ERR_UNHANDLED_REJECTION] This error originated either by throwing inside of an async function",
     "node.unhandled_rejection"),
])
def test_each_node_pattern_matches(etype, msg, expected):
    h = match_trace(ParsedTrace(Family.NODE, etype, msg, F), PATS)
    assert h.pattern_id == expected and 2 <= len(h.fixes) <= 3 and h.repro_test

def test_cause_fixture_diagnoses_root_econnrefused():
    [t] = parse(Path("tests/data/node_cause.txt").read_text())
    assert match_trace(t, PATS).pattern_id == "node.econnrefused"

def test_at_least_ten_node_patterns():
    assert sum(p.family is Family.NODE for p in PATS) >= 10

def test_unrecognized_node_error_is_low_confidence_unknown():
    h = match_trace(ParsedTrace(Family.NODE, "TypeError", "x.map is weird", F), PATS)
    assert h.pattern_id == "node.unknown" and h.confidence == 0.1

def test_end_to_end_heap_oom_and_rejection():
    s = build_subagents()
    oom = "FATAL ERROR: Reached heap limit Allocation failed - JavaScript heap out of memory\n"
    assert diagnose(oom, s).top.pattern_id == "node.heap_oom"
    rej = ('[UnhandledPromiseRejection: This error originated either by throwing inside of an async '
           'function without a catch block. The promise rejected with the reason "oops".] {\n'
           "  code: 'ERR_UNHANDLED_REJECTION'\n}\n")
    assert diagnose(rej, s).top.pattern_id == "node.unhandled_rejection"

def test_node_repro_is_a_jest_test():
    [t] = parse(Path("tests/data/node_cause.txt").read_text())
    h = match_trace(t, PATS)
    assert 'test("repro' in h.repro_test and "toThrow" in h.repro_test


@pytest.mark.parametrize("etype,msg,expected", [
    ("TypeError", "Cannot read property 'id' of undefined", "node.undefined_property"),   # Node <16 wording
    ("DOMException", "[TimeoutError] The operation was aborted due to timeout", "node.timeout"),
])
def test_legacy_and_dom_exception_variants(etype, msg, expected):
    assert match_trace(ParsedTrace(Family.NODE, etype, msg, F), PATS).pattern_id == expected

def test_dom_exception_header_parses_bracket_name():
    [t] = parse("DOMException [TimeoutError]: The operation was aborted due to timeout\n"
                "    at handler (/srv/web/src/api.ts:10:5)\n")
    assert t.error_type == "DOMException" and t.message.startswith("[TimeoutError] ")
