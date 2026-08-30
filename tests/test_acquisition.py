"""The acquisition boundary, exercised without a socket.

Every test here injects a reader, so the suite makes no network call and needs no
credential - which is also the property being tested. What is under test is not the
happy path, which GitHub is responsible for: it is the eight ways a capture can fail,
and the single rule that holds for all of them. A capture that cannot complete leaves
the last accepted observation exactly where it was, and says what stopped it.
"""

import json

import pytest

from semantic_layer import acquire, github, graph, pack

REPOSITORY = {
    "id": 1347717349,
    "name": "siana",
    "full_name": "vvonkledge/siana",
    "default_branch": "main",
    "visibility": "public",
    "language": "Python",
    "html_url": "https://github.com/vvonkledge/siana",
    "pushed_at": "2026-08-30T05:07:19Z",
    "archived": False,
    "owner": {
        "id": 121954748,
        "login": "vvonkledge",
        "html_url": "https://github.com/vvonkledge",
        "avatar_url": "https://avatars.githubusercontent.com/u/121954748?v=4",
    },
    "stargazers_count": 0,
    "topics": [],
}

BRANCH = {
    "name": "main",
    "commit": {
        "sha": "558d5f95a97775de2d786eee7ac1f4eb24c2f80f",
        "url": "https://api.github.com/x",
    },
    "protected": False,
}

REPOSITORY_URL = f"{acquire.API_ROOT}/repos/{github.TARGET}"
BRANCHES_URL = f"{REPOSITORY_URL}/branches?per_page={acquire.PER_PAGE}"


def reader(responses):
    """A reader answering from a table, and refusing anything the table does not name."""

    def read(url):
        if url not in responses:
            raise AssertionError(f"the capture asked for {url}, which no test set up")
        status, headers, body = responses[url]
        return status, headers, json.dumps(body).encode() if not isinstance(body, bytes) else body

    return read


def ok(body, headers=None):
    return (200, headers or {}, body)


@pytest.fixture
def responses():
    return {REPOSITORY_URL: ok(REPOSITORY), BRANCHES_URL: ok([BRANCH])}


## What a good capture is.


def test_a_capture_is_the_contract_and_nothing_else(responses):
    """The response is projected, not stored.

    GitHub sends eighty fields; ten of them are read. Everything else - the avatar URL,
    the star count, the topics - is dropped at the boundary rather than carried into the
    graph, which is what makes the committed snapshot reviewable and what means there is
    no field a credential could arrive in and be written from.
    """
    snapshot = acquire.capture(observed_at="2026-08-30T06:07:15Z", reader=reader(responses))
    assert set(snapshot) == set(github.SNAPSHOT_FIELDS)
    assert set(snapshot["repository"]) == set(github.REPOSITORY_FIELDS)
    assert set(snapshot["repository"]["owner"]) == set(github.OWNER_FIELDS)
    assert "avatar_url" not in json.dumps(snapshot)
    assert "stargazers_count" not in json.dumps(snapshot)


def test_a_capture_reconciles(responses):
    """The two halves agree: what acquisition writes is what reconciliation reads."""
    snapshot = acquire.capture(observed_at="2026-08-30T06:07:15Z", reader=reader(responses))
    assert github.reconcile(snapshot, digest="sha256:" + "0" * 64)


def test_a_capture_renders_the_same_bytes_twice(responses):
    snapshot = acquire.capture(observed_at="2026-08-30T06:07:15Z", reader=reader(responses))
    assert acquire.render(snapshot) == acquire.render(snapshot)


def test_no_request_carries_a_credential(monkeypatch, responses):
    """There is no token read and no header that could hold one.

    Stated as a test rather than as a comment because the way this stops being true is
    somebody adding a convenience: an environment variable read "just for rate limits",
    and now the capture behaves differently for whoever has one set, and the trust basis
    it writes down is false.
    """
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_not_a_real_token")
    monkeypatch.setenv("GH_TOKEN", "ghp_not_a_real_token")

    asked = []

    def watching(url):
        asked.append(url)
        return reader(responses)(url)

    snapshot = acquire.capture(observed_at="2026-08-30T06:07:15Z", reader=watching)
    assert asked
    assert "ghp_not_a_real_token" not in json.dumps(snapshot)
    assert "authorization" not in json.dumps(snapshot).lower()


## The target lock.


def test_the_source_is_locked_to_one_repository(responses):
    with pytest.raises(acquire.AcquisitionError, match="locked to"):
        acquire.capture(target="vvonkledge/semantic-layer", reader=reader(responses))


## Pagination.


