"""The two layers stay apart, and the one edge between them points one way.

Three mechanisms hold that, and each is tested here rather than trusted. The loader
puts a file in a named graph chosen by the directory it sits in, and no file can say
otherwise. Each vocabulary loads into a named graph of its own, so only a vocabulary
can say what a vocabulary defines. And the vocabularies themselves name each other in
exactly one place, in one direction.

The shapes that act on all of this are covered by the negative fixtures. What is here
is the part underneath them: if the loader stopped distinguishing the graphs, every one
of those shapes would go quiet and every fixture would still be rejected for something.
"""

import pytest
from rdflib import Graph, URIRef
from rdflib.namespace import RDF, RDFS

from semantic_layer import graph

BIZ = "https://semantic-layer.19h09.co/vocab/biz#"
TECH = "https://semantic-layer.19h09.co/vocab/tech#"
CORE = "https://semantic-layer.19h09.co/vocab/core#"


## The loader.


@pytest.mark.parametrize(
    ("directory", "expected"),
    [
        (graph.BUSINESS_DIR, graph.CURATED_GRAPH),
        (graph.VALID_FIXTURES_DIR, graph.CURATED_GRAPH),
        (graph.INVALID_FIXTURES_DIR, graph.CURATED_GRAPH),
        (graph.TECHNICAL_DIR, graph.OBSERVED_GRAPH),
        (graph.TECHNICAL_VALID_FIXTURES_DIR, graph.OBSERVED_GRAPH),
        (graph.TECHNICAL_INVALID_FIXTURES_DIR, graph.OBSERVED_GRAPH),
    ],
    ids=lambda value: getattr(value, "name", str(value)),
)
def test_the_directory_decides_the_layer(directory, expected):
    assert graph.instance_graph(directory / "anything.ttl") == expected


def test_a_file_outside_the_instance_directories_is_refused(tmp_path):
    """Rather than defaulted into one layer or the other.

    Which layer a fact is in decides whether it may carry an expiry date, whether it may
    name a system, and whether it may name a capability. Guessing is not available.
    """
    with pytest.raises(graph.LayerError, match="no instance directory"):
        graph.instance_graph(tmp_path / "somewhere-else.ttl")


def test_all_four_graphs_stay_distinguishable(committed_instances):
    """L1 vocabulary, L1 data, L2 vocabulary and L2 data, each nameable on its own."""
    dataset = graph.data_graph(committed_instances)
    names = {
        "core vocabulary": URIRef("https://semantic-layer.19h09.co/vocab/core"),
        "business vocabulary": URIRef("https://semantic-layer.19h09.co/vocab/biz"),
        "technical vocabulary": URIRef("https://semantic-layer.19h09.co/vocab/tech"),
        "curated business truth": graph.CURATED_GRAPH,
        "observed technical truth": graph.OBSERVED_GRAPH,
    }
    for what, name in names.items():
        assert len(dataset.graph(name)) > 0, f"the {what} graph is empty"

    curated = dataset.graph(graph.CURATED_GRAPH)
    observed = dataset.graph(graph.OBSERVED_GRAPH)
    assert set(curated) & set(observed) == set()


def test_the_accepted_observation_is_loaded_as_observed(committed_instances):
    dataset = graph.data_graph(committed_instances)
    observed = dataset.graph(graph.OBSERVED_GRAPH)
    assert list(observed.subjects(RDF.type, graph.TECH.Repository))
    assert not list(dataset.graph(graph.CURATED_GRAPH).subjects(RDF.type, graph.TECH.Repository))


def test_no_curated_business_entity_is_loaded_as_observed(committed_instances):
    """What the import is forbidden from doing, checked against what is committed.

    The valid technical fixtures include the crossing edge, so a business capability is
    named in the observed graph - as an object. Being named is not being asserted, and
    the difference is the whole rule: L2 may point at L1 and may never author it.
    """
    dataset = graph.data_graph(committed_instances)
    observed = dataset.graph(graph.OBSERVED_GRAPH)
    for subject in set(observed.subjects()):
        assert not str(subject).startswith("https://semantic-layer.19h09.co/biz/")
        assert not str(subject).startswith("https://semantic-layer.19h09.co/fixture/biz/")
    assert any(
        str(obj).startswith("https://semantic-layer.19h09.co/fixture/biz/")
        for obj in observed.objects()
    ), "no crossing edge in the observed graph; this test is checking nothing"


def test_an_instance_file_cannot_reach_a_vocabulary_graph(committed_instances):
    """Turtle has no syntax for naming a graph, and that is what the boundaries rest on.

    Both boundary shapes ask a vocabulary which properties it defines, inside that
    vocabulary's own named graph. If an instance file could write there, either shape
    could be satisfied by the data it is judging - which is the breach
    technical-fact-defined-by-the-instance-file.ttl and
    technical-term-defined-by-the-observed-file.ttl are the fixtures for.
    """
    dataset = graph.data_graph(committed_instances)
    for iri, path in graph.VOCABULARIES.items():
        assert set(dataset.graph(iri)) == set(Graph().parse(path, format="turtle"))


## The vocabularies.


def _vocabulary(name):
    return Graph().parse(graph.ONTOLOGY / name, format="turtle")


def _defined_terms(vocabulary, namespace):
    return {
        subject
        for subject in vocabulary.subjects(RDFS.isDefinedBy, None)
        if str(subject).startswith(namespace)
    }


def test_the_business_vocabulary_names_no_technical_term():
    """The route a breach would take, and the reason it is a review question.

    The L1 boundary shape asks the business vocabulary what L1 defines, so adding a
    technical term there widens the boundary with no other edit anywhere. That makes it
    a conspicuous change to a small file, which is the point - and this is what makes it
    a failing build as well.
    """
    business = _vocabulary("biz.ttl")
    assert not [term for term in business.all_nodes() if str(term).startswith(TECH)]


def test_the_technical_vocabulary_crosses_upward_exactly_once():
    """One edge, one direction, one range.

    A capability has to survive the deletion of every system that ever delivered it, so
    there is no downward term and this is what would fail if one were added.
    """
    technical = _vocabulary("tech.ttl")
    crossings = {
        (str(subject), str(predicate), str(obj))
        for subject, predicate, obj in technical
        if str(obj).startswith(BIZ)
    }
    assert crossings == {
        (f"{TECH}realizes", str(RDFS.range), f"{BIZ}Capability"),
    }


def test_neither_vocabulary_defines_the_other_or_the_core():
    """Each term is defined by exactly one vocabulary, which is what the shapes ask."""
    for name, namespace in (("biz.ttl", BIZ), ("tech.ttl", TECH), ("core.ttl", CORE)):
        vocabulary = _vocabulary(name)
        for subject in vocabulary.subjects(RDFS.isDefinedBy, None):
            assert str(subject).startswith(namespace), (
                f"{name} declares {subject}, which is not its own term"
            )
