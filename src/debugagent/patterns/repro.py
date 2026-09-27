import re
from string import Template
from debugagent.models import Family, Frame, ParsedTrace

FAMILY_REPRO: dict[Family, str] = {
    Family.PYTHON: '''# Repro for ${pattern_id} at ${file}:${line}
import pytest

def test_repro_${test_name}():
    # Arrange: rebuild the input that reached ${function}() (see the logged payload)
    # Assert the current failure; after the fix, change this to assert the correct result
    with pytest.raises(${short_error_type}):
        ${function}(...)  # call with the failing input
''',
    Family.JVM: '''// Repro for ${pattern_id} at ${file}:${line}
@Test
void repro_${test_name}() {
    // Arrange: rebuild the input that reached ${module}.${function}
    assertThrows(${short_error_type}.class, () -> {
        // call ${function} with the failing input
    });
}
''',
    Family.NODE: '''// Repro for ${pattern_id} at ${file}:${line}
test("repro ${test_name}", async () => {
  // Arrange: rebuild the input that reached ${function}
  await expect(async () => {
    // call ${function} with the failing input
  }).rejects.toThrow(/${message_escaped}/);
});
''',
    Family.GO: '''// Repro for ${pattern_id} at ${file}:${line}
func TestRepro_${test_name}(t *testing.T) {
\tdefer func() {
\t\tif r := recover(); r == nil {
\t\t\tt.Fatal("expected panic: ${message_quoted}")
\t\t}
\t}()
\t// call ${function} with the failing input
}
''',
    Family.RUST: '''// Repro for ${pattern_id} at ${file}:${line}
#[test]
#[should_panic(expected = "${message_quoted}")]
fn repro_${test_name}() {
    // call ${function} with the failing input
}
''',
}


def render_repro(template: str, pattern_id: str, root: ParsedTrace, loc: Frame | None) -> str:
    function = loc.function if loc else "unknown"
    short_fn = re.split(r"[.:/]+", function)[-1] or function
    test_name = re.sub(r"\W+", "_", short_fn).strip("_") or "repro"
    msg = root.message[:80]
    return Template(template).safe_substitute(
        pattern_id=pattern_id,
        file=loc.file.rsplit("/", 1)[-1] if loc else "?",
        line=loc.line if loc and loc.line is not None else "?",
        function=short_fn,
        module=(loc.module or "") if loc else "",
        test_name=test_name,
        error_type=root.error_type,
        short_error_type=root.short_error_type,
        message_escaped=re.escape(msg).replace("/", r"\/"),
        message_quoted=msg.replace("\\", "\\\\").replace('"', '\\"'),
    )