def test_every_page_is_followed(responses):
    second = f"{BRANCHES_URL}&page=2"
    release = {**BRANCH, "name": "release/1.4"}
    responses[BRANCHES_URL] = ok([BRANCH], {"link": f'<{second}>; rel="next"'})
    responses[second] = ok([release])

    snapshot = acquire.capture(observed_at="2026-08-30T06:07:15Z", reader=reader(responses))
    assert snapshot["branches"]["pages"] == 2
    assert [item["name"] for item in snapshot["branches"]["items"]] == ["main", "release/1.4"]


def test_a_pagination_chain_that_breaks_yields_nothing(responses):
    """Not the pages that did arrive. A prefix of the answer looks like the answer."""
    second = f"{BRANCHES_URL}&page=2"
    responses[BRANCHES_URL] = ok([BRANCH], {"link": f'<{second}>; rel="next"'})
    responses[second] = (500, {}, [])

    with pytest.raises(acquire.AcquisitionError, match="HTTP 500"):
        acquire.capture(reader=reader(responses))


def test_pagination_pointed_off_the_api_is_refused(responses):
    responses[BRANCHES_URL] = ok([BRANCH], {"link": '<https://evil.example/next>; rel="next"'})
    with pytest.raises(acquire.AcquisitionError, match="not under"):
        acquire.capture(reader=reader(responses))


def test_an_endless_pagination_chain_stops(responses):
    responses[BRANCHES_URL] = ok([BRANCH], {"link": f'<{BRANCHES_URL}>; rel="next"'})
    with pytest.raises(acquire.AcquisitionError, match=f"passed {acquire.MAX_PAGES} pages"):
        acquire.capture(reader=reader(responses))


## Everything that is not an answer.


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (
            (403, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1790000000"}, {}),
            "rate limited",
        ),
        (
            (429, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1790000000"}, {}),
            "rate limited",
        ),
        ((401, {}, {}), "sends no credential by design"),
        ((403, {"x-ratelimit-remaining": "58"}, {}), "sends no credential by design"),
        ((404, {}, {}), "not found"),
        ((500, {}, {}), "HTTP 500"),
        ((200, {}, b"<html>not json</html>"), "not JSON"),
    ],
    ids=[
        "rate limited",
        "too many requests",
        "unauthorized",
        "forbidden",
        "gone",
        "server error",
        "not json",
    ],
)
def test_a_refusal_is_never_read_as_an_empty_answer(responses, response, expected):
    responses[REPOSITORY_URL] = response
    with pytest.raises(acquire.AcquisitionError, match=expected):
        acquire.capture(reader=reader(responses))


def test_schema_drift_is_an_error_rather_than_a_gap(responses):
    responses[REPOSITORY_URL] = ok({k: v for k, v in REPOSITORY.items() if k != "default_branch"})
    with pytest.raises(acquire.AcquisitionError, match="drifted"):
        acquire.capture(reader=reader(responses))


def test_a_collection_that_is_not_a_collection_is_an_error(responses):
    responses[BRANCHES_URL] = ok({"message": "Moved Permanently"})
    with pytest.raises(acquire.AcquisitionError, match="not a list"):
        acquire.capture(reader=reader(responses))


## The write.


@pytest.mark.parametrize("dies_at", ["os.fsync", "os.replace"])
def test_a_write_replaces_the_last_accepted_bytes_or_leaves_them(tmp_path, monkeypatch, dies_at):
    """The new bytes land in one step, or not at all.

    A capture that dies partway through writing must not leave a truncated snapshot in
    place of a good one: the failure mode is losing an observation, not silently keeping
    half of one and hashing it. The temporary file is in the same directory, so the
    rename is on one filesystem and is atomic; the two moments it can die are once the
    bytes are down and once the rename has begun, and neither leaves anything behind.
    """
    import os

    path = tmp_path / "snapshot.json"
    acquire.write_atomically(path, b"first\n")

    def die(*_args, **_kwargs):
        raise OSError("the disk went away")

    monkeypatch.setattr(os, dies_at.split(".")[1], die)
    with pytest.raises(OSError, match="disk went away"):
        acquire.write_atomically(path, b"second\n")

    assert path.read_bytes() == b"first\n"
    assert not list(tmp_path.glob("*.partial"))


def test_a_snapshot_is_written_with_the_digest_that_checks_it(tmp_path, responses):
    path = tmp_path / "snapshot.json"
    snapshot = acquire.capture(observed_at="2026-08-30T06:07:15Z", reader=reader(responses))
    digest = acquire.write_snapshot(snapshot, path)

    read, checked = github.read_snapshot(path)
    assert checked == digest
    assert read == snapshot


