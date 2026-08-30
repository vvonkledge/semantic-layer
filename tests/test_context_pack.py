"""A pack is checkable by whoever receives it, or it is not worth sending.

The build half is easy and mostly proved by the committed pack reproducing. The half
that matters is ``verify``, and it is written from the consumer's side: they have two
files, no git history, no idea what this repository is, and a decision to make. Each
test below is one way that decision could be made on something they should have
refused.
"""

import json
from datetime import datetime, timedelta

import pytest
from rdflib import RDF, Graph, URIRef

from semantic_layer import github, graph, pack


@pytest.fixture(scope="session")
def committed():
    return pack.read(pack.pack_dir())


def _within(held) -> str:
    """An instant inside the pack's own window, read from the pack.

    Hard-coding one would be a test that quietly stops meaning anything the first time
    somebody refreshes the observation: the window moves and a date chosen to be inside
    it stays where it was. The instant the observation was made is inside its own window
    by construction, whenever that was.
    """
    return json.loads(held.manifest)["observed_at"]


def _past(held) -> str:
    """The instant the pack expires, which is the first one it must refuse."""
    return json.loads(held.manifest)["fresh_until"]


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
    built = pack.build(pack.accepted(), pack.accepted_observation())
    assert built.content == committed.content
    assert built.manifest == committed.manifest


def test_the_committed_pack_verifies_inside_its_own_window(committed):
    stated = pack.verify(committed.content, committed.manifest, as_of=_within(committed))
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


def test_a_pack_asserts_nothing_about_a_business_entity(committed):
    """It may point at L1. It may not state anything about it.

    The distinction is the crossing edge, and getting it wrong in either direction is
    a real failure. Carrying the L1 entity itself would hand a consumer declared
    business truth stamped with an expiry date it has no way to honour - L1 has no
    observation behind it and no freshness to state. Dropping the pointer would throw
    away the most valuable fact in the pack: which capability this system delivers.
    """
    content = graph.load_text(committed.content.decode())
    for subject, predicate, _ in content:
        assert not str(subject).startswith("https://semantic-layer.19h09.co/biz/")
        assert not str(subject).startswith("https://semantic-layer.19h09.co/fixture/biz/")
        assert not str(predicate).startswith("https://semantic-layer.19h09.co/vocab/biz#")


def test_a_pack_carries_the_crossing_edge_and_not_what_is_on_the_other_side():
    """Built from the fixtures, which have a tech:realizes edge; the accepted graph
    has none yet, so asserting this against it would prove nothing today and would
    break on the day somebody authored one.
    """
    observation = URIRef(
        "https://semantic-layer.19h09.co/fixture/l2/github/api-github-com/observation/"
        "3f786850e387550fdab836ed7e6dc881de23001b3f786850e387550fdab836ed"
    )
    built = pack.build(
        pack.observed(graph.turtle_files(graph.TECHNICAL_VALID_FIXTURES_DIR)), observation
    )
    content = graph.load_text(built.content.decode())

    capability = URIRef("https://semantic-layer.19h09.co/fixture/biz/capability/payment-processing")
    assert list(content.subjects(graph.TECH.realizes, capability)), (
        "the pack dropped the crossing edge, which is the fact a consumer most wants"
    )
    assert not list(content.predicate_objects(capability)), (
        "the pack carries the capability itself, which has no observation behind it"
    )


## What a consumer must refuse.


def test_a_pack_is_refused_from_the_instant_it_expires(committed):
    """The boundary is exclusive, so "fresh until" means what it says.

    Both instants are read from the pack rather than written down here, so a refresh
    moves the window and the test goes on asking the same question.
    """
    expires = datetime.fromisoformat(_past(committed))
    for instant in (expires, expires + timedelta(days=7)):
        with pytest.raises(pack.PackError, match="stops being worth believing"):
            pack.verify(
                committed.content,
                committed.manifest,
                as_of=instant.strftime("%Y-%m-%dT%H:%M:%SZ"),
            )


def test_tampered_content_is_refused(committed):
    tampered = committed.content.replace(b'"public"', b'"private"')
    assert tampered != committed.content
    with pytest.raises(pack.PackError, match="do not belong to each other"):
        pack.verify(tampered, committed.manifest, as_of=_within(committed))


