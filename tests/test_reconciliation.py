"""Reconciliation is deterministic, closed, and refuses rather than guesses.

Three claims are under test, and they are the three the promote workflow rests on.

**The committed graph is the committed capture.** Not equivalent to it, not derived
from something like it: the same bytes, reproduced here. That is what makes reviewing a
refresh a matter of reading a diff rather than trusting a generator.

**Determinism is unconditional.** Same payload and same instants, same bytes, whatever
order the JSON arrived in, whatever the hash seed, the locale or the clock. The three
subprocesses below are not belt and braces - a dict iteration order leaking into output
is exactly the bug that shows up as a spurious diff months later and gets blamed on the
source.

**A response that is not the response is an error.** Missing fields, unknown fields, a
collection that stopped early, an id that is not an id: each is refused by name, because
the alternative is a partial answer committed as an authoritative one.
"""

import json
import os
import subprocess
import sys

import pytest

from semantic_layer import github, graph, ids

BIZ = "https://semantic-layer.19h09.co/vocab/biz#"
TECH = "https://semantic-layer.19h09.co/vocab/tech#"


@pytest.fixture(scope="session")
def committed():
    snapshot, digest = github.read_snapshot(github.snapshot_path())
    return snapshot, digest


@pytest.fixture
def snapshot(committed):
    """A private copy of the committed capture, for tests that break one field."""
    return json.loads(json.dumps(committed[0]))


DIGEST = "sha256:" + "0" * 64


def reconcile(snapshot):
    return github.reconcile(snapshot, digest=DIGEST)


## The committed graph, and the capture it came from.


def test_the_committed_graph_is_what_the_committed_capture_reconciles_to(committed):
    """The single most load-bearing assertion in the L2 half of this repository.

    Everything downstream - the context pack, the competency questions, the freshness
    of anything a consumer is handed - is about a graph that claims to be a reading of
    a source. This is what makes the claim checkable rather than asserted: the bytes on
    disk are reproduced from the bytes that were captured, and a hand-edit to either
    fails here.
    """
    snapshot, digest = committed
    assert github.accepted_path().read_text(encoding="utf-8") == github.reconcile(
        snapshot, digest=digest
    )


def test_a_capture_edited_after_it_was_hashed_is_refused(tmp_path):
    path = tmp_path / "snapshot.json"
    path.write_text('{"target": "vvonkledge/siana"}\n', encoding="utf-8")
    path.with_name("snapshot.json.sha256").write_text(f"{DIGEST}\n", encoding="utf-8")
    with pytest.raises(github.ReconcileError, match="disagree"):
        github.read_snapshot(path)


def test_a_capture_that_is_not_there_is_refused_by_name(tmp_path):
    """The first error a cold reader following the README from an empty tree can hit.

    A missing capture is a state with an obvious next step, not a bug, so it is refused
    the way every other acquisition failure is: a domain error that names the file and
    the command to run. An OSError escaping here would be the one path in this change
    that answers a reader with a stack trace.
    """
    with pytest.raises(github.ReconcileError, match="just capture"):
        github.read_snapshot(tmp_path / "snapshot.json")


def test_a_capture_with_no_committed_digest_is_refused(tmp_path):
    path = tmp_path / "snapshot.json"
    path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(github.ReconcileError, match="no committed digest"):
        github.read_snapshot(path)


def test_the_committed_capture_holds_exactly_the_contract(committed):
    """A field nobody chose is a field nobody has decided the meaning of.

    It is also the only route a credential could take into the graph, since the capture
    projects the response rather than storing it. Holding the committed file against the
    contract is what makes that projection a promise.
    """
    snapshot, _ = committed
    assert set(snapshot) == set(github.SNAPSHOT_FIELDS)
    assert set(snapshot["repository"]) == set(github.REPOSITORY_FIELDS)
    assert set(snapshot["repository"]["owner"]) == set(github.OWNER_FIELDS)
    for branch in snapshot["branches"]["items"]:
        assert set(branch) == set(github.BRANCH_FIELDS)
        assert set(branch["commit"]) == set(github.BRANCH_COMMIT_FIELDS)


## Determinism.


def test_reconciling_twice_gives_the_same_bytes(snapshot):
    assert reconcile(snapshot) == reconcile(snapshot)


def test_the_order_the_payload_arrived_in_does_not_reach_the_output(snapshot):
    shuffled = dict(reversed(list(snapshot.items())))
    shuffled["repository"] = dict(reversed(list(snapshot["repository"].items())))
    assert reconcile(shuffled) == reconcile(snapshot)


def test_the_order_of_a_collection_does_not_reach_the_output(snapshot):
    """Two branches, given both ways round. GitHub does not promise an order."""
    snapshot["branches"]["items"] = [
        snapshot["branches"]["items"][0],
        {
            "name": "release/1.4",
            "commit": {"sha": "0f4b3ac8ff35b1e08c8a2d7d1e0f4b0f43e2a11c"},
            "protected": False,
        },
    ]
    forward = reconcile(snapshot)
    snapshot["branches"]["items"] = list(reversed(snapshot["branches"]["items"]))
    assert reconcile(snapshot) == forward


