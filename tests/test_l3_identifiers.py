"""An L3 identifier is machine-minted from the run itself, and never authored.

The third of the three minting rules, and it is unlike both of the others. An L1 slug is
written by a person who will not change their mind quietly. An L2 local id is handed
over by a system that renames things without telling anyone, so it is scoped by the
source that issued it. An L3 identifier is neither: a run happened here, and this layer
is the only system that will ever name it.

So there is no scope and there is nothing authored. The trace and span ids come from the
tracer, the pack is named by a digest of the bytes it was, and everything else is named
by the run it belongs to. That is what makes recording the same run twice mint the same
identifiers - and it is what lets a replay be recognized as a replay rather than written
down as a second run.
"""

import pytest
from rdflib import RDF, URIRef

from semantic_layer import graph, ids

TRACE = "https://semantic-layer.19h09.co/vocab/trace#"
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"


def test_a_run_is_named_by_the_trace_id_the_tracer_emitted():
    assert ids.mint_trace("run", TRACE_ID) == f"https://semantic-layer.19h09.co/l3/run/{TRACE_ID}"


def test_a_span_is_named_by_its_run_and_then_by_itself():
    """Because a span id identifies an operation only within one trace."""
    assert ids.mint_trace("span", TRACE_ID, "00f067aa0ba902b7") == (
        f"https://semantic-layer.19h09.co/l3/span/{TRACE_ID}/00f067aa0ba902b7"
    )


def test_recording_the_same_run_twice_mints_the_same_identifiers():
    """Nothing here is drawn from a clock, a counter or a sequence."""
    assert ids.mint_trace("outcome", TRACE_ID) == ids.mint_trace("outcome", TRACE_ID)
    assert ids.mint_trace("metric", TRACE_ID, "branches-read") == ids.mint_trace(
        "metric", TRACE_ID, "branches-read"
    )


def test_fixtures_are_minted_under_a_namespace_no_recorded_run_ever_uses():
    assert (
        ids.mint_trace("run", TRACE_ID, fixture=True)
        == f"https://semantic-layer.19h09.co/fixture/l3/run/{TRACE_ID}"
    )
    assert ids.FIXTURE_TRACE_SEGMENT not in ids.mint_trace("run", TRACE_ID)


@pytest.mark.parametrize("fixture", [False, True])
def test_parse_is_the_inverse_of_mint(fixture):
    iri = ids.mint_trace("finding", TRACE_ID, "3", fixture=fixture)
    assert ids.parse_trace(iri) == ids.TraceIdentifier("finding", (TRACE_ID, "3"), fixture)


@pytest.mark.parametrize(
    "iri",
    [
        "https://example.org/l3/run/" + TRACE_ID,
        "https://semantic-layer.19h09.co/l2/github/api-github-com/repository/1",
        f"https://semantic-layer.19h09.co/l3/attempt/{TRACE_ID}",
        f"https://semantic-layer.19h09.co/l3/run/{TRACE_ID}/extra",
        "https://semantic-layer.19h09.co/l3/span/" + TRACE_ID,
        f"https://semantic-layer.19h09.co/l3/metric/{TRACE_ID}/branches%2fread",
    ],
    ids=[
        "another base",
        "an observed identifier",
        "a kind this layer does not record",
        "too many segments for a run",
        "too few segments for a span",
        "a lower-case percent escape",
    ],
)
def test_parse_rejects_anything_minting_would_not_have_produced(iri):
    with pytest.raises(ids.IdentifierError):
        ids.parse_trace(iri)


def test_a_local_id_a_path_resolver_would_collapse_is_refused():
    """Nothing resolves these, so it is not a vulnerability - it is an unstable name."""
    for segment in (".", ".."):
        with pytest.raises(ids.IdentifierError, match="collapse"):
            ids.mint_trace("metric", TRACE_ID, segment)


def _typed_trace_entities(paths):
    """Every trace entity in ``paths`` that has an identifier to check.

    Whether it has one at all is shpl:TraceIdentityShape's question, which is why a
    blank node is skipped here: one of the invalid fixtures is deliberately anonymous,
    and it is the shape that must reject it.
    """
    data = graph.load(paths)
    for subject, _, rdf_class in data.triples((None, RDF.type, None)):
        if isinstance(subject, URIRef) and str(rdf_class).startswith(TRACE):
            yield subject, rdf_class


@pytest.mark.parametrize(
    "directory",
    [
        graph.TRACE_VALID_FIXTURES_DIR,
        graph.TRACE_INVALID_FIXTURES_DIR,
        # The trace fixture filed as observed truth lives over there, and it is minted
        # like any other: what is wrong with it is where it sits, not what it is called.
        graph.TECHNICAL_INVALID_FIXTURES_DIR,
    ],
    ids=["valid-fixtures", "invalid-fixtures", "technical-invalid-fixtures"],
)
def test_every_committed_trace_entity_carries_the_identifier_minting_would_give_it(directory):
    found = False
    for subject, rdf_class in _typed_trace_entities(graph.turtle_files(directory)):
        found = True
        kind = ids.TRACE_KIND_BY_CLASS.get(str(rdf_class))
        assert kind is not None, f"{subject} is typed {rdf_class}, which mints no identifier"
        identifier = ids.parse_trace(str(subject))
        assert identifier.kind == kind, f"{subject} is a {kind} but its IRI says {identifier.kind}"
        assert identifier.fixture is True, (
            f"{subject} is test data and is minted in the namespace recorded runs use"
        )
    assert found, f"no trace entities in {directory}; this parametrization checks nothing"


def test_every_trace_class_the_vocabulary_defines_mints_an_identifier():
    """So a class added to the vocabulary cannot be committed with no minting rule."""
    from rdflib import Graph
    from rdflib.namespace import OWL, RDFS

    vocabulary = Graph().parse(graph.ONTOLOGY / "trace.ttl", format="turtle")
    classes = {
        str(subject)
        for subject in vocabulary.subjects(RDF.type, OWL.Class)
        if (subject, RDFS.isDefinedBy, None) in vocabulary
    }
    assert classes == set(ids.TRACE_KIND_BY_CLASS)
    assert set(ids.TRACE_KIND_BY_CLASS.values()) == ids.TRACE_KINDS
