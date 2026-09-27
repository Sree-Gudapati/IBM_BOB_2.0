from debugagent.models import Frame
from debugagent.scanner.store import load_map, save_map, scan


def test_round_trip(mini_system, tmp_path):
    m = scan(mini_system, history=False)
    save_map(m, tmp_path / "m.json")
    assert load_map(tmp_path / "m.json") == m


def test_service_for_frame_strategies(mini_system):
    m = scan(mini_system, history=False)
    assert m.service_for_frame(Frame("/srv/web/src/api.ts", 3, "handler")) == "web"
    assert m.service_for_frame(
        Frame("Discounts.java", 18, "Discounts.forName", "com.acme.orders.pricing.Discounts")
    ) == "orders"
    assert m.service_for_frame(Frame("./src/ledger.rs", 27, "ledger_svc::post_entry")) == "ledger"
    assert m.service_for_frame(
        Frame("github.com/acme/inventory/store.go", 42, "main.Get")
    ) == "inventory"
    assert m.service_for_frame(Frame("/usr/lib/other.py", 1, "f")) is None


def test_calls_is_transitive(mini_system):
    m = scan(mini_system, history=False)
    assert m.calls("web", "inventory") and not m.calls("inventory", "web")