#: One forgery per manifest field: a value a consumer would act on differently, and
#: what refusing it must say. A field is listed here or the audit below fails, so a
#: field added to the manifest cannot reach a consumer with nothing holding it.
FORGERIES = [
    ("pack_version", 2, "another layout"),
    ("graph", "https://semantic-layer.19h09.co/graph/curated", "this reader is built for"),
    ("vocabulary_version", "0.0.1-forged", "this reader is built for"),
    ("content_media_type", "text/turtle", "this reader is built for"),
    ("source", "https://semantic-layer.19h09.co/l2/gitlab/gitlab-com", "the content says"),
    ("provider", "gitlab", "the content says"),
    ("api_root", "https://api.internal.example.com", "the content says"),
    (
        "trust_basis",
        "Authenticated read with organization admin scope; branch protection verified.",
        "the content says",
    ),
    ("target", "vvonkledge/semantic-layer", "the content says"),
    ("observed_at", "2026-08-30T23:59:59Z", "the content says"),
    ("fresh_until", "2027-01-01T00:00:00Z", "the content says"),
    ("snapshot_digest", "sha256:" + "0" * 64, "the content says"),
    (
        "observation",
        "https://semantic-layer.19h09.co/l2/github/api-github-com/observation/" + "0" * 64,
        "does not contain it",
    ),
    ("content_digest", "sha256:" + "0" * 64, "do not belong to each other"),
    ("content_bytes", 1, "the manifest claims"),
    ("artifact_count", 99, "the content holds"),
]


def test_every_manifest_field_is_one_this_suite_forges():
    """The code and this file enumerate the same fields, or one of them is lying.

    ``verify`` refuses a manifest whose fields are not exactly ``MANIFEST_FIELDS``, and
    every field in that set has a forgery below. Adding a manifest key therefore fails
    here first, rather than shipping a field a consumer reads and nothing holds.
    """
    built = json.loads(pack.build(pack.accepted(), pack.accepted_observation()).manifest)
    assert set(built) == pack.MANIFEST_FIELDS
    assert {field for field, _, _ in FORGERIES} == pack.MANIFEST_FIELDS


@pytest.mark.parametrize(
    ("field", "value", "message"), FORGERIES, ids=[field for field, _, _ in FORGERIES]
)
def test_every_manifest_field_is_held_against_content_or_a_trusted_constant(
    committed, field, value, message
):
    """Each field forged on its own, with the content left exactly as it was.

    A manifest is read first and believed, so a field that survives being rewritten is
    a field a consumer can be handed a lie in - and the one that matters most is
    ``trust_basis``, which is the field this repository tells a consumer to weigh
    before acting. Source and target are pinned to the honest values, so an expectation
    the consumer supplied cannot be what does the refusing here.
    """
    honest = json.loads(committed.manifest)
    assert honest[field] != value, f"{field} is forged to the value it already had"
    with pytest.raises(pack.PackError, match=message):
        pack.verify(
            committed.content,
            amended(committed, **{field: value}).manifest,
            as_of=honest["observed_at"],
            expect_source=honest["source"],
            expect_target=honest["target"],
        )


def test_a_manifest_carrying_a_field_nothing_holds_is_refused(committed):
    """Refused rather than partly checked.

    Ignoring an unknown field is how a manifest grows a claim no verification looks at:
    the producer writes it, the consumer reads it, and the check in between passes
    because it never heard of it.
    """
    with pytest.raises(pack.PackError, match="no rule for"):
        pack.verify(
            committed.content,
            amended(committed, invented_field="believe me").manifest,
            as_of=_within(committed),
        )


def test_a_manifest_missing_a_field_is_refused(committed):
    manifest = json.loads(committed.manifest)
    del manifest["trust_basis"]
    with pytest.raises(pack.PackError, match="lacks \\['trust_basis'\\]"):
        pack.verify(committed.content, pack.render(manifest), as_of=_within(committed))


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
            as_of=_within(committed),
            expect_source="https://semantic-layer.19h09.co/l2/github/github-example-org",
        )


def test_a_pack_about_another_target_is_refused(committed):
    with pytest.raises(pack.PackError, match="was expected"):
        pack.verify(
            committed.content,
            committed.manifest,
            as_of=_within(committed),
            expect_target="vvonkledge/semantic-layer",
        )


