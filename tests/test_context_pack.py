"""A pack is checkable by whoever receives it, or it is not worth sending.

The build half is easy and mostly proved by the committed pack reproducing. The half
that matters is ``verify``, and it is written from the consumer's side: they have two
files, no git history, no idea what this repository is, and a decision to make. Each
test below is one way that decision could be made on something they should have
refused.
"""

import json

import pytest
from rdflib import URIRef

from semantic_layer import graph, pack

FRESH = "2026-08-30T12:00:00Z"


@pytest.fixture(scope="session")
def committed():
    return pack.read(pack.pack_dir())


@pytest.fixture
def copy(committed):
    return pack.Pack(content=committed.content, manifest=committed.manifest)


def amended(committed, **changes):
    manifest = json.loads(committed.manifest)
    manifest.update(changes)
    return pack.Pack(content=committed.content, manifest=pack.render(manifest))


## What is committed.


def test_the_committed_pack_is_what_the_accepted_graph_packs(committed):
    """Deterministic, so a refresh that changes nothing shows no diff here either."""
    built = pack.build(graph.turtle_files(graph.TECHNICAL_DIR), pack.accepted_observation())
    assert built.content == committed.content
    assert built.manifest == committed.manifest


def test_the_committed_pack_verifies_inside_its_own_window(committed):
    stated = pack.verify(committed.content, committed.manifest, as_of=FRESH)
    assert stated["target"] == "vvonkledge/siana"
    assert stated["trust_basis"]


def test_the_manifest_names_what_a_consumer_has_to_decide_on(committed):
    """The manifest is read by someone who will not parse the graph.

    Every field here answers a question they have to answer before acting: where did
    this come from, when was it true, until when, why believe it, and is this the file
    that was sent.
    """
    stated = json.loads(committed.manifest)
    assert set(stated) >= {
        "graph",
        "vocabulary_version",
        "source",
        "provider",
        "target",
        "observation",
        "observed_at",
        "fresh_until",
        "trust_basis",
        "snapshot_digest",
        "content_digest",
    }
    assert stated["graph"] == str(graph.OBSERVED_GRAPH)


def test_a_pack_carries_the_observation_it_names_and_nothing_else(committed):
    """Bounded: one reading, the source behind it, and what that reading saw."""
    content = graph.load_text(committed.content.decode())
    stated = json.loads(committed.manifest)
    observation = URIRef(stated["observation"])
    for subject in set(content.subjects()):
        assert subject in {observation, URIRef(stated["source"])} or (
            (subject, graph.TECH.observedIn, observation) in content
        ), f"{subject} is in the pack and belongs to no part of this observation"


def test_a_pack_carries_no_business_fact(committed):
    """L1 has no observation behind it and no freshness to state.

    Putting the two in one artifact would hand a consumer declared business truth
    stamped with an expiry date it has no way to honour.
    """
    assert b"/vocab/biz#" not in committed.content
    assert b"/biz/" not in committed.content


## What a consumer must refuse.


def test_a_stale_pack_is_refused(committed):
    with pytest.raises(pack.PackError, match="stops being worth believing"):
        pack.verify(committed.content, committed.manifest, as_of="2026-09-05T00:00:00Z")


def test_a_pack_is_refused_at_the_instant_it_expires(committed):
    """The boundary is exclusive, so "fresh until" means what it says."""
    stated = json.loads(committed.manifest)
    with pytest.raises(pack.PackError, match="stops being worth believing"):
        pack.verify(committed.content, committed.manifest, as_of=stated["fresh_until"])


def test_tampered_content_is_refused(committed):
    tampered = committed.content.replace(b'"public"', b'"private"')
    assert tampered != committed.content
    with pytest.raises(pack.PackError, match="do not belong to each other"):
        pack.verify(tampered, committed.manifest, as_of=FRESH)


def test_a_manifest_that_disagrees_with_its_content_is_refused(committed):
    """Every field a consumer reads without parsing the graph is held against the graph.

    A manifest is read first and believed, so one that has been edited to say the
    observation is newer than it is would be believed too.
    """
    for key, value in (
        ("observed_at", "2026-08-30T23:59:59Z"),
        ("fresh_until", "2027-01-01T00:00:00Z"),
        ("target", "vvonkledge/semantic-layer"),
        ("snapshot_digest", "sha256:" + "0" * 64),
        ("source", "https://semantic-layer.19h09.co/l2/gitlab/gitlab-com"),
    ):
        with pytest.raises(pack.PackError, match="says"):
            pack.verify(committed.content, amended(committed, **{key: value}).manifest, as_of=FRESH)


def test_a_manifest_naming_an_observation_the_content_lacks_is_refused(committed):
    amended_pack = amended(
        committed,
        observation="https://semantic-layer.19h09.co/l2/github/api-github-com/observation/"
        + "0" * 64,
    )
    with pytest.raises(pack.PackError, match="does not contain it"):
        pack.verify(committed.content, amended_pack.manifest, as_of=FRESH)


def test_a_pack_from_another_source_is_refused(committed):
    """An identifier means nothing outside the source that issued it.

    A consumer that asked github.com for repository 1347717349 and was handed a GitHub
    Enterprise pack holding the same number is holding a different thing, and every
    field in it will look plausible.
    """
    with pytest.raises(pack.PackError, match="acting on a different thing"):
        pack.verify(
            committed.content,
            committed.manifest,
            as_of=FRESH,
            expect_source="https://semantic-layer.19h09.co/l2/github/github-example-org",
        )


def test_a_pack_about_another_target_is_refused(committed):
    with pytest.raises(pack.PackError, match="was expected"):
        pack.verify(
            committed.content,
            committed.manifest,
            as_of=FRESH,
            expect_target="vvonkledge/semantic-layer",
        )


def test_a_pack_written_in_another_layout_is_refused(committed):
    with pytest.raises(pack.PackError, match="another layout"):
        pack.verify(committed.content, amended(committed, pack_version=2).manifest, as_of=FRESH)


def test_a_manifest_that_is_not_json_is_refused(committed):
    with pytest.raises(pack.PackError, match="not valid JSON"):
        pack.verify(committed.content, b"{", as_of=FRESH)


def test_a_comparison_instant_that_is_not_an_instant_is_refused(committed):
    """Rather than compared as a string and quietly answered."""
    with pytest.raises(pack.PackError, match="not a UTC instant"):
        pack.verify(committed.content, committed.manifest, as_of="2026-08-30")


def test_packing_something_that_is_not_an_observation_is_refused():
    with pytest.raises(pack.PackError, match="not an observation"):
        pack.build(
            graph.turtle_files(graph.TECHNICAL_DIR),
            URIRef(
                "https://semantic-layer.19h09.co/l2/github/api-github-com/repository/1347717349"
            ),
        )
