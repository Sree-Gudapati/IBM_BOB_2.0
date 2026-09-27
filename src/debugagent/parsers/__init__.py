from collections.abc import Callable

from debugagent.models import Family, ParsedTrace
from debugagent.parsers import go, jvm, node, python, rust

PARSERS: dict[Family, Callable[[str], list[ParsedTrace]]] = {
    Family.PYTHON: python.parse,
    Family.JVM: jvm.parse,
    Family.NODE: node.parse,
    Family.GO: go.parse,
    Family.RUST: rust.parse,
}
