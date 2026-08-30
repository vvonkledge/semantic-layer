import pytest

from semantic_layer import graph


@pytest.fixture(scope="session")
def committed_instances() -> list:
    """Every instance file the repository asserts as loadable and valid.

    All three layers, together, because that is the only arrangement that proves
    anything: the crossing edge resolves, and every graph-boundary shape has both the
    graph it judges and the graphs it judges against in front of it.
    """
    return [
        path
        for directory in (
            graph.BUSINESS_DIR,
            graph.TECHNICAL_DIR,
            graph.VALID_FIXTURES_DIR,
            graph.TECHNICAL_VALID_FIXTURES_DIR,
            graph.TRACE_VALID_FIXTURES_DIR,
        )
        for path in graph.turtle_files(directory)
    ]


@pytest.fixture(scope="session")
def question_graph(committed_instances):
    """Everything committed as valid, which is what a question is asked of.

    Competency questions were once asked of the fixtures alone, because curated L1 was
    empty and a question answered only by invented data was the only kind available. It
    is not any more: the organization has declared what it does, and a question that
    could not see that would be proving the vocabulary works rather than proving the
    model answers.

    So the fixtures stay - they exercise shapes the real content does not reach, such as
    a retired capability and an owner who is not the performer - and the real content is
    asked alongside them. A committed answer therefore carries both, and drift in either
    is a failing build rather than a silent change of subject.
    """
    return graph.data_graph(committed_instances)


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


@pytest.fixture(scope="session")
def accepted_pack():
    """The context pack this repository commits, read from disk as a consumer gets it."""
    from semantic_layer import pack

    return pack.read(pack.pack_dir())


@pytest.fixture
def store():
    """A span store in memory, which is what a local file buys: no service to start."""
    from semantic_layer.trace import TraceStore

    with TraceStore.open(":memory:") as opened:
        yield opened