def test_a_manifest_that_is_not_json_is_refused(committed):
    with pytest.raises(pack.PackError, match="not valid JSON"):
        pack.verify(committed.content, b"{", as_of=_within(committed))


## What a consumer must refuse without being handed a traceback.
#
# A forgery is a manifest that lies in a field's own vocabulary. The tests below are
# the other half: a manifest that does not speak that vocabulary at all. Both halves
# of a pack, and the instant the consumer supplies, are values somebody else wrote, so
# every one of them can arrive as any JSON value or as no value. The documented answer
# to all of it is one catchable ``PackError``, and a refusal that escapes as a library
# exception is not caught by the `except pack.PackError` this repository tells a
# consumer to write.


#: Shapes no manifest field's rule can read. ``true`` is here because ``bool`` is an
#: ``int`` in Python, so a counted field would otherwise accept it and compare equal
#: to 1.
HOSTILE_SHAPES = (None, True, [], {}, 1.5)


def _hostile(field):
    """The shapes that are wrong for one field, including the one the other kind reads."""
    return (*HOSTILE_SHAPES, "1" if field in pack.COUNTED_FIELDS else 1)


SHAPES = [(field, value) for field in sorted(pack.MANIFEST_FIELDS) for value in _hostile(field)]


def test_every_manifest_field_has_a_shape_this_suite_drives():
    """The shape rule is derived from the field set, and this is what says so.

    ``COUNTED_FIELDS`` names the numbers and every other manifest field is text, so a
    field added to the manifest gets a shape rule without anybody remembering to write
    one - and gets driven below without anybody remembering to add it.
    """
    assert pack.COUNTED_FIELDS < pack.MANIFEST_FIELDS
    assert {field for field, _ in SHAPES} == pack.MANIFEST_FIELDS


@pytest.mark.parametrize(
    ("field", "value"), SHAPES, ids=[f"{field}={value!r}" for field, value in SHAPES]
)
def test_a_manifest_field_of_another_shape_is_refused_by_name(committed, field, value):
    """Every field, against every shape its rule cannot read.

    This is the class QA reproduced: ``"observation": null`` and ``"observation": 5``
    reached ``URIRef`` and came back out of rdflib as ``TypeError``, which the refusal
    a consumer is told to catch does not catch. A shape is not a lie about the source -
    it is a value no rule below was written for - so it is refused before any rule runs
    and the message names the field and what belongs there.
    """
    with pytest.raises(pack.PackError) as refusal:
        pack.verify(
            committed.content,
            amended(committed, **{field: value}).manifest,
            as_of=_within(committed),
        )
    reads = "a whole number" if field in pack.COUNTED_FIELDS else "text"
    assert f"the manifest says {field} is {value!r}" in str(refusal.value)
    assert f"this reader reads {reads} there" in str(refusal.value)


def test_a_manifest_that_does_not_say_which_layout_it_is_in_is_refused(committed):
    manifest = json.loads(committed.manifest)
    del manifest[pack.VERSION_FIELD]
    with pytest.raises(pack.PackError, match="declares no pack_version"):
        pack.verify(committed.content, pack.render(manifest), as_of=_within(committed))


#: Comparison instants that are not one: four shapes no pattern can be matched
#: against, and five strings that are not the one spelling a pack is compared in.
HOSTILE_INSTANTS = [
    None,
    5,
    [],
    {},
    "",
    "2026-08-30",
    "not-an-instant",
    "2026-08-30T07:00:00",
    "2026-08-30T07:00:00+02:00",
]


@pytest.mark.parametrize("as_of", HOSTILE_INSTANTS, ids=repr)
def test_a_comparison_instant_that_is_not_an_instant_is_refused(committed, as_of):
    """Rather than compared as a string and quietly answered.

    A timezone-less instant and one carrying an offset are refused with the malformed
    ones on purpose: a pack is compared by string against a manifest this repository
    spells one way, so an instant spelled another way is a question this cannot answer
    rather than one it should answer approximately.
    """
    with pytest.raises(pack.PackError, match="not a UTC instant"):
        pack.verify(committed.content, committed.manifest, as_of=as_of)


