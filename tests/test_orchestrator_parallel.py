import time

from debugagent.models import Family
from debugagent.orchestrator import diagnose
from debugagent.subagent import LanguageSubagent, build_subagents

PY = open("tests/data/python_none.txt").read()
JAVA = open("tests/data/jvm_chained.txt").read()
NODE = open("tests/data/node_cause.txt").read()
GO = "fatal error: all goroutines are asleep - deadlock!\n\ngoroutine 1 [chan receive]:\nmain.main()\n\t/srv/inventory/main.go:9 +0x2d\n"
RUST = "thread 'main' panicked at src/ledger.rs:27:18:\ncalled `Option::unwrap()` on a `None` value\n"


def test_all_five_families_in_one_input():
    d = diagnose("\n".join([PY, JAVA, NODE, GO, RUST]), build_subagents())
    assert d.families == set(Family)
    ids = {h.pattern_id for h in d.hypotheses}
    assert {"python.attribute_error.none_type", "jvm.npe.helpful", "node.econnrefused",
            "go.deadlock", "rust.unwrap_none"} <= ids
    assert {fam for fam, _ in d.timings} == {f.value for f in Family}


# Review Focus #5: a crashing or hanging subagent must not sink the others
def test_crashing_subagent_is_isolated():
    subs = build_subagents()

    def boom(_text):
        raise RuntimeError("parser exploded")

    subs[Family.GO] = LanguageSubagent(Family.GO, boom, [])
    d = diagnose(PY + "\n" + GO, subs)
    assert d.top.pattern_id == "python.attribute_error.none_type"
    assert any("go subagent failed: RuntimeError: parser exploded" in n for n in d.notes)


def test_hanging_subagent_times_out_quickly():
    subs = build_subagents()
    subs[Family.RUST] = LanguageSubagent(Family.RUST, lambda _t: time.sleep(10) or [], [])
    t0 = time.perf_counter()
    d = diagnose(PY + "\n" + RUST, subs, timeout_s=0.3)
    assert time.perf_counter() - t0 < 1.0
    assert d.top.pattern_id == "python.attribute_error.none_type"
    assert any("rust subagent timed out after 0.3s" in n for n in d.notes)


def test_subagents_run_concurrently():
    subs = build_subagents()

    def slow(fam):
        return LanguageSubagent(fam, lambda _t: time.sleep(0.4) or [], [])

    subs[Family.GO], subs[Family.RUST] = slow(Family.GO), slow(Family.RUST)
    t0 = time.perf_counter()
    diagnose(GO + "\n" + RUST, subs)
    assert time.perf_counter() - t0 < 0.7  # sequential would be >= 0.8


def test_timings_recorded_for_completed_subagents():
    d = diagnose(PY, build_subagents())
    assert any(fam == "python" for fam, _ in d.timings)
    assert all(secs >= 0 for _, secs in d.timings)
