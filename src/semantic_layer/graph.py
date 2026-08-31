"""Loading, validating and querying both layers.

The Turtle files are the contract. Everything here is a thin, deterministic wrapper
over rdflib and pyshacl so that tests, and any query path, read the same graph the same
way.

The one thing this module decides rather than wraps is which named graph a file loads
into, and ``data_graph`` says why that is the whole of what separates the layers.

No reasoner is ever run. ``sh:class`` already follows ``rdfs:subClassOf*``, so class
hierarchies work without inference, while ``rdfs:domain`` and ``rdfs:range`` stay
documentation. Turning inference on would materialize types from domain and range and
quietly disable every endpoint check.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from pyshacl import validate as _shacl_validate
from rdflib import Dataset, Graph, Namespace, URIRef
from rdflib.namespace import RDF, SH

BIZ = Namespace("https://semantic-layer.19h09.co/vocab/biz#")
TECH = Namespace("https://semantic-layer.19h09.co/vocab/tech#")
TRACE = Namespace("https://semantic-layer.19h09.co/vocab/trace#")
PROV = Namespace("http://www.w3.org/ns/prov#")

#: The checkout this package was written in, which exists only when it is being read
#: out of one. Everything reached through it is site data - a capture, an accepted
#: instance file, a committed pack, a committed query - and none of it is packaged,
#: because it is this installation's content rather than the library's.
ROOT = Path(__file__).resolve().parents[2]

#: The vocabularies and shapes as an installed wheel carries them: beside the code,
#: because they are the contract the code compiles against and a consumer who pip
#: installed this has no checkout to read them out of.
PACKAGED_ONTOLOGY = Path(__file__).resolve().parent / "_ontology"

#: Which of the two this installation reads. There is one rule and it lives here: the
#: packaged copy if there is one, and the checkout otherwise. A wheel has the first and
#: not the second; a checkout has the second and not the first. Nothing else in this
#: repository asks the question, so a build that forgets to package a vocabulary is a
#: build that reads the checkout beside it and looks fine - which is exactly why
#: tests/test_packaging.py builds the wheel and reads the answer out of it instead.
ONTOLOGY = PACKAGED_ONTOLOGY if PACKAGED_ONTOLOGY.is_dir() else ROOT / "ontology"
SHAPES_DIR = ONTOLOGY / "shapes"

#: Instance files are never packaged and are always the checkout's: fixtures are the
#: suite's, and business and technical instances are what this one organization
#: declared and observed. A wheel carrying them would ship one site's facts to
#: everybody who installed it.
INSTANCES = ROOT / "ontology" / "instances"
BUSINESS_DIR = INSTANCES / "business"
TECHNICAL_DIR = INSTANCES / "technical"
VALID_FIXTURES_DIR = INSTANCES / "fixtures" / "valid"
INVALID_FIXTURES_DIR = INSTANCES / "fixtures" / "invalid"
TECHNICAL_VALID_FIXTURES_DIR = INSTANCES / "fixtures" / "technical" / "valid"
TECHNICAL_INVALID_FIXTURES_DIR = INSTANCES / "fixtures" / "technical" / "invalid"
TRACE_VALID_FIXTURES_DIR = INSTANCES / "fixtures" / "trace" / "valid"
TRACE_INVALID_FIXTURES_DIR = INSTANCES / "fixtures" / "trace" / "invalid"
QUERIES_DIR = ROOT / "queries"
SOURCES_DIR = ROOT / "sources"
PACKS_DIR = ROOT / "packs"

#: Each vocabulary file, under the IRI of the ontology it declares. The IRI is the
#: name of the named graph the file is loaded into, which is what lets a shape ask a
#: vocabulary a question and get the vocabulary's own answer. See ``data_graph``.
VOCABULARIES = {
    URIRef("https://semantic-layer.19h09.co/vocab/core"): ONTOLOGY / "core.ttl",
    URIRef("https://semantic-layer.19h09.co/vocab/biz"): ONTOLOGY / "biz.ttl",
    URIRef("https://semantic-layer.19h09.co/vocab/tech"): ONTOLOGY / "tech.ttl",
    URIRef("https://semantic-layer.19h09.co/vocab/trace"): ONTOLOGY / "trace.ttl",
}

#: L1: business truth the organization declared, true until it declares otherwise.
CURATED_GRAPH = URIRef("https://semantic-layer.19h09.co/graph/l1-curated")

#: L2: technical truth a source was observed to hold at an instant, and which decays.
OBSERVED_GRAPH = URIRef("https://semantic-layer.19h09.co/graph/l2-observed")

#: L3: what a run was told, what it did, and what came of it. Evidence, never truth:
#: nothing here is believed because it is written down, only because it happened.
EVIDENCE_GRAPH = URIRef("https://semantic-layer.19h09.co/graph/l3-evidence")

#: Which named graph each instance directory loads into. The classification is by
#: directory and lives only here, because Turtle has no syntax for naming a graph:
#: a file cannot declare itself observed or curated, so where it sits is the whole of
#: what decides, and moving a file between layers is a visible move in a diff.
INSTANCE_GRAPHS = {
    BUSINESS_DIR: CURATED_GRAPH,
    VALID_FIXTURES_DIR: CURATED_GRAPH,
    INVALID_FIXTURES_DIR: CURATED_GRAPH,
    TECHNICAL_DIR: OBSERVED_GRAPH,
    TECHNICAL_VALID_FIXTURES_DIR: OBSERVED_GRAPH,
    TECHNICAL_INVALID_FIXTURES_DIR: OBSERVED_GRAPH,
    TRACE_VALID_FIXTURES_DIR: EVIDENCE_GRAPH,
    TRACE_INVALID_FIXTURES_DIR: EVIDENCE_GRAPH,
}

#: Every directory holding negative fixtures, one per layer.
INVALID_FIXTURE_DIRS = (
    INVALID_FIXTURES_DIR,
    TECHNICAL_INVALID_FIXTURES_DIR,
    TRACE_INVALID_FIXTURES_DIR,
)


class LayerError(ValueError):
    """An instance file sits where nothing says which layer it belongs to."""


def instance_graph(path: Path) -> URIRef:
    """The named graph ``path`` loads into, decided by the directory holding it."""
    graph_name = INSTANCE_GRAPHS.get(path.resolve().parent)
    if graph_name is None:
        raise LayerError(
            f"{path} is in no instance directory, so nothing says whether it holds curated "
            f"business truth or observed technical truth. Instance files live in one of "
            f"{sorted(str(d.relative_to(ROOT)) for d in INSTANCE_GRAPHS)}."
        )
    return graph_name


def turtle_files(directory: Path) -> list[Path]:
    """Every Turtle file in ``directory``, in a stable order."""
    return sorted(directory.glob("*.ttl"))


def load(paths: Iterable[Path]) -> Graph:
    """Parse Turtle files into one graph."""
    graph = Graph()
    for path in paths:
        graph.parse(path, format="turtle")
    return graph


def data_graph(instances: Iterable[Path]) -> Dataset:
    """The vocabularies plus the given instance files, each in a named graph of its own.

    A vocabulary belongs in the data graph: ``sh:class`` resolves subclasses against
    it, and each layer's boundary shape asks it which properties that layer defines.
    But a shape validates one graph and cannot see where a triple came from, so a
    vocabulary merged flat into the instances is a vocabulary any instance file can
    write to - two lines of ``rdfs:isDefinedBy`` and a technical term is L1.

    So each vocabulary is loaded into a named graph of its own, named by its ontology
    IRI. Instances are loaded into one of three more named graphs - curated, observed
    or evidence - chosen by the directory the file sits in and nothing else. Turtle has no syntax
    for naming a graph, so an instance file can reach neither a vocabulary graph nor
    the other layer's data graph: what a vocabulary defines can only be said by a
    vocabulary, and which layer a fact belongs to can only be said by where it is
    committed.

    That is what every boundary shape and every layer-separation shape rests on, and
    it is the whole mechanism. ``default_union`` keeps every unqualified pattern -
    target selection, ``sh:class`` - reading the whole thing, while a constraint that
    must not be answered by the data it is judging says ``GRAPH`` and asks the graph
    it means directly.
    """
    dataset = Dataset(default_union=True)
    for iri, path in VOCABULARIES.items():
        dataset.graph(iri).parse(path, format="turtle")
    for path in instances:
        dataset.graph(instance_graph(path)).parse(path, format="turtle")
    return dataset


def load_text(turtle: str) -> Graph:
    """Parse a block of Turtle that is not on disk."""
    return Graph().parse(data=turtle, format="turtle")


def observed_data_graph(turtle: str) -> Dataset:
    """The vocabularies plus one block of observed Turtle, as ``data_graph`` would load it.

    A reconciled graph is validated before it is written, and a candidate has no
    directory yet to be classified by. Naming the observed graph explicitly here is the
    honest way to say that: it is the one place a caller chooses the layer rather than
    the layout choosing it, and it exists so a graph that would not validate never
    reaches the working tree in the first place.
    """
    dataset = Dataset(default_union=True)
    for iri, path in VOCABULARIES.items():
        dataset.graph(iri).parse(path, format="turtle")
    dataset.graph(OBSERVED_GRAPH).parse(data=turtle, format="turtle")
    return dataset


def evidence_data_graph(evidence: Graph) -> Dataset:
    """The vocabularies plus one projected trace summary, as ``data_graph`` would load it.

    The L3 counterpart of ``observed_data_graph``, and it exists for the same reason: a
    summary is projected from the span store and has no directory to be classified by,
    so naming the evidence graph explicitly here is the honest way to say that the
    caller chose the layer. It takes a graph rather than a block of Turtle because the
    projector produces one, and round-tripping it through text would test the
    serializer rather than the projection.
    """
    dataset = Dataset(default_union=True)
    for iri, path in VOCABULARIES.items():
        dataset.graph(iri).parse(path, format="turtle")
    target = dataset.graph(EVIDENCE_GRAPH)
    for triple in evidence:
        target.add(triple)
    return dataset


def shapes_graph() -> Graph:
    return load(turtle_files(SHAPES_DIR))


@dataclass(frozen=True)
class Report:
    conforms: bool
    messages: tuple[str, ...]
    text: str


def _rendered_messages(results: Graph) -> set[str]:
    """Fill each result's message template in from the result itself.

    pyshacl interpolates SHACL-SPARQL messages but leaves core-constraint ones as
    written, so ``{$this}`` would reach the reader verbatim and the message would name
    no entity. Substituting here means a message reads the same however its shape
    happens to be expressed.
    """
    messages = set()
    for result in results.subjects(RDF.type, SH.ValidationResult):
        focus = results.value(result, SH.focusNode)
        value = results.value(result, SH.value)
        for message in results.objects(result, SH.resultMessage):
            text = str(message)
            if focus is not None:
                text = text.replace("{$this}", str(focus))
            if value is not None:
                text = text.replace("{?value}", str(value))
            messages.add(text)
    return messages


def validate(data: Dataset) -> Report:
    """Run every shape over ``data`` and report what failed, and why."""
    conforms, results, text = _shacl_validate(
        data,
        shacl_graph=shapes_graph(),
        advanced=True,
        inference="none",
    )
    messages = tuple(sorted(_rendered_messages(results)))
    return Report(conforms=conforms, messages=messages, text=text)


def query(graph: Dataset, query_file: Path) -> list[dict[str, str]]:
    """Run a committed SPARQL query and return its rows in a stable order.

    Rows are plain strings so a result can be compared against a committed JSON file
    without either side knowing about rdflib.
    """
    result = graph.query(query_file.read_text(encoding="utf-8"))
    variables: Sequence[str] = [str(variable) for variable in result.vars or ()]
    rows = [{name: str(row[name]) for name in variables if row[name] is not None} for row in result]
    return sorted(rows, key=lambda row: [row.get(name, "") for name in variables])
