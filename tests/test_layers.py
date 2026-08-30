"""The three layers stay apart, and the one edge between the first two points one way.

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
TRACE = "https://semantic-layer.19h09.co/vocab/trace#"


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
        (graph.TRACE_VALID_FIXTURES_DIR, graph.EVIDENCE_GRAPH),
        (graph.TRACE_INVALID_FIXTURES_DIR, graph.EVIDENCE_GRAPH),
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


def test_every_graph_stays_distinguishable(committed_instances):
    """Each vocabulary and each layer's data, nameable on its own and sharing nothing."""
    dataset = graph.data_graph(committed_instances)
    names = {
        "core vocabulary": URIRef("https://semantic-layer.19h09.co/vocab/core"),
        "business vocabulary": URIRef("https://semantic-layer.19h09.co/vocab/biz"),
        "technical vocabulary": URIRef("https://semantic-layer.19h09.co/vocab/tech"),
        "execution-trace vocabulary": URIRef("https://semantic-layer.19h09.co/vocab/trace"),
        "curated business truth": graph.CURATED_GRAPH,
        "observed technical truth": graph.OBSERVED_GRAPH,
        "recorded evidence": graph.EVIDENCE_GRAPH,
    }
    for what, name in names.items():
        assert len(dataset.graph(name)) > 0, f"the {what} graph is empty"

    data = [
        set(dataset.graph(name))
        for name in (graph.CURATED_GRAPH, graph.OBSERVED_GRAPH, graph.EVIDENCE_GRAPH)
    ]
    for index, triples in enumerate(data):
        for other in data[index + 1 :]:
            assert triples & other == set()


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


def test_the_trace_vocabulary_is_loaded_as_evidence(committed_instances):
    """Evidence is where a run is recorded, and it is not either of the other two."""
    dataset = graph.data_graph(committed_instances)
    evidence = dataset.graph(graph.EVIDENCE_GRAPH)
    assert list(evidence.subjects(RDF.type, graph.TRACE.Run))
    for other in (graph.CURATED_GRAPH, graph.OBSERVED_GRAPH):
        assert not list(dataset.graph(other).subjects(RDF.type, graph.TRACE.Run))


def test_recorded_evidence_declares_no_business_or_technical_entity(committed_instances):
    """A trace names L1 and L2 nodes, as objects, and authors none of them.

    The same distinction the observed graph is held to, one layer up: being named is
    not being asserted, and it is the difference the whole boundary rests on. The
    committed trace fixture names an agent identity and a repository, so a change that
    let a run author one would fail here as well as at the shape.
    """
    dataset = graph.data_graph(committed_instances)
    evidence = dataset.graph(graph.EVIDENCE_GRAPH)
    for subject in set(evidence.subjects()):
        assert str(subject).startswith("https://semantic-layer.19h09.co/fixture/l3/")
    named = {str(obj) for obj in evidence.objects()}
    assert any(name.startswith("https://semantic-layer.19h09.co/fixture/biz/") for name in named)
    assert any(name.startswith("https://semantic-layer.19h09.co/fixture/l2/") for name in named)


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


def test_the_trace_vocabulary_defines_no_term_of_another_layer():
    """It reuses PROV-O and points at L1 and L2, and defines neither.

    A trace vocabulary that declared a business or technical term would widen both
    boundary shapes with no other edit anywhere, because each of them asks a vocabulary
    what that vocabulary defines. Reusing prov: is not the same thing and is the point:
    those terms are declared by PROV-O, which this repository does not own.
    """
    trace = _vocabulary("trace.ttl")
    declared = list(trace.subjects(RDFS.isDefinedBy, None))
    assert not [term for term in declared if str(term).startswith(BIZ)]
    assert not [term for term in declared if str(term).startswith(TECH)]
    prov = "http://www.w3.org/ns/prov#"
    assert [term for term in trace.all_nodes() if str(term).startswith(prov)]


def test_no_vocabulary_defines_another_or_the_core():
    """Each term is defined by exactly one vocabulary, which is what the shapes ask."""
    for name, namespace in (
        ("biz.ttl", BIZ),
        ("tech.ttl", TECH),
        ("core.ttl", CORE),
        ("trace.ttl", TRACE),
    ):
        vocabulary = _vocabulary(name)
        for subject in vocabulary.subjects(RDFS.isDefinedBy, None):
            assert str(subject).startswith(namespace), (
                f"{name} declares {subject}, which is not its own term"
            )
