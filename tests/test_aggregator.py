from debugagent.models import Family
from debugagent.orchestrator import diagnose
from debugagent.scanner import scan
from debugagent.subagent import build_subagents

NODE_TIMEOUT = "AxiosError: timeout of 5000ms exceeded\n    at placeOrder (/srv/web/src/orders.ts:22:11)\n"
JAVA = open("tests/data/jvm_chained.txt").read()


# Review Focus #4: mixed multi-service input → source service wins, caller is a symptom
def test_cross_service_source_beats_symptom(mini_system):
    d = diagnose(NODE_TIMEOUT + JAVA, build_subagents(), codebase=scan(mini_system, history=False))
    assert d.top.pattern_id == "jvm.npe.helpful" and d.top.service == "orders"
    assert d.top.confidence == 0.95
    assert any("web" in e and "likely origin" in e for e in d.top.evidence)
    node = next(h for h in d.hypotheses if h.family is Family.NODE)
    assert node.service == "web" and node.confidence == 0.45
    assert "symptom" in node.evidence[0]


def test_without_map_dependency_errors_rank_below_code_errors():
    d = diagnose(NODE_TIMEOUT + JAVA, build_subagents())
    assert d.top.pattern_id == "jvm.npe.helpful" and d.top.service is None
    node = next(h for h in d.hypotheses if h.family is Family.NODE)
    assert node.confidence == 0.6 and "usually a symptom" in node.evidence[0]


def test_lone_dependency_error_is_untouched(mini_system):
    d = diagnose(NODE_TIMEOUT, build_subagents(), codebase=scan(mini_system, history=False))
    assert d.top.pattern_id == "node.timeout" and d.top.confidence == 0.75 and d.top.evidence == ()


def test_unrelated_services_are_not_linked(mini_system):
    # ledger does not call orders → no symptom demotion
    rust_timeout = (
        "thread 'main' panicked at src/ledger.rs:3:5:\n"
        "called `Result::unwrap()` on an `Err` value: Elapsed(())\nstack backtrace:\n"
        "   0: ledger_svc::post\n             at ./src/ledger.rs:3:5\n"
    )
    d = diagnose(rust_timeout + JAVA, build_subagents(), codebase=scan(mini_system, history=False))
    rust = next(h for h in d.hypotheses if h.family is Family.RUST)
    assert rust.service == "ledger" and rust.confidence == 0.86


def test_attribution_for_python(mini_system):
    d = diagnose(
        open("tests/data/python_none.txt").read(),
        build_subagents(),
        codebase=scan(mini_system, history=False),
    )
    assert d.top.service == "billing"


def test_history_boost_for_recurring_weakness(mini_system):
    cb = scan(mini_system, history=False)
    cb.history["billing"] = {"null": 4}
    d = diagnose(open("tests/data/python_none.txt").read(), build_subagents(), codebase=cb)
    assert d.top.service == "billing" and d.top.confidence == 0.9
    assert any("4 past fix commits tagged 'null'" in e for e in d.top.evidence)


def test_history_below_threshold_no_boost(mini_system):
    cb = scan(mini_system, history=False)
    cb.history["billing"] = {"null": 2}
    d = diagnose(open("tests/data/python_none.txt").read(), build_subagents(), codebase=cb)
    assert d.top.confidence == 0.85
