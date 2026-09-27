from __future__ import annotations

from dataclasses import asdict, dataclass, field
from debugagent.models import Family, Frame


@dataclass
class ServiceInfo:
    name: str
    path: str
    family: Family
    frameworks: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    packages: list[str] = field(default_factory=list)


@dataclass
class CodebaseMap:
    root: str
    services: dict[str, ServiceInfo]
    edges: dict[str, list[str]]
    history: dict[str, dict[str, int]] = field(default_factory=dict)

    def service_for_frame(self, frame: Frame) -> str | None:
        segments = set(frame.file.replace("\\", "/").split("/"))
        norm_file = frame.file.replace("\\", "/")
        for name, s in self.services.items():
            for alias in s.aliases:
                if alias in segments or ("/" in alias and alias + "/" in norm_file):
                    return name
            if frame.module and s.packages:
                pkg = frame.module.rsplit(".", 1)[0]
                if any(pkg == p or pkg.startswith(p + ".") for p in s.packages):
                    return name
            crate = frame.function.split("::", 1)[0] if "::" in frame.function else None
            if crate and crate in s.aliases:
                return name
        return None

    def calls(self, a: str, b: str) -> bool:
        seen, stack = set(), list(self.edges.get(a, []))
        while stack:
            n = stack.pop()
            if n == b:
                return True
            if n not in seen:
                seen.add(n)
                stack.extend(self.edges.get(n, []))
        return False

    def to_dict(self) -> dict:
        d = asdict(self)
        for s in d["services"].values():
            s["family"] = s["family"].value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> CodebaseMap:
        services = {
            k: ServiceInfo(**{**v, "family": Family(v["family"])})
            for k, v in d["services"].items()
        }
        return cls(d["root"], services, d["edges"], d.get("history", {}))