RECONCILE_SCRIPT = """
import json, sys
from semantic_layer import github
snapshot, digest = github.read_snapshot(github.snapshot_path())
sys.stdout.write(github.reconcile(snapshot, digest=digest))
"""


def _reconcile_under(**environment) -> str:
    env = dict(os.environ, **environment)
    result = subprocess.run(
        [sys.executable, "-c", RECONCILE_SCRIPT],
        capture_output=True,
        check=True,
        cwd=graph.ROOT,
        env=env,
        text=True,
    )
    return result.stdout


@pytest.mark.parametrize(
    "environment",
    [
        {"PYTHONHASHSEED": "0"},
        {"PYTHONHASHSEED": "1"},
        {"TZ": "Asia/Kathmandu"},
        {"TZ": "Pacific/Kiritimati", "LC_ALL": "C"},
        {"LC_ALL": "tr_TR.UTF-8", "LANG": "tr_TR.UTF-8"},
    ],
    ids=["hash seed 0", "hash seed 1", "UTC+5:45", "UTC+14", "Turkish locale"],
)
def test_nothing_outside_the_payload_reaches_the_output(environment):
    """The clock, the hash seed and the locale are all ways a diff appears from nowhere.

    A timezone that is not a whole number of hours off UTC catches an instant formatted
    through local time; a Turkish locale catches a case conversion done without one, the
    classic being a lower-cased "I" that stops being an I.
    """
    assert _reconcile_under(**environment) == github.accepted_path().read_text(encoding="utf-8")


## Identity, held against the two ways it goes wrong.


def test_a_rename_updates_attributes_without_minting_a_second_entity(snapshot):
    """The reason an identifier is not a name.

    GitHub renames a repository in one click and keeps the id. If the identifier
    tracked the path, the next observation would mint a second repository, the first
    would go quiet, and nothing would say the two were one thing.
    """
    before = graph.load_text(reconcile(snapshot))
    snapshot["repository"]["name"] = "siana-renamed"
    snapshot["repository"]["full_name"] = "vvonkledge/siana-renamed"
    snapshot["repository"]["owner"]["login"] = "vvonkledge-renamed"
    after = graph.load_text(reconcile(snapshot))

    assert set(after.subjects()) == set(before.subjects())
    assert set(after) != set(before)


def test_two_installations_of_one_provider_do_not_collide(snapshot):
    """The same numeric id at github.com and at a GitHub Enterprise host."""
    here = set(graph.load_text(reconcile(snapshot)).subjects())
    snapshot["instance"] = "github-example-org"
    snapshot["api_root"] = "https://github.example.org/api/v3"
    there = set(graph.load_text(reconcile(snapshot)).subjects())
    assert here & there == set()


HOSTILE = {
    "name": '../../etc/passwd" ; a <https://evil.example/Thing> ; #',
    "full_name": "vvonkledge/..\n<injected>",
    "login": "vvonkledge‮",
    "branch": "feature/../../../etc/passwd?x=1#y",
}


def test_hostile_text_from_the_source_lands_as_text(snapshot):
    """A source's text goes in literals and never in structure.

    The identifiers are built from numbers the source issued and from a percent-encoded
    branch name, so the quotes, angle brackets, newlines and path segments below reach
    the graph as characters in a string and change nothing about its shape.
    """
    snapshot["repository"]["name"] = HOSTILE["name"]
    snapshot["repository"]["full_name"] = HOSTILE["full_name"]
    snapshot["repository"]["owner"]["login"] = HOSTILE["login"]
    snapshot["branches"]["items"][0]["name"] = HOSTILE["branch"]
    snapshot["repository"]["default_branch"] = HOSTILE["branch"]

    data = graph.load_text(reconcile(snapshot))
    assert graph.validate(graph.observed_data_graph(reconcile(snapshot))).conforms
    for subject in data.subjects():
        assert str(subject).startswith("https://semantic-layer.19h09.co/l2/github/api-github-com")
    branch = ids.mint_observed(
        "github", "api-github-com", "branch", "1347717349", HOSTILE["branch"]
    )
    assert ids.parse_observed(branch).local_id == ("1347717349", HOSTILE["branch"])


def test_a_branch_whose_name_a_resolver_would_collapse_is_refused(snapshot):
    snapshot["branches"]["items"][0]["name"] = ".."
    snapshot["repository"]["default_branch"] = ".."
    with pytest.raises(github.ReconcileError, match="collapse"):
        reconcile(snapshot)


## What the import is not allowed to do.


def test_the_import_authors_no_business_fact(committed):
    """A source knows what it contains, never what the organization answers for.

    The layer-separation shape enforces this against the committed graph; this is the
    other half, against the code that writes it, so a reconciler that started emitting
    an owner or a capability fails here rather than at the point somebody notices.
    """
    snapshot, digest = committed
    data = graph.load_text(github.reconcile(snapshot, digest=digest))
    for subject, predicate, obj in data:
        assert not str(predicate).startswith(BIZ), f"the import wrote {predicate}"
        assert not str(obj).startswith(BIZ), f"the import wrote a value from {obj}"
        assert not str(subject).startswith("https://semantic-layer.19h09.co/biz/")


