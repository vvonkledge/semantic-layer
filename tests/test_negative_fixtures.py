"""Each negative fixture is rejected, and rejected for its intended reason.

Asserting the exact message, not just non-conformance, is the point: a shape that
stops enforcing usually keeps failing something, so a bare "it was rejected" check
would keep passing long after it stopped meaning anything.
"""

import pytest

from semantic_layer import graph

FIXTURES = graph.turtle_files(graph.INVALID_FIXTURES_DIR)


def test_every_violation_class_has_a_fixture():
    assert FIXTURES, "no negative fixtures found"


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda path: path.stem)
def test_fixture_is_rejected_for_its_stated_reason(fixture):
    expected_file = fixture.with_suffix(".expected.txt")
    assert expected_file.exists(), f"{fixture.name} has no committed expected message"
    expected = expected_file.read_text(encoding="utf-8").strip()

    report = graph.validate(graph.data_graph([fixture]))

    assert not report.conforms, f"{fixture.name} was expected to be rejected"
    assert list(report.messages) == [expected], (
        f"{fixture.name} should trip exactly one shape, with the committed message"
    )
