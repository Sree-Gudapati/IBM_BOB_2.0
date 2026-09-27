from debugagent.scanner.graph import build_edges
from debugagent.scanner.languages import scan_services


def test_edges_from_compose_and_source_urls(mini_system):
    edges = build_edges(mini_system, scan_services(mini_system))
    assert set(edges["web"]) == {"billing", "orders"}   # depends_on + env URL + source URL
    assert edges["orders"] == ["inventory"]              # dict-form depends_on + application.yml
    assert edges["billing"] == ["ledger"]                # source URL only
    assert edges.get("ledger", []) == []


def test_no_self_edges(mini_system):
    (mini_system / "services/web/src/self.ts").write_text('fetch("http://web:3000/health")\n')
    assert "web" not in build_edges(mini_system, scan_services(mini_system))["web"]
