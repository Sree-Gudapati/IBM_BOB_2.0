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
