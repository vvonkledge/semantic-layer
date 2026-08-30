"""Loading, validating and querying the L1 graph.

The Turtle files are the contract. Everything here is a thin, deterministic wrapper
over rdflib and pyshacl so that tests, and later any query path, read the same graph
the same way.

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

ROOT = Path(__file__).resolve().parents[2]
ONTOLOGY = ROOT / "ontology"
SHAPES_DIR = ONTOLOGY / "shapes"
INSTANCES = ONTOLOGY / "instances"
BUSINESS_DIR = INSTANCES / "business"
TECHNICAL_DIR = INSTANCES / "technical"
VALID_FIXTURES_DIR = INSTANCES / "fixtures" / "valid"
INVALID_FIXTURES_DIR = INSTANCES / "fixtures" / "invalid"
TECHNICAL_VALID_FIXTURES_DIR = INSTANCES / "fixtures" / "technical" / "valid"
TECHNICAL_INVALID_FIXTURES_DIR = INSTANCES / "fixtures" / "technical" / "invalid"
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
}

#: L1: business truth the organization declared, true until it declares otherwise.
CURATED_GRAPH = URIRef("https://semantic-layer.19h09.co/graph/l1-curated")

#: L2: technical truth a source was observed to hold at an instant, and which decays.
OBSERVED_GRAPH = URIRef("https://semantic-layer.19h09.co/graph/l2-observed")

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
}

#: Every directory holding negative fixtures, one per layer.
INVALID_FIXTURE_DIRS = (INVALID_FIXTURES_DIR, TECHNICAL_INVALID_FIXTURES_DIR)


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
    """The vocabularies plus the given instance files, with all four kept apart.

    A vocabulary belongs in the data graph: ``sh:class`` resolves subclasses against
    it, and each layer's boundary shape asks it which properties that layer defines.
    But a shape validates one graph and cannot see where a triple came from, so a
    vocabulary merged flat into the instances is a vocabulary any instance file can
    write to - two lines of ``rdfs:isDefinedBy`` and a technical term is L1.

    So each vocabulary is loaded into a named graph of its own, named by its ontology
    IRI. Instances are loaded into one of two more named graphs, curated or observed,
    chosen by the directory the file sits in and nothing else. Turtle has no syntax
    for naming a graph, so an instance file can reach neither a vocabulary graph nor
    the other layer's data graph: what a vocabulary defines can only be said by a
    vocabulary, and which layer a fact belongs to can only be said by where it is
    committed.

    That is what the two boundary shapes and the layer-separation shape rest on, and
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
