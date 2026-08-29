"""Everything committed as valid L1 validates against every shape."""

from semantic_layer import graph


def test_committed_instances_conform(curated_and_fixture_instances):
    report = graph.validate(graph.data_graph(curated_and_fixture_instances))
    assert report.conforms, report.text


def test_there_is_something_to_validate(curated_and_fixture_instances):
    """A conformance pass over an empty graph proves nothing."""
    assert curated_and_fixture_instances
