import json
import re
import tomllib
from pathlib import Path

from debugagent.models import Family
from debugagent.scanner.models import ServiceInfo

SKIP_DIRS = {
    ".git", "node_modules", "target", "build", "dist", "vendor",
    ".venv", "venv", "__pycache__", ".gradle", ".idea", ".debugagent",
    ".next", "out",
}
MANIFESTS: list[tuple[str, Family]] = [
    ("pom.xml", Family.JVM),
    ("build.gradle.kts", Family.JVM),
    ("build.gradle", Family.JVM),
    ("build.sbt", Family.JVM),
    ("go.mod", Family.GO),
    ("Cargo.toml", Family.RUST),
    ("package.json", Family.NODE),
    ("pyproject.toml", Family.PYTHON),
    ("setup.py", Family.PYTHON),
    ("requirements.txt", Family.PYTHON),
]
FRAMEWORKS = {
    "spring-boot": "spring",
    "quarkus": "quarkus",
    "micronaut": "micronaut",
    "ktor": "ktor",
    "django": "django",
    "flask": "flask",
    "fastapi": "fastapi",
    "celery": "celery",
    '"express"': "express",
    "@nestjs/core": "nestjs",
    '"fastify"': "fastify",
    '"next"': "next",
    "gin-gonic/gin": "gin",
    "labstack/echo": "echo",
    "gofiber/fiber": "fiber",
    "grpc": "grpc",
    "actix-web": "actix-web",
    "axum": "axum",
    "tokio": "tokio",
    "rocket": "rocket",
}
MAX_DEPTH = 4


def _dep_names(manifest: Path, family: Family) -> tuple[list[str], list[str]]:
    """Return (dependency names, extra aliases) parsed from a manifest."""
    text = manifest.read_text(errors="replace")
    name = manifest.name
    deps: list[str] = []
    aliases: list[str] = []
    if name == "package.json":
        try:
            data = json.loads(text or "{}")
        except json.JSONDecodeError:
            data = {}
        deps = sorted({**data.get("dependencies", {}), **data.get("devDependencies", {})})
        if data.get("name"):
            aliases += [data["name"], data["name"].rsplit("/", 1)[-1]]
    elif name == "pyproject.toml":
        try:
            data = tomllib.loads(text)
        except Exception:
            data = {}
        proj = data.get("project", {})
        raw = proj.get("dependencies", []) + list(
            data.get("tool", {}).get("poetry", {}).get("dependencies", {})
        )
        deps = sorted({re.split(r"[<>=~!;\[ ]", d, maxsplit=1)[0] for d in raw if d and d != "python"})
        if proj.get("name"):
            aliases.append(proj["name"])
    elif name == "requirements.txt":
        deps = sorted({
            re.split(r"[<>=~!;\[ ]", ln.strip(), 1)[0]
            for ln in text.splitlines()
            if ln.strip() and not ln.startswith(("#", "-"))
        })
    elif name == "go.mod":
        m = re.search(r"^module\s+(\S+)", text, re.M)
        if m:
            aliases += [m[1], m[1].rsplit("/", 1)[-1]]
        deps = sorted(set(re.findall(r"^\s*([\w.-]+\.[\w.-]+/\S+)\s+v", text, re.M)))
    elif name == "Cargo.toml":
        try:
            data = tomllib.loads(text)
        except Exception:
            data = {}
        deps = sorted(data.get("dependencies", {}))
        pkg = data.get("package", {}).get("name")
        if pkg:
            aliases += [pkg, pkg.replace("-", "_")]
    elif name == "pom.xml":
        arts = re.findall(r"<artifactId>([^<]+)</artifactId>", text)
        if arts:
            aliases.append(arts[0])
        deps = sorted(set(arts[1:]))
    elif name.startswith("build.gradle") or name == "build.sbt":
        deps = sorted(set(re.findall(r"""["'][\w.-]+[:%]\s*"?([\w.-]+)"?\s*[:%]""", text)))
    return deps, aliases


def _jvm_packages(service_dir: Path) -> list[str]:
    pkgs = set()
    for lang in ("java", "kotlin", "scala"):
        base = service_dir / "src" / "main" / lang
        if base.is_dir():
            for f in base.rglob("*"):
                if f.suffix in (".java", ".kt", ".scala"):
                    pkgs.add(".".join(f.parent.relative_to(base).parts))
    return sorted(p for p in pkgs if p)


def detect_service(d: Path, root: Path) -> ServiceInfo | None:
    for fname, family in MANIFESTS:
        manifest = d / fname
        if manifest.is_file():
            deps, aliases = _dep_names(manifest, family)
            lowered = manifest.read_text(errors="replace").lower()
            frameworks = sorted({label for needle, label in FRAMEWORKS.items() if needle in lowered})
            name = d.name if d != root else root.name
            rel = d.relative_to(root).as_posix() if d != root else "."
            return ServiceInfo(
                name=name,
                path=rel,
                family=family,
                frameworks=frameworks,
                dependencies=deps,
                aliases=sorted({name, *aliases}),
                packages=_jvm_packages(d) if family is Family.JVM else [],
            )
    return None


def scan_services(root: Path) -> dict[str, ServiceInfo]:
    root = Path(root)
    found: dict[str, ServiceInfo] = {}
    frontier = (
        [(p, 1) for p in sorted(root.iterdir()) if p.is_dir() and p.name not in SKIP_DIRS]
        if root.is_dir()
        else []
    )
    while frontier:
        d, depth = frontier.pop(0)
        svc = detect_service(d, root)
        if svc:
            found.setdefault(svc.name, svc)
            continue  # don't descend into a service
        if depth < MAX_DEPTH:
            frontier += [
                (p, depth + 1)
                for p in sorted(d.iterdir())
                if p.is_dir() and p.name not in SKIP_DIRS
            ]
    if not found and root.is_dir():
        svc = detect_service(root, root)
        if svc:
            found[svc.name] = svc
    return found
