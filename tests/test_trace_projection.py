"""The PROV summary: deterministic, readable without this vocabulary, and asserting nothing.

The span store holds the detail and the graph holds the summary. What is tested here is
the three things that make the summary worth projecting at all: that it is a function of
the record and nothing else, that a consumer who speaks only PROV-O can read it, and
that it names L1 and L2 nodes without ever stating anything about them.

The last of those is also tested from the other side - as a shape, with a negative
fixture committing its message, under ontology/instances/fixtures/trace/invalid/. Both
are needed: the shape says a graph like that is refused, and this says the projector
does not write one.
"""

import hashlib

import pytest
from rdflib import RDF, Graph, Literal, URIRef
from rdflib.namespace import RDFS, XSD
from trace_runs import AGENT, AS_OF, REPOSITORY, TRACE_ID, run

from semantic_layer import graph as layer
from semantic_layer import ids
from semantic_layer.serialize import ntriples

PROV = layer.PROV
TRACE = layer.TRACE

RUN_IRI = URIRef(ids.mint_trace("run", TRACE_ID))


@pytest.fixture
def recorded(store, accepted_pack):
    store.record(run(), pack=accepted_pack, as_of=AS_OF)
    return store


@pytest.fixture
def summary(recorded):
    return recorded.summary(TRACE_ID)


def _digest(graph: Graph) -> str:
    return hashlib.sha256(ntriples(graph).encode()).hexdigest()


## Deterministic.


def test_two_projections_of_one_run_are_the_same_bytes(recorded, summary):
    """Which is what lets a consumer hash a summary and compare it with whoever sent one.

    Nothing in the projection reads a clock, an insertion order or a counter: every
    identifier is minted from the run's own content, so the same record projects to the
    same triples however many times it is asked.
    """
    assert _digest(recorded.summary(TRACE_ID)) == _digest(summary)


def test_the_summary_survives_a_round_trip_through_the_store(tmp_path, accepted_pack):
    """A summary is projected from what the store holds, not from the object in hand."""
    from semantic_layer.trace import TraceStore

    path = tmp_path / "trace.sqlite3"
    with TraceStore.open(path) as opened:
        opened.record(run(), pack=accepted_pack, as_of=AS_OF)
        first = _digest(opened.summary(TRACE_ID))
    with TraceStore.open(path) as reopened:
        assert _digest(reopened.summary(TRACE_ID)) == first


## What it says.


def test_the_summary_names_the_run_and_the_exact_pack_it_used(recorded, summary):
    pack = recorded.read(TRACE_ID).pack
    pack_iri = URIRef(ids.mint_trace("pack", pack.identity))

    assert (RUN_IRI, TRACE.traceId, None) in summary
    assert list(summary.objects(RUN_IRI, TRACE.usedPack)) == [pack_iri]
    assert set(summary.objects(pack_iri, TRACE.contentDigest)) == {Literal(pack.content_digest)}
    assert list(summary.objects(pack_iri, TRACE.packObservation)) == [URIRef(pack.observation)]


def test_a_run_has_exactly_one_pack_however_the_summary_is_read(summary):
    """The cardinality the whole model turns on, asserted here as well as in the shapes."""
    runs = set(summary.subjects(RDF.type, TRACE.Run))
    assert len(runs) == 1
    for run_iri in runs:
        assert len(list(summary.objects(run_iri, TRACE.usedPack))) == 1


def test_the_run_is_an_activity_and_its_rollups_are_entities(summary):
    """PROV-O reused rather than re-invented, and materialized rather than inferred.

    No reasoner is ever run in this repository, so rdfs:subClassOf in the vocabulary is
    documentation. Writing both types is what makes the interoperability claim true: a
    lineage or audit tool that speaks only PROV reads this with no integration work.
    """
    activities = set(summary.subjects(RDF.type, PROV.Activity))
    entities = set(summary.subjects(RDF.type, PROV.Entity))

    assert RUN_IRI in activities
    assert activities == set(summary.subjects(RDF.type, TRACE.Run)) | set(
        summary.subjects(RDF.type, TRACE.Span)
    )
    assert entities == {
        subject
        for kind in (TRACE.ContextPack, TRACE.Outcome, TRACE.Metric, TRACE.Finding)
        for subject in summary.subjects(RDF.type, kind)
    }
    assert activities and entities
    assert not activities & entities


