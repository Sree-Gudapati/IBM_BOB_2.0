from debugagent.detect import normalize
from debugagent.models import Family
from debugagent.parsers.python import parse

SIMPLE = '''Traceback (most recent call last):
  File "/srv/billing/app/api.py", line 20, in handle
    invoice = build(req)
  File "/srv/billing/app/invoice.py", line 7, in build
    return cust.address.zip
           ^^^^^^^^^^^^
AttributeError: 'NoneType' object has no attribute 'zip'
'''

CHAINED = '''Traceback (most recent call last):
  File "/srv/billing/app/db.py", line 3, in get
    return rows[0]
IndexError: list index out of range

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/srv/billing/app/api.py", line 9, in handle
    raise LookupFailed("no customer") from e
app.errors.LookupFailed: no customer
'''

def test_parses_type_message_and_frames_innermost_first():
    [t] = parse(SIMPLE)
    assert t.family is Family.PYTHON
    assert t.error_type == "AttributeError"
    assert t.message == "'NoneType' object has no attribute 'zip'"
    assert t.frames[0].file == "/srv/billing/app/invoice.py" and t.frames[0].line == 7
    assert t.frames[0].function == "build"
    assert len(t.frames) == 2

# Review Focus #2: chained exceptions → innermost/original cause
def test_chained_exception_root_is_original():
    traces = parse(CHAINED)
    assert len(traces) == 1
    assert traces[0].error_type == "app.errors.LookupFailed"
    assert traces[0].root().error_type == "IndexError"

def test_two_unrelated_tracebacks_are_two_traces():
    assert len(parse(SIMPLE + "\nsome log line\n" + SIMPLE)) == 2

# Review Focus #1: prefixed log lines (indentation preserved) still parse
def test_log_prefixed_traceback_parses():
    wrapped = "\n".join(f"2026-09-26 10:00:00,123 ERROR [billing] {ln}" for ln in SIMPLE.splitlines())
    [t] = parse(normalize(wrapped))
    assert t.error_type == "AttributeError" and len(t.frames) == 2

def test_source_line_that_looks_like_a_name_is_not_an_exception():
    text = 'Traceback (most recent call last):\n  File "a.py", line 1, in f\n    Config.TIMEOUT\nKeyError: \'x\'\n'
    [t] = parse(text)
    assert t.error_type == "KeyError"

def test_no_traceback_returns_empty():
    assert parse("INFO all good\n") == []


# --- Task 2 review fixes -----------------------------------------------------

def _tb(exc: str, frame: str = '  File "/srv/app/x.py", line 5, in run\n    go()\n') -> str:
    return "Traceback (most recent call last):\n" + frame + exc + "\n"

def test_dotted_lowercase_exception_type_parses():
    [t] = parse(_tb("socket.timeout: timed out"))
    assert t.error_type == "socket.timeout" and t.message == "timed out"

def test_dotted_custom_exception_without_message_parses():
    [t] = parse(_tb("app.errors.PaymentDeclined"))
    assert t.error_type == "app.errors.PaymentDeclined" and t.message == ""

def test_indented_source_line_is_never_the_exception():
    [t] = parse(_tb("KeyError: 'a'", '  File "/a.py", line 1, in f\n    Foo: int = 3\n'))
    assert t.error_type == "KeyError"

SYNTAX = '''Traceback (most recent call last):
  File "/srv/app/main.py", line 1, in <module>
    import broken
  File "/srv/app/broken.py", line 3
    def f(
         ^
SyntaxError: '(' was never closed
'''

def test_syntax_error_innermost_frame_is_the_broken_file():
    [t] = parse(SYNTAX)
    assert t.error_type == "SyntaxError"
    assert t.frames[0].file == "/srv/app/broken.py" and t.frames[0].line == 3
    assert t.frames[0].function == "<unknown>" and len(t.frames) == 2

def test_headerless_syntax_error_parses():
    [t] = parse(SYNTAX.split("\n", 3)[3])
    assert t.error_type == "SyntaxError" and t.frames[0].file == "/srv/app/broken.py"

GROUP = '''  + Exception Group Traceback (most recent call last):
  |   File "/srv/app/main.py", line 9, in <module>
  |     run()
  | ExceptionGroup: batch failed (2 sub-exceptions)
  +-+---------------- 1 ----------------
    | Traceback (most recent call last):
    |   File "/srv/app/worker.py", line 4, in job
    |     d["k"]
    | KeyError: 'k'
    +---------------- 2 ----------------
    | Traceback (most recent call last):
    |   File "/srv/app/worker.py", line 8, in job2
    |     x.y
    | AttributeError: 'NoneType' object has no attribute 'y'
    +------------------------------------
'''

def test_exception_group_root_is_first_sub_exception():
    # Sub-exception 1 becomes the group's cause; later sub-exceptions are their own traces.
    t, second = parse(GROUP)
    assert t.short_error_type == "ExceptionGroup"
    assert t.frames[0].file == "/srv/app/main.py"
    root = t.root()
    assert root.error_type == "KeyError" and root.frames[0].file == "/srv/app/worker.py"
    assert second.error_type == "AttributeError"
