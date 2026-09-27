import json
import pytest


SAMPLE_SYSTEM_FILES = {
    "docker-compose.yml": (
        "services:\n"
        "  web:\n    build: ./services/web\n    depends_on: [orders]\n"
        "    environment:\n      BILLING_URL: http://billing:8000\n"
        "  orders:\n    build: ./services/orders\n    depends_on:\n      inventory: {condition: service_started}\n"
        "  billing:\n    build: ./services/billing\n"
        "  inventory:\n    build: ./services/inventory\n"
        "  ledger:\n    build: ./services/ledger\n"
    ),
    "services/web/package.json": json.dumps({
        "name": "@acme/web",
        "dependencies": {"express": "^4.19.0", "axios": "^1.7.0"},
    }),
    "services/web/src/api.ts": 'const ORDERS = "http://orders:8080/api";\n',
    "services/web/node_modules/axios/index.js": "// must be skipped\n",
    "services/orders/pom.xml": (
        "<project><artifactId>orders-service</artifactId><dependencies>"
        "<dependency><artifactId>spring-boot-starter-web</artifactId></dependency>"
        "<dependency><artifactId>HikariCP</artifactId></dependency>"
        "</dependencies></project>"
    ),
    "services/orders/src/main/java/com/acme/orders/pricing/Discounts.java": "package com.acme.orders.pricing;\n",
    "services/orders/src/main/resources/application.yml": "inventory:\n  url: http://inventory:9000\n",
    "services/billing/pyproject.toml": (
        '[project]\nname = "billing"\ndependencies = ["fastapi>=0.110", "requests==2.32.0"]\n'
    ),
    "services/billing/app/client.py": 'LEDGER = "http://ledger:7000"\n',
    "services/inventory/go.mod": (
        "module github.com/acme/inventory\n\ngo 1.22\n\nrequire (\n\tgithub.com/gin-gonic/gin v1.10.0\n)\n"
    ),
    "services/inventory/store.go": "package main\n",
    "services/ledger/Cargo.toml": (
        '[package]\nname = "ledger-svc"\nversion = "0.1.0"\n\n'
        '[dependencies]\naxum = "0.7"\ntokio = { version = "1", features = ["full"] }\n'
    ),
    "services/ledger/src/ledger.rs": "fn post_entry() {}\n",
}


@pytest.fixture
def mini_system(tmp_path):
    root = tmp_path / "sys"
    for rel, content in SAMPLE_SYSTEM_FILES.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return root
