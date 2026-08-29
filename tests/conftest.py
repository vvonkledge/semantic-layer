import pytest

from semantic_layer import graph


@pytest.fixture(scope="session")
def curated_and_fixture_instances() -> list:
    """Every instance file the repository asserts as loadable, valid L1."""
    return graph.turtle_files(graph.BUSINESS_DIR) + graph.turtle_files(graph.VALID_FIXTURES_DIR)


@pytest.fixture(scope="session")
def fixture_graph():
    """The valid fixtures alone.

    Competency questions are asserted against this graph rather than against curated
    content, so their committed answers stay stable as the organization's real L1
    grows.
    """
    return graph.data_graph(graph.turtle_files(graph.VALID_FIXTURES_DIR))
