from debugagent.models import Family
from debugagent.scanner.languages import scan_services


def test_finds_five_services_with_families(mini_system):
    s = scan_services(mini_system)
    assert {k: v.family for k, v in s.items()} == {
        "web": Family.NODE,
        "orders": Family.JVM,
        "billing": Family.PYTHON,
        "inventory": Family.GO,
        "ledger": Family.RUST,
    }
    assert s["web"].path == "services/web"


def test_frameworks_dependencies_aliases_packages(mini_system):
    s = scan_services(mini_system)
    assert "express" in s["web"].frameworks and "axios" in s["web"].dependencies
    assert "spring" in s["orders"].frameworks and "HikariCP" in s["orders"].dependencies
    assert "fastapi" in s["billing"].frameworks and "requests" in s["billing"].dependencies
    assert "gin" in s["inventory"].frameworks
    assert {"axum", "tokio"} <= set(s["ledger"].frameworks)
    assert "ledger_svc" in s["ledger"].aliases and "ledger-svc" in s["ledger"].aliases
    assert "github.com/acme/inventory" in s["inventory"].aliases
    assert "com.acme.orders.pricing" in s["orders"].packages


def test_skips_vendored_dirs(mini_system):
    assert all("node_modules" not in v.path for v in scan_services(mini_system).values())


def test_empty_dir_has_no_services(tmp_path):
    assert scan_services(tmp_path) == {}


def test_single_service_repo_root(tmp_path):
    (tmp_path / "go.mod").write_text("module example.com/solo\n")
    s = scan_services(tmp_path)
    assert list(s) == [tmp_path.name] and s[tmp_path.name].path == "."
