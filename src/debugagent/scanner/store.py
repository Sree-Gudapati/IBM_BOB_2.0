import json
from pathlib import Path

from debugagent.scanner.graph import build_edges
from debugagent.scanner.languages import scan_services
from debugagent.scanner.models import CodebaseMap

DEFAULT_MAP_PATH = Path(".debugagent/codebase.json")


def scan(root: Path, history: bool = True) -> CodebaseMap:
    root = Path(root).resolve()
    services = scan_services(root)
    return CodebaseMap(str(root), services, build_edges(root, services), {})


def save_map(m: CodebaseMap, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(m.to_dict(), indent=2, sort_keys=True))


def load_map(path: Path) -> CodebaseMap:
    return CodebaseMap.from_dict(json.loads(Path(path).read_text()))
