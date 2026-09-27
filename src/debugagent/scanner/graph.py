import re
from pathlib import Path

import yaml

from debugagent.scanner.languages import SKIP_DIRS
from debugagent.scanner.models import ServiceInfo

TEXT_EXT = {
    ".py", ".java", ".kt", ".scala", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".go", ".rs",
    ".yml", ".yaml", ".properties", ".env", ".json", ".toml", ".conf",
}
MAX_FILE_BYTES = 256_000
_URL_HOST = re.compile(
    r"\b(?:https?|grpc|amqp|redis|postgres(?:ql)?)://([a-z0-9][a-z0-9-]*)(?=[:/\"'\s]|$)", re.I
)
_K8S_HOST = re.compile(r"\b([a-z0-9][a-z0-9-]*)\.[a-z0-9-]+\.svc\b")
COMPOSE_FILES = ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")


def _resolver(services: dict[str, ServiceInfo]) -> dict[str, str]:
    alias_to = {}
    for name, s in services.items():
        for a in s.aliases:
            alias_to[a.lower()] = name
    return alias_to


def _iter_text_files(d: Path):
    for p in d.rglob("*"):
        if any(part in SKIP_DIRS for part in p.relative_to(d).parts):
            continue
        if p.is_file() and p.suffix in TEXT_EXT and p.stat().st_size <= MAX_FILE_BYTES:
            yield p


def build_edges(root: Path, services: dict[str, ServiceInfo]) -> dict[str, list[str]]:
    root = Path(root)
    alias_to = _resolver(services)
    edges: dict[str, set[str]] = {n: set() for n in services}

    def add(src: str | None, host: str) -> None:
        dst = alias_to.get(host.lower())
        if src and dst and dst != src:
            edges[src].add(dst)

    for cf in COMPOSE_FILES:
        f = root / cf
        if f.is_file():
            data = yaml.safe_load(f.read_text()) or {}
            for cname, spec in (data.get("services") or {}).items():
                src = alias_to.get(cname.lower())
                deps = spec.get("depends_on") or []
                for dep in (deps if isinstance(deps, list) else list(deps)):
                    add(src, dep)
                env = spec.get("environment") or {}
                values = (
                    env.values() if isinstance(env, dict)
                    else [e.split("=", 1)[-1] for e in env]
                )
                for v in values:
                    for host in _URL_HOST.findall(str(v)):
                        add(src, host)

    for name, s in services.items():
        svc_path = root / s.path
        if svc_path.is_dir():
            for p in _iter_text_files(svc_path):
                try:
                    text = p.read_text(errors="replace")
                except OSError:
                    continue
                for host in _URL_HOST.findall(text) + _K8S_HOST.findall(text):
                    add(name, host)
    return {k: sorted(v) for k, v in edges.items()}