def test_an_explicit_utc_instant_still_decides_freshness(committed):
    """The guard above refuses shapes, and changes nothing about the instants that pass."""
    stated = json.loads(committed.manifest)
    assert pack.verify(committed.content, committed.manifest, as_of=stated["observed_at"])
    with pytest.raises(pack.PackError, match="stops being worth believing"):
        pack.verify(committed.content, committed.manifest, as_of=stated["fresh_until"])


#: Content whose bytes are not a graph. Each is paired with a manifest that agrees with
#: it, so the digest check passes and what refuses is the parse: content that fails to
#: parse must be refused as content this reader cannot read, not as content that was
#: tampered with.
UNPARSEABLE = [
    ("prose", b"this is not n-triples\n"),
    ("a truncated triple", b"<https://example.org/a> <https://example.org/b>\n"),
    ("turtle", b"@prefix ex: <https://example.org/> .\nex:a ex:b ex:c .\n"),
    ("bytes that are not utf-8", b"\xff\xfe<https://example.org/a>\n"),
]


@pytest.mark.parametrize(("what", "content"), UNPARSEABLE, ids=[what for what, _ in UNPARSEABLE])
def test_content_that_is_not_a_graph_is_refused_rather_than_raised(committed, what, content):
    """The pack is internally consistent and still not readable, which is its own answer.

    Nothing here was tampered with in transit - the digest and the length agree with the
    bytes - so the refusal cannot come from the checks above it. What arrived is not a
    graph, and saying so is what tells a consumer they were sent the wrong thing rather
    than a corrupted copy of the right one.
    """
    manifest = amended(
        committed, content_digest=github.digest_of(content), content_bytes=len(content)
    ).manifest
    with pytest.raises(pack.PackError, match="not N-Triples this reader can parse"):
        pack.verify(content, manifest, as_of=_within(committed))


@pytest.mark.parametrize(
    ("content", "manifest"), [(None, None), ("text", "text"), (bytearray(b""), bytearray(b""))]
)
def test_a_pack_half_that_is_not_bytes_is_refused(content, manifest):
    """Both halves are read as bytes - hashed, measured, parsed - so both are held to it."""
    with pytest.raises(pack.PackError, match="a pack half is the bytes"):
        pack.verify(content, manifest, as_of="2026-08-30T07:00:00Z")


def test_packing_something_that_is_not_an_observation_is_refused():
    with pytest.raises(pack.PackError, match="not an observation"):
        pack.build(
            graph.turtle_files(graph.TECHNICAL_DIR),
            URIRef(
                "https://semantic-layer.19h09.co/l2/github/api-github-com/repository/1347717349"
            ),
        )


def test_hostile_source_text_survives_the_whole_path():
    """Captured response to reconciled graph to pack to a verified pack, once, together.

    Each stage is covered on its own elsewhere, and this is the one that would have
    caught what none of those did: the reconciler wrote Turtle correctly, the pack wrote
    it as N-Triples with Turtle's quoting, and a repository name with a line break in
    it produced a pack that looked fine and that no consumer could parse. A
    composition bug is only visible from the composition.
    """
    snapshot, digest = github.read_snapshot(github.snapshot_path())
    snapshot = json.loads(json.dumps(snapshot))
    snapshot["repository"]["name"] = 'a "quoted" name\nwith a newline'
    snapshot["repository"]["full_name"] = "vvonkledge/back\\slash"
    snapshot["repository"]["owner"]["login"] = "control\x01characters"
    snapshot["branches"]["items"][0]["name"] = "release/1.4 ☃"
    snapshot["repository"]["default_branch"] = "release/1.4 ☃"

    reconciled = github.reconcile(snapshot, digest=digest)
    observed = graph.observed_data_graph(reconciled).graph(graph.OBSERVED_GRAPH)
    assert graph.validate(graph.observed_data_graph(reconciled)).conforms

    observation = next(iter(observed.subjects(RDF.type, graph.TECH.Observation)))
    built = pack.build(observed, observation)

    pack.verify(built.content, built.manifest, as_of=_within(built))
    assert set(graph.load_text(built.content.decode())) == set(
        Graph().parse(data=built.content, format="nt")
    )
    assert pack.build(observed, observation).content == built.content
