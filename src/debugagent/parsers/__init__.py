from collections.abc import Callable

from debugagent.models import Family, ParsedTrace
from debugagent.parsers import jvm, python

PARSERS: dict[Family, Callable[[str], list[ParsedTrace]]] = {
    Family.PYTHON: python.parse,
    Family.JVM: jvm.parse,
}
