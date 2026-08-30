import pytest

from semantic_layer import graph


@pytest.fixture(scope="session")
def committed_instances() -> list:
    """Every instance file the repository asserts as loadable and valid.

    Both layers, together, because that is the only arrangement that proves anything:
    the crossing edge resolves, and the two graph-boundary shapes have both graphs in
    front of them.
    """
    return [
        path
        for directory in (
            graph.BUSINESS_DIR,
            graph.TECHNICAL_DIR,
            graph.VALID_FIXTURES_DIR,
            graph.TECHNICAL_VALID_FIXTURES_DIR,
        )
        for path in graph.turtle_files(directory)
    ]


@pytest.fixture(scope="session")
def fixture_graph():
    """The valid fixtures alone, both layers.

    Competency questions are asserted against this graph rather than against curated
    content or a real observation, so their committed answers stay stable as the
    organization's L1 grows and as the source drifts.
    """
    return graph.data_graph(
        graph.turtle_files(graph.VALID_FIXTURES_DIR)
        + graph.turtle_files(graph.TECHNICAL_VALID_FIXTURES_DIR)
    )


@pytest.fixture(autouse=True, scope="session")
def no_network():
    """The suite reads committed files and nothing else, and this is what says so.

    Half of this repository exists to read a public API, and the temptation to reach for
    it from a test is real: a fixture would be fresher, and a failure would be about the
    source rather than about a stale capture. It is the wrong trade twice over. A suite
    that talks to GitHub is a suite that goes red when GitHub is slow, that behaves
    differently for whoever has a token set, and that cannot run in CI without a network
    policy nobody wants to own.

    So the socket is taken away for the whole session. A test that reaches for one fails
    saying why, rather than passing on a machine that happens to be online.
    """
    import socket

    def refuse(*_args, **_kwargs):
        raise RuntimeError(
            "this test tried to open a socket. The suite is offline by construction: "
            "acquisition takes an injected reader (see tests/test_acquisition.py) and "
            "everything else reads committed files."
        )

    original = socket.socket
    socket.socket = refuse
    try:
        yield
    finally:
        socket.socket = original