def test_a_consumer_that_speaks_only_prov_can_read_the_whole_shape(summary):
    """Asked with PROV terms alone, having never been told this vocabulary exists."""
    prov_only = Graph()
    for subject, predicate, obj in summary:
        if str(predicate).startswith(str(PROV)) or predicate == RDF.type:
            if predicate == RDF.type and not str(obj).startswith(str(PROV)):
                continue
            prov_only.add((subject, predicate, obj))

    assert len(set(prov_only.subjects(RDF.type, PROV.Activity))) == 3
    assert len(set(prov_only.subjects(RDF.type, PROV.Entity))) == 6
    assert list(prov_only.objects(RUN_IRI, PROV.used))
    assert list(prov_only.objects(RUN_IRI, PROV.wasAssociatedWith)) == [URIRef(AGENT)]
    assert list(prov_only.objects(RUN_IRI, PROV.startedAtTime))
    assert len(list(prov_only.subject_objects(PROV.wasGeneratedBy))) == 5
    assert len(list(prov_only.subject_objects(PROV.wasInformedBy))) == 3


def test_the_summary_names_l1_and_l2_nodes_and_states_nothing_about_them(summary):
    """Naming is what a trace is for; asserting is the one thing it may never do."""
    named = {URIRef(AGENT), URIRef(REPOSITORY)}
    assert named <= set(summary.objects())
    for node in named:
        assert list(summary.predicate_objects(node)) == []


def test_the_summary_asserts_no_business_or_technical_predicate(summary):
    """The boundary, read off the vocabularies rather than off a list kept by hand."""
    defined = set()
    for name in ("biz.ttl", "tech.ttl"):
        vocabulary = Graph().parse(layer.ONTOLOGY / name, format="turtle")
        defined |= set(vocabulary.subjects(RDFS.isDefinedBy))
    assert defined
    assert not defined & set(summary.predicates())


def test_the_summary_validates_as_evidence(summary):
    report = layer.validate(layer.evidence_data_graph(summary))
    assert report.conforms, report.text


## After retention.


@pytest.fixture
def expired(recorded):
    recorded.expire_spans(as_of="2027-01-01T00:00:00Z")
    return recorded.summary(TRACE_ID)


def test_the_summary_is_still_valid_once_the_span_detail_has_gone(expired):
    report = layer.validate(layer.evidence_data_graph(expired))
    assert report.conforms, report.text


def test_the_rollups_and_the_pack_binding_outlive_the_spans(expired, recorded):
    pack = recorded.read(TRACE_ID).pack

    assert set(expired.subjects(RDF.type, TRACE.Span)) == set()
    assert list(expired.objects(RUN_IRI, TRACE.usedPack)) == [
        URIRef(ids.mint_trace("pack", pack.identity))
    ]
    assert len(set(expired.subjects(RDF.type, TRACE.Metric))) == 2
    assert len(set(expired.subjects(RDF.type, TRACE.Finding))) == 2
    assert len(set(expired.subjects(RDF.type, TRACE.Outcome))) == 1


def test_an_expired_run_says_the_detail_expired_rather_than_that_there_was_none(expired):
    """A run is never recorded with no spans, so the absence would be readable either way.

    It is written down anyway, because "readable either way" means a reader has to know
    that rule to draw the conclusion, and evidence should not require the reader to
    reconstruct the policy that produced it.
    """
    expired_at = list(expired.objects(RUN_IRI, TRACE.spanDetailExpiredAt))
    assert len(expired_at) == 1
    # Spelled with the trailing Z this repository writes, not the +00:00 rdflib would
    # normalize it to: a summary is hashed and compared by whoever receives it.
    assert str(expired_at[0]) == "2026-10-03T00:00:00Z"
    assert expired_at[0].datatype == XSD.dateTime


## Nothing else moves.


def test_no_trace_path_writes_to_curated_truth_observed_truth_a_capture_or_a_pack(
    tmp_path, accepted_pack
):
    """The strongest form of "evidence never writes truth": nothing on disk moves.

    A shape refuses a trace graph that states an L1 or L2 fact. This is the other half:
    recording a run, expiring it and projecting it touches no file outside the store,
    so there is no path through this library that edits the layers below it, whatever
    a graph it produced would have been allowed to say.
    """
    from semantic_layer.trace import TraceStore

    watched = sorted(
        path
        for directory in (layer.ONTOLOGY, layer.SOURCES_DIR, layer.PACKS_DIR)
        for path in directory.rglob("*")
        if path.is_file()
    )
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in watched}
    assert len(before) > 50

    with TraceStore.open(tmp_path / "trace.sqlite3") as opened:
        opened.record(run(), pack=accepted_pack, as_of=AS_OF)
        opened.summary(TRACE_ID)
        opened.expire_spans(as_of="2027-01-01T00:00:00Z")
        opened.summary(TRACE_ID)

    after = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in watched}
    assert after == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["trace.sqlite3"]
