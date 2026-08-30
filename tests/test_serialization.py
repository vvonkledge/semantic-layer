"""Both syntaxes survive whatever a source puts in a string.

Turtle is committed and read by a person; N-Triples is hashed and read by a machine
that has never met this repository. The two escape differently, and the failure that
matters is the quiet one: Turtle's quoting handed to an N-Triples writer produces a
file that looks fine and that nothing can parse, discovered by whoever received it.

Everything here is a round trip, because "it serialized" is not the claim. The claim is
that the graph comes back.
"""

import pytest
from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import XSD

from semantic_layer import serialize

SUBJECT = URIRef("https://semantic-layer.19h09.co/l2/github/api-github-com/repository/1")
PREDICATE = URIRef("https://semantic-layer.19h09.co/vocab/tech#repositoryPath")

#: What a repository description, a branch name or an account login can hold. GitHub
#: does not promise any of these will be absent, and each one breaks a different half of
#: a hand-written escaper.
HOSTILE = [
    "a newline\nand another\r\n",
    'a "quoted" phrase',
    "a backslash \\ and a \\\\ pair",
    'ends with a quote"',
    '"""a triple-quoted run"""',
    "a tab\there",
    "control characters \x00\x01\x1f",
    "unicode é ☃ 🙂",
    "a turtle comment # not a comment",
    "<https://not-an-iri>",
    "^^xsd:integer",
    "",
]


def _graph(value, **kwargs):
    graph = Graph()
    graph.add((SUBJECT, PREDICATE, Literal(value, **kwargs)))
    return graph


@pytest.mark.parametrize("value", HOSTILE, ids=repr)
@pytest.mark.parametrize(
    ("write", "syntax"),
    [(serialize.turtle, "turtle"), (serialize.ntriples, "nt")],
    ids=["turtle", "n-triples"],
)
@pytest.mark.parametrize(
    "typed", [{}, {"datatype": XSD.string}, {"lang": "en"}], ids=["plain", "typed", "tagged"]
)
def test_a_hostile_literal_comes_back(value, write, syntax, typed):
    graph = _graph(value, **typed)
    written = write(graph)
    assert set(Graph().parse(data=written, format=syntax)) == set(graph)


@pytest.mark.parametrize("value", HOSTILE, ids=repr)
def test_writing_is_a_fixed_point(value):
    """Written, parsed and written again is the same bytes.

    Not the same claim as round-tripping: this is what makes a committed graph stable
    under a reader that happened to normalize something, and it is the property a
    reviewer relies on when they read a refresh as a diff.
    """
    graph = _graph(value)
    turtle = serialize.turtle(graph)
    assert serialize.turtle(Graph().parse(data=turtle, format="turtle")) == turtle

    ntriples = serialize.ntriples(graph)
    assert serialize.ntriples(Graph().parse(data=ntriples, format="nt")) == ntriples


def test_an_instant_keeps_the_spelling_it_was_given():
    """rdflib normalizes a typed literal on construction; the reconciler asks it not to.

    The two spellings mean the same instant and compare the same. The committed graph is
    read beside the committed capture, and a reviewer should not have to work out which
    of the two rewrote the other.
    """
    graph = Graph()
    graph.add(
        (
            SUBJECT,
            PREDICATE,
            Literal("2026-08-30T06:07:15Z", datatype=XSD.dateTime, normalize=False),
        )
    )
    assert '"2026-08-30T06:07:15Z"^^xsd:dateTime' in serialize.turtle(graph)


def test_the_order_of_the_triples_does_not_reach_the_output():
    forward, backward = Graph(), Graph()
    triples = [
        (SUBJECT, PREDICATE, Literal("one")),
        (SUBJECT, PREDICATE, Literal("two")),
        (URIRef("https://semantic-layer.19h09.co/a"), PREDICATE, Literal("three")),
    ]
    for triple in triples:
        forward.add(triple)
    for triple in reversed(triples):
        backward.add(triple)
    assert serialize.turtle(forward) == serialize.turtle(backward)
    assert serialize.ntriples(forward) == serialize.ntriples(backward)


@pytest.mark.parametrize(
    "write", [serialize.turtle, serialize.ntriples], ids=["turtle", "n-triples"]
)
def test_a_blank_node_is_refused_rather_than_labelled(write):
    """rdflib mints blank-node labels at parse time, so two writes of one graph would
    differ in nothing but the labels - which is a diff a reviewer cannot read and a
    digest a consumer cannot reproduce.
    """
    graph = Graph()
    graph.add((BNode(), PREDICATE, Literal("anonymous")))
    with pytest.raises(serialize.SerializationError, match="no stable name"):
        write(graph)
