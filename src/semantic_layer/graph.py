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

ROOT = Path(__file__).resolve().parents[2]
ONTOLOGY = ROOT / "ontology"
SHAPES_DIR = ONTOLOGY / "shapes"
BUSINESS_DIR = ONTOLOGY / "instances" / "business"
VALID_FIXTURES_DIR = ONTOLOGY / "instances" / "fixtures" / "valid"
INVALID_FIXTURES_DIR = ONTOLOGY / "instances" / "fixtures" / "invalid"
QUERIES_DIR = ROOT / "queries"

#: Each vocabulary file, under the IRI of the ontology it declares. The IRI is the
#: name of the named graph the file is loaded into, which is what lets a shape ask a
#: vocabulary a question and get the vocabulary's own answer. See ``data_graph``.
VOCABULARIES = {
    URIRef("https://semantic-layer.19h09.co/vocab/core"): ONTOLOGY / "core.ttl",
    URIRef("https://semantic-layer.19h09.co/vocab/biz"): ONTOLOGY / "biz.ttl",
}


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
    """The vocabulary plus the given instance files, with the two kept apart.

    The vocabulary belongs in the data graph: ``sh:class`` resolves subclasses
    against it, and the L1 boundary shape asks it which properties L1 defines. But a
    shape validates one graph and cannot see where a triple came from, so a
    vocabulary merged flat into the instances is a vocabulary any instance file can
    write to - two lines of ``rdfs:isDefinedBy`` and a technical term is L1.

    So each vocabulary is loaded into a named graph of its own, named by its ontology
    IRI, and instances go to the default graph. Turtle cannot name a graph, so an
    instance file can never reach a vocabulary graph. ``default_union`` keeps every
    unqualified pattern - target selection, ``sh:class`` - reading the whole thing,
    while a constraint that must not be answered by the data it is judging says
    ``GRAPH`` and asks the vocabulary directly.
    """
    dataset = Dataset(default_union=True)
    for iri, path in VOCABULARIES.items():
        dataset.graph(iri).parse(path, format="turtle")
    for path in instances:
        dataset.default_graph.parse(path, format="turtle")
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