def test_the_import_writes_no_crossing_edge(committed):
    """tech:realizes is authored by a human under review, and by nothing else."""
    snapshot, digest = committed
    data = graph.load_text(github.reconcile(snapshot, digest=digest))
    assert not list(data.triples((None, graph.TECH.realizes, None)))


## Refusals, one per way a response can fail to be an answer.


#: One entry per way a response can fail to be an answer: what it does to the payload,
#: and the sentence the reader is owed. The id is the field, so a failure names the
#: contract line to go and read rather than the phrase it happened to match on.
NOT_AN_ANSWER = [
    ("target: absent", lambda s: s.pop("target"), "missing"),
    ("target: another repository", lambda s: s.update(target="vvonkledge/other"), "locked to"),
    ("provider: another system", lambda s: s.update(provider="gitlab"), "reads 'github'"),
    ("snapshot_version: unknown", lambda s: s.update(snapshot_version=2), "another layout"),
    ("snapshot: a field nobody chose", lambda s: s.update(surprise="?"), "does not read"),
    (
        "repository: a field nobody chose",
        lambda s: s["repository"].update(surprise=1),
        "does not read",
    ),
    ("repository.id: absent", lambda s: s["repository"].pop("id"), "missing"),
    ("repository.id: null", lambda s: s["repository"].update(id=None), "positive integer"),
    ("repository.id: zero", lambda s: s["repository"].update(id=0), "positive integer"),
    ("repository.id: negative", lambda s: s["repository"].update(id=-3), "positive integer"),
    (
        "repository.id: a string",
        lambda s: s["repository"].update(id="1347717349"),
        "positive integer",
    ),
    ("repository.id: a boolean", lambda s: s["repository"].update(id=True), "positive integer"),
    ("owner.id: null", lambda s: s["repository"]["owner"].update(id=None), "positive integer"),
    (
        "repository.html_url: not https",
        lambda s: s["repository"].update(html_url="http://github.com/vvonkledge/siana"),
        "https",
    ),
    (
        "repository.pushed_at: a date",
        lambda s: s["repository"].update(pushed_at="2026-08-30"),
        "UTC instant",
    ),
    (
        "repository.archived: a string",
        lambda s: s["repository"].update(archived="false"),
        "true or false",
    ),
    (
        "repository.default_branch: not in the branch list",
        lambda s: s["repository"].update(default_branch="trunk"),
        "do not include it",
    ),
    (
        "branches.complete: false",
        lambda s: s["branches"].update(complete=False),
        "did not follow pagination",
    ),
    ("branches.complete: absent", lambda s: s["branches"].pop("complete"), "missing"),
    ("branches.items: not a list", lambda s: s["branches"].update(items={}), "reads a list"),
    ("freshness_seconds: zero", lambda s: s.update(freshness_seconds=0), "positive integer"),
    (
        "observed_at: not an instant",
        lambda s: s.update(observed_at="2026-08-30 06:07:15"),
        "UTC instant",
    ),
    ("api_root: not https", lambda s: s.update(api_root="http://api.github.com"), "https"),
    ("trust_basis: empty", lambda s: s.update(trust_basis=""), "non-empty string"),
]


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [entry[1:] for entry in NOT_AN_ANSWER],
    ids=[entry[0] for entry in NOT_AN_ANSWER],
)
def test_a_response_that_is_not_an_answer_is_refused(snapshot, mutate, expected):
    mutate(snapshot)
    with pytest.raises(github.ReconcileError, match=expected):
        reconcile(snapshot)


def test_two_branches_with_one_name_are_refused(snapshot):
    """Two artifacts minting one identifier describe two things as one thing."""
    snapshot["branches"]["items"] = [snapshot["branches"]["items"][0]] * 2
    with pytest.raises(github.ReconcileError, match="already used"):
        reconcile(snapshot)


def test_a_truncated_branch_page_is_refused(snapshot):
    """The default branch is the tripwire: a prefix of the list is not the list."""
    snapshot["branches"]["items"] = []
    with pytest.raises(github.ReconcileError, match="do not include it"):
        reconcile(snapshot)


def test_a_malformed_commit_is_refused(snapshot):
    snapshot["branches"]["items"][0]["commit"]["sha"] = "558D5F9"
    with pytest.raises(github.ReconcileError, match="SHA-1"):
        reconcile(snapshot)


def test_an_absent_optional_field_is_an_answer_and_a_missing_one_is_not(snapshot):
    """GitHub reports no language for an empty repository, and that is an answer."""
    snapshot["repository"]["language"] = None
    assert "primaryLanguage" not in reconcile(snapshot)

    del snapshot["repository"]["language"]
    with pytest.raises(github.ReconcileError, match="missing"):
        reconcile(snapshot)
