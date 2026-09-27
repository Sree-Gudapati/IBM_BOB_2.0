import pytest

from debugagent.models import Family
from debugagent.patterns.loader import DEFAULT_PATTERN_DIR, PatternError, load_patterns

GOOD = """
id: python.test.thing
family: python
error_type: KeyError
category: code
root_cause: Missing key.
base_confidence: 0.7
fixes:
  - {summary: Use .get(), tradeoff: May hide bad data}
  - {summary: Validate schema, tradeoff: More code}
tags: [schema]
"""

def test_loads_valid_pattern_and_defaults_repro(tmp_path):
    (tmp_path / "a.yaml").write_text(GOOD)
    [p] = load_patterns(tmp_path)
    assert p.id == "python.test.thing" and p.family is Family.PYTHON
    assert p.error_type.fullmatch("KeyError")
    assert p.message_regex is None and len(p.fixes) == 2
    assert "pytest" in p.repro_template          # family default applied
    assert p.source == "manual"                  # non-default dir → manual

@pytest.mark.parametrize("mutation,needle", [
    (lambda s: s.replace("root_cause: Missing key.\n", ""), "missing required key 'root_cause'"),
    (lambda s: s.replace("base_confidence: 0.7", "base_confidence: 1.5"), "base_confidence"),
    (lambda s: s + "message_regex: '([unclosed'\n", "bad message_regex"),
    (lambda s: s.replace("  - {summary: Validate schema, tradeoff: More code}\n", ""), "2-3 fixes"),
])
def test_invalid_pattern_errors_name_the_file(tmp_path, mutation, needle):
    (tmp_path / "bad.yaml").write_text(mutation(GOOD))
    with pytest.raises(PatternError) as e:
        load_patterns(tmp_path)
    assert "bad.yaml" in str(e.value) and needle in str(e.value)

def test_duplicate_ids_rejected(tmp_path):
    (tmp_path / "a.yaml").write_text(GOOD)
    (tmp_path / "b.yaml").write_text(GOOD)
    with pytest.raises(PatternError, match="duplicate id"):
        load_patterns(tmp_path)

def test_missing_directory_is_skipped(tmp_path):
    assert load_patterns(tmp_path / "nope") == []

def test_builtin_python_patterns_load_and_meet_top10():
    pats = [p for p in load_patterns(DEFAULT_PATTERN_DIR) if p.family is Family.PYTHON]
    assert len(pats) >= 10


# --- Task 2 review fixes: malformed manual patterns raise PatternError naming the file
@pytest.mark.parametrize("mutation,needle", [
    (lambda s: s.replace(", tradeoff: More code", ""), "fixes[1]"),
    (lambda s: s.replace("root_cause: Missing key.", "root_cause: 5"), "'root_cause' must be"),
    (lambda s: s.replace("id: python.test.thing", "id: [a]"), "'id' must be"),
    (lambda s: s.replace("tags: [schema]", "tags: [null]"), "tags must be a list of strings"),
    (lambda s: s + "message_regex: 5\n", "'message_regex' must be"),
])
def test_malformed_fields_raise_pattern_error(tmp_path, mutation, needle):
    (tmp_path / "bad.yaml").write_text(mutation(GOOD))
    with pytest.raises(PatternError) as e:
        load_patterns(tmp_path)
    assert "bad.yaml" in str(e.value) and needle in str(e.value)

def test_builtin_tags_are_all_strings():
    assert all(isinstance(t, str) for p in load_patterns(DEFAULT_PATTERN_DIR) for t in p.tags)


@pytest.mark.parametrize("rx", ["(A+)+B", r"(\w*)*", "(a|b+)*x", "(?:x{2,})+"])
def test_nested_quantifier_regex_rejected(tmp_path, rx):
    (tmp_path / "bad.yaml").write_text(GOOD + f"message_regex: '{rx}'\n")
    with pytest.raises(PatternError) as e:
        load_patterns(tmp_path)
    assert "bad.yaml" in str(e.value) and "nested quantifier" in str(e.value)
