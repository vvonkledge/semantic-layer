"""Each negative fixture is rejected, and rejected for its intended reason.

Asserting the exact message, not just non-conformance, is the point: a shape that
stops enforcing usually keeps failing something, so a bare "it was rejected" check
would keep passing long after it stopped meaning anything.

There is one directory of these per layer, and which one a fixture lives in is not
only tidiness: the loader reads a curated directory into the curated graph and a
technical one into the observed graph, so two of the fixtures below are rejected for
where they are committed rather than for anything written in them.
"""

import pytest

from semantic_layer import graph

FIXTURES = [
    path for directory in graph.INVALID_FIXTURE_DIRS for path in graph.turtle_files(directory)
]


def test_every_violation_class_has_a_fixture():
    assert FIXTURES, "no negative fixtures found"


def _id(path):
    """The layer and the fixture, because both directories are named "invalid"."""
    return f"{path.parent.parent.name}-{path.stem}"


@pytest.mark.parametrize("fixture", FIXTURES, ids=_id)
def test_fixture_is_rejected_for_its_stated_reason(fixture):
    expected_file = fixture.with_suffix(".expected.txt")
    assert expected_file.exists(), f"{fixture.name} has no committed expected message"
    expected = expected_file.read_text(encoding="utf-8").strip()

    report = graph.validate(graph.data_graph([fixture]))

    assert not report.conforms, f"{fixture.name} was expected to be rejected"
    assert list(report.messages) == [expected], (
        f"{fixture.name} should trip exactly one shape, with the committed message"
    )
