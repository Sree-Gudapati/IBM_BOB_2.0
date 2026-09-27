from debugagent.detect import normalize
from debugagent.models import Family
from debugagent.parsers.jvm import parse

CHAINED = normalize(open("tests/data/jvm_chained.txt").read())

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
