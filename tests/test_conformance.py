"""Everything committed as valid validates against every shape, in both layers."""

from semantic_layer import graph


def test_committed_instances_conform(committed_instances):
    report = graph.validate(graph.data_graph(committed_instances))
    assert report.conforms, report.text


def test_there_is_something_to_validate(committed_instances):
    """A conformance pass over an empty graph proves nothing."""
    assert committed_instances


def test_both_layers_are_present(committed_instances):
    """And a pass over one layer proves nothing about the other.

    The two boundary shapes and the two graph-separation shapes only say anything when
    both graphs are loaded, so a suite that quietly stopped loading the observed half
    would go green having checked half of what it claims.
    """
    assert graph.turtle_files(graph.TECHNICAL_VALID_FIXTURES_DIR)
    assert graph.turtle_files(graph.TECHNICAL_DIR)
    assert graph.turtle_files(graph.VALID_FIXTURES_DIR)
