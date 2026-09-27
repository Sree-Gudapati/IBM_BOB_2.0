from pathlib import Path

from debugagent.detect import normalize
from debugagent.models import Family
from debugagent.parsers.jvm import parse

CHAINED = normalize(Path("tests/data/jvm_chained.txt").read_text())

def test_outer_and_chain():
    [t] = parse(CHAINED)
    assert t.family is Family.JVM
    assert t.error_type == "org.springframework.web.util.NestedServletException"
    assert t.cause.error_type == "java.lang.IllegalStateException"
    root = t.root()
    assert root.error_type == "java.lang.NullPointerException"
    assert root.message.startswith('Cannot invoke "String.length()"')

def test_frames_innermost_first_with_module_and_function():
    root = parse(CHAINED)[0].root()
    f = root.frames[0]
    assert (f.file, f.line, f.function, f.module) == (
        "Discounts.java", 18, "Discounts.forName", "com.acme.orders.pricing.Discounts")

def test_java_base_module_prefix_is_stripped():
    root = parse(CHAINED)[0].root()
    assert root.frames[2].module == "java.util.Optional"

def test_native_and_unknown_source_frames():
    text = ('Exception in thread "main" java.lang.StackOverflowError\n'
            "\tat java.lang.Object.hashCode(Native Method)\n"
            "\tat com.acme.Tree.walk(Unknown Source)\n")
    [t] = parse(text)
    assert t.error_type == "java.lang.StackOverflowError" and t.message == ""
    assert t.frames[0].line is None and t.frames[1].function == "Tree.walk"

def test_kotlin_and_scala_frames():
    text = ("java.lang.ClassCastException: class A cannot be cast to class B\n"
            "\tat com.acme.Svc.run(Svc.kt:3)\n\tat com.acme.Job.go(Job.scala:9)\n")
    [t] = parse(text)
    assert [f.file for f in t.frames] == ["Svc.kt", "Job.scala"]

def test_two_independent_traces():
    one = "java.lang.IllegalArgumentException: bad\n\tat com.acme.A.b(A.java:1)\n"
    assert len(parse(one + "INFO something\n" + one)) == 2

def test_exception_name_in_plain_log_line_without_frames_is_ignored():
    assert parse("WARN retrying after java.io.IOException: reset\nINFO ok\n") == []


# --- Task 4 review fixes -----------------------------------------------------
import pytest

from debugagent.detect import detect_families

APP = "\tat com.acme.orders.OrderService.place(OrderService.java:42)\n"

def test_frameless_oom_with_thread_header_is_kept():
    [t] = parse('Exception in thread "main" java.lang.OutOfMemoryError: Java heap space\n')
    assert t.error_type == "java.lang.OutOfMemoryError" and t.frames == ()

def test_frameless_dotted_exception_kept_and_detected():
    text = "java.lang.IllegalStateException: x\n\t... 3 more\n"
    assert Family.JVM in detect_families(text)
    [t] = parse(text)
    assert t.error_type == "java.lang.IllegalStateException"

def test_frameless_undotted_name_is_not_a_jvm_trace():
    assert parse("KeyError: 1\n") == []

def test_multiline_message_keeps_frames_and_joins_message():
    text = ("com.fasterxml.jackson.databind.exc.MismatchedInputException: Cannot deserialize\n"
            ' at [Source: (String)"x"; line: 1, column: 6]\n' + APP)
    [t] = parse(text)
    assert len(t.frames) == 1
    assert t.message == 'Cannot deserialize\nat [Source: (String)"x"; line: 1, column: 6]'

def test_trailing_log_lines_do_not_leak_into_frameless_message():
    [t] = parse("java.lang.OutOfMemoryError: Java heap space\nINFO next\n")
    assert t.message == "Java heap space"

@pytest.mark.parametrize("line,module", [
    ("\tat java.base@17.0.2/java.util.Objects.requireNonNull(Objects.java:209)", "java.util.Objects"),
    ("\tat app//com.acme.Svc.run(Svc.java:5)", "com.acme.Svc"),
    ("\tat com.acme.Svc$$Lambda$14/0x0000000800066840.apply(Unknown Source)", "com.acme.Svc$$Lambda$14"),
])
def test_classloader_module_and_hidden_class_frames(line, module):
    [t] = parse("java.lang.IllegalStateException: x\n" + line + "\n")
    assert t.frames[0].module == module
    assert Family.JVM in detect_families(line)

def test_native_method_only_trace_detected():
    assert Family.JVM in detect_families("java.lang.X: y\n\tat jdk.internal.X.y(Native Method)\n")

SUPPRESSED = (
    "java.io.IOException: main\n" + APP +
    "\tSuppressed: java.lang.IllegalStateException: close failed\n"
    "\t\tat com.acme.R.close(R.java:9)\n"
    "\t\tCaused by: java.lang.NullPointerException: inner\n"
    "\t\t\tat com.acme.R.x(R.java:1)\n"
)

def test_suppressed_cause_is_not_in_main_chain():
    [t] = parse(SUPPRESSED)
    assert t.root() is t and t.error_type == "java.io.IOException"

def test_frames_after_suppressed_block_resume():
    [t] = parse(SUPPRESSED + "\tat com.acme.orders.Tail.t(Tail.java:1)\n"
                "Caused by: java.net.ConnectException: Connection refused\n\tat com.acme.C.c(C.java:1)\n")
    assert [f.file for f in t.frames] == ["OrderService.java", "Tail.java"]
    assert t.root().error_type == "java.net.ConnectException"

@pytest.mark.parametrize("header", ["com.acme.PaymentDeclined: card", "MyException: x"])
def test_custom_exception_names_parse(header):
    [t] = parse(header + "\n" + APP)
    assert t.error_type == header.split(":")[0]