@pytest.fixture
def layer(tmp_path, monkeypatch):
    """One repository holding one accepted observation, in a tree this test owns.

    The commands downstream of a capture read and write committed paths, so a test that
    interrupts a capture in ``tmp_path`` and then asserts about ``packs/`` is asserting
    about files the interrupted writer could not have reached either way - true, and
    unable to fail. Every path the three commands use is pointed here instead, so
    `just reconcile` and `just pack` can be run for real against the snapshot this test
    interrupted, and what they leave behind is what the assertions read.
    """
    technical = (tmp_path / "ontology" / "instances" / "technical").resolve()
    technical.mkdir(parents=True)
    accepted = technical / "github-vvonkledge-siana.ttl"
    monkeypatch.setitem(graph.INSTANCE_GRAPHS, technical, graph.OBSERVED_GRAPH)
    monkeypatch.setattr(graph, "TECHNICAL_DIR", technical)
    monkeypatch.setattr(graph, "PACKS_DIR", tmp_path / "packs")
    monkeypatch.setattr(
        github, "snapshot_path", lambda *_args, **_kwargs: tmp_path / "snapshot.json"
    )
    monkeypatch.setattr(github, "accepted_path", lambda *_args, **_kwargs: accepted)


@pytest.mark.parametrize("dies_at", [1, 2])
def test_an_interruption_between_the_snapshot_and_its_digest_is_refused_not_believed(
    monkeypatch, responses, layer, dies_at
):
    """Two renames are not one, so what is guaranteed is that neither half is believed.

    ``write_snapshot`` writes the snapshot and then its digest, each atomically. Killed
    before the first, both files are still the last accepted observation. Killed between
    them, the snapshot is new and the digest still commits the old bytes - and that pair
    is refused by name rather than reconciled, so the accepted graph and the context pack
    cannot be built from a capture that never finished landing. Recovery is a person's:
    recapture, or `git checkout` the pair back.

    The refusal is driven rather than described. The whole path is run first, so there
    is a real accepted graph and a real pack to protect; then the capture is interrupted
    and the next command a person would type is run against what it left. What must
    fail, fails by name, and what must not move, has not moved.
    """
    path = github.snapshot_path()
    sidecar = path.with_name("snapshot.json.sha256")
    accepted = acquire.capture(observed_at="2026-08-30T06:07:15Z", reader=reader(responses))
    accepted_digest = acquire.write_snapshot(accepted, path)
    github.main()
    pack.main()
    accepted_graph = github.accepted_path().read_bytes()
    held = pack.read(pack.pack_dir())

    later = json.loads(json.dumps(accepted))
    later["observed_at"] = "2026-08-31T06:07:15Z"

    landed = acquire.write_atomically
    writes = 0

    def die_on_the_nth_write(target, payload):
        nonlocal writes
        writes += 1
        if writes == dies_at:
            raise OSError("the machine went away")
        landed(target, payload)

    # Scoped, so the interruption is the capture's own and the commands run below write
    # for real.
    with monkeypatch.context() as interrupted:
        interrupted.setattr(acquire, "write_atomically", die_on_the_nth_write)
        with pytest.raises(OSError, match="machine went away"):
            acquire.write_snapshot(later, path)

    if dies_at == 1:
        # Nothing landed, so the pair is still the accepted observation and the next
        # `just reconcile` is an ordinary one that reproduces the same bytes.
        assert github.read_snapshot(path) == (accepted, accepted_digest)
        github.main()
    else:
        assert json.loads(path.read_bytes()) == later
        assert sidecar.read_text(encoding="utf-8").strip() == accepted_digest
        with pytest.raises(github.ReconcileError, match="Recapture"):
            github.read_snapshot(path)
        # The command, not just the reader it calls: `just reconcile` against this pair
        # refuses before it writes anything, which is the whole of what protects the
        # accepted graph.
        with pytest.raises(github.ReconcileError, match="Recapture"):
            github.main()

    assert github.accepted_path().read_bytes() == accepted_graph, (
        "the reconcile wrote a graph from a capture that never finished landing"
    )
    assert pack.read(pack.pack_dir()) == held, "the pack moved without a reconcile writing one"

    # And the observation a consumer would be handed is still the accepted one: rebuild
    # the pack from the graph the refusal protected and it is byte-identical, so the
    # interrupted capture reached neither half of what leaves this repository.
    pack.main()
    assert pack.read(pack.pack_dir()) == held
    assert json.loads(held.manifest)["observed_at"] == accepted["observed_at"]
