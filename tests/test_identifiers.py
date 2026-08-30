"""Identifiers are minted one way, and every committed entity uses that way.

This is what makes a slug a stable identity rather than a filename: an entity's IRI
is a function of its kind and its slug, so the same entity cannot be written down
twice under two spellings.
"""

import pytest
from rdflib import RDF, URIRef

from semantic_layer import graph, ids


def test_mint_places_an_entity_under_the_permanent_base():
    assert (
        ids.mint("capability", "payment-processing")
        == "https://semantic-layer.19h09.co/biz/capability/payment-processing"
    )


def test_fixtures_are_minted_under_a_namespace_curated_content_never_uses():
    assert (
        ids.mint("goal", "checkout-reliability", fixture=True)
        == "https://semantic-layer.19h09.co/fixture/biz/goal/checkout-reliability"
    )
    assert ids.FIXTURE_SEGMENT not in ids.mint("goal", "checkout-reliability")


@pytest.mark.parametrize(
    "slug",
    ["Payment-Processing", "payment_processing", "payment--processing", "-payments", "", "a/b"],
)
def test_a_slug_that_could_be_written_two_ways_is_rejected(slug):
    with pytest.raises(ids.IdentifierError):
        ids.mint("capability", slug)


def test_an_unknown_entity_kind_is_rejected():
    with pytest.raises(ids.IdentifierError):
        ids.mint("service", "payment-gateway")


@pytest.mark.parametrize("fixture", [False, True])
def test_parse_is_the_inverse_of_mint(fixture):
    slug = "investigate-payment-declines"
    iri = ids.mint("assignment", slug, fixture=fixture)
    assert ids.parse(iri) == ids.Identifier("assignment", slug, fixture)


@pytest.mark.parametrize(
    "iri",
    [
        "https://example.org/biz/capability/payments",
        "https://semantic-layer.19h09.co/biz/service/payments",
        "https://semantic-layer.19h09.co/biz/capability/Payments",
        "https://semantic-layer.19h09.co/biz/capability/payments/extra",
    ],
)
def test_parse_rejects_anything_minting_would_not_have_produced(iri):
    with pytest.raises(ids.IdentifierError):
        ids.parse(iri)


def _typed_entities(paths):
    """Every business entity in ``paths`` that has an identifier to check.

    Whether an entity has one at all is `shp:IdentityShape`'s question, not this
    file's, which is why a blank node is skipped here rather than failed: the invalid
    fixtures deliberately contain one, and it is the shape that must reject it.
    """
    data = graph.load(paths)
    for subject, _, rdf_class in data.triples((None, RDF.type, None)):
        if isinstance(subject, URIRef) and str(rdf_class).startswith(str(graph.BIZ)):
            yield subject, rdf_class


@pytest.mark.parametrize(
    ("directory", "fixture"),
    [
        (graph.BUSINESS_DIR, False),
        (graph.VALID_FIXTURES_DIR, True),
        (graph.INVALID_FIXTURES_DIR, True),
        # The technical directories hold business entities too: the fixture that proves
        # an L1 entity cannot be smuggled in as observed truth is a business entity
        # committed there on purpose, and it is minted like any other.
        (graph.TECHNICAL_DIR, False),
        (graph.TECHNICAL_VALID_FIXTURES_DIR, True),
        (graph.TECHNICAL_INVALID_FIXTURES_DIR, True),
    ],
    ids=[
        "business",
        "valid-fixtures",
        "invalid-fixtures",
        "technical",
        "technical-valid-fixtures",
        "technical-invalid-fixtures",
    ],
)
def test_every_committed_entity_carries_the_identifier_minting_would_give_it(directory, fixture):
    for subject, rdf_class in _typed_entities(graph.turtle_files(directory)):
        kind = ids.KIND_BY_CLASS.get(str(rdf_class))
        assert kind is not None, f"{subject} is typed {rdf_class}, which mints no identifier"
        identifier = ids.parse(str(subject))
        assert identifier.kind == kind, f"{subject} is a {kind} but its IRI says {identifier.kind}"
        assert identifier.fixture is fixture, (
            f"{subject} lives in {directory.name} but is minted in the wrong namespace"
        )


def test_curated_content_names_no_fixture_identifier():
    """Not one, in any position, in the one directory that speaks for the organization.

    The check above holds every entity the curated files *declare*, which is not the
    whole risk: a curated capability owned by a fixture team, or serving a fixture goal,
    declares nothing wrong and validates - the fixture end is a real, well-formed entity
    committed elsewhere. What would be wrong is the sentence, and the graph would go on
    saying it. So the fixture namespaces are refused here wherever they appear, and a
    statement about the organization can never have an invented thing on either end of
    it.
    """
    invented = (
        f"{ids.BASE}{ids.FIXTURE_SEGMENT}",
        f"{ids.BASE}{ids.FIXTURE_OBSERVED_SEGMENT}",
    )
    for triple in graph.load(graph.turtle_files(graph.BUSINESS_DIR)):
        for term in triple:
            assert not str(term).startswith(invented), (
                f"curated business content names the fixture identifier {term}"
            )
