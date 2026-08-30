"""Deterministic Turtle and N-Triples, written here rather than taken from rdflib.

Reconciled L2 truth is committed to git and reviewed as a diff, so the same payload
has to produce the same bytes - not an equivalent graph. rdflib's serializers do not
promise that: their output tracks dictionary order, blank-node labels minted at parse
time, and whatever the installed version happens to do about prefixes. Any of those
turns a no-op refresh into a diff nobody can read.

So layout is decided here and escaping is left to rdflib, which is the half that is
genuinely hard to get right. Terms are sorted, ``rdf:type`` leads each subject because
that is how a reader scans a graph, and nothing else about the output depends on
anything but the triples themselves.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import RDF

#: The prefixes emitted, longest namespace first so the most specific one wins. Only
#: vocabulary terms are ever compacted: an entity IRI carries slashes, which a Turtle
#: prefixed name cannot hold unescaped, and an escaped one is harder to read in review
#: than the angle brackets it replaced.
PREFIXES: tuple[tuple[str, str], ...] = (
    ("biz", "https://semantic-layer.19h09.co/vocab/biz#"),
    ("core", "https://semantic-layer.19h09.co/vocab/core#"),
    ("tech", "https://semantic-layer.19h09.co/vocab/tech#"),
    ("owl", "http://www.w3.org/2002/07/owl#"),
    ("rdf", "http://www.w3.org/1999/02/22-rdf-syntax-ns#"),
    ("rdfs", "http://www.w3.org/2000/01/rdf-schema#"),
    ("xsd", "http://www.w3.org/2001/XMLSchema#"),
)

#: What may follow a prefix. Deliberately narrower than Turtle's own PN_LOCAL: a term
#: this does not match is written out in full rather than escaped, because a prefixed
#: name nobody can read at a glance is worse than the IRI it stood for.
LOCAL_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")


class SerializationError(ValueError):
    """A graph was handed here that has no one deterministic way to be written."""


#: What may not appear inside <> in Turtle or N-Triples without being escaped, plus the
#: space and the control characters. Every IRI this repository writes is minted, and
#: minting percent-encodes anything a source contributed, so none of these can reach
#: here - which is exactly why it is worth saying so out loud rather than discovering
#: otherwise in a file somebody else is parsing.
IRI_FORBIDDEN = set('<>"{}|^`\\') | {chr(code) for code in range(0x21)}


def _iri(node: URIRef, *, compact: bool) -> str:
    offending = sorted(IRI_FORBIDDEN & set(str(node)))
    if offending:
        raise SerializationError(
            f"the IRI {str(node)!r} contains {offending}, which cannot be written between "
            f"angle brackets. Every identifier here is minted, and minting percent-encodes "
            f"whatever the source contributed, so this is text that reached a graph without "
            f"going through semantic_layer.ids."
        )
    if compact:
        for prefix, namespace in PREFIXES:
            if str(node).startswith(namespace):
                local = str(node)[len(namespace) :]
                if LOCAL_NAME.fullmatch(local):
                    return f"{prefix}:{local}"
    return f"<{node}>"


#: The escapes N-Triples defines. Everything else below 0x20 is written as \uXXXX,
#: because N-Triples has no other spelling for it.
NT_ESCAPES = str.maketrans(
    {
        "\\": "\\\\",
        '"': '\\"',
        "\n": "\\n",
        "\r": "\\r",
        "\t": "\\t",
        "\b": "\\b",
        "\f": "\\f",
    }
)


def _quoted(text: str, *, compact: bool) -> str:
    """A lexical form, quoted for the syntax being written.

    Turtle can hold a newline inside a triple-quoted string and rdflib writes one, which
    is what makes a committed graph readable when a source puts a line break in a
    description. N-Triples cannot: it is one triple per line, so the same value has to be
    escaped instead. Handing rdflib's Turtle quoting to an N-Triples writer produces a
    file that looks fine and that no consumer can parse - which is a thing to find out
    here rather than in somebody else's pipeline.
    """
    if compact:
        return Literal(text).n3()
    escaped = text.translate(NT_ESCAPES)
    escaped = "".join(
        character if character >= " " or character == "\t" else f"\\u{ord(character):04X}"
        for character in escaped
    )
    return f'"{escaped}"'


def _literal(node: Literal, *, compact: bool) -> str:
    # The datatype is compacted for Turtle so the common case - an xsd:dateTime - stays
    # readable in a diff, and left in full for N-Triples, which has no prefixes.
    quoted = _quoted(str(node), compact=compact)
    if node.language:
        return f"{quoted}@{node.language}"
    if node.datatype:
        return f"{quoted}^^{_iri(URIRef(node.datatype), compact=compact)}"
    return quoted


def term(node, *, compact: bool = True) -> str:
    """One term, written the one way this module writes it."""
    if isinstance(node, BNode):
        raise SerializationError(
            f"the graph contains the blank node {node}, which has no stable name: two "
            f"serializations of the same graph would differ only in labels rdflib minted "
            f"at parse time. Mint an identifier for it instead."
        )
    if isinstance(node, Literal):
        return _literal(node, compact=compact)
    return _iri(node, compact=compact)


def _predicate(node: URIRef) -> str:
    return "a" if node == RDF.type else term(node)


def _predicate_order(node: URIRef) -> tuple[int, str]:
    return (0 if node == RDF.type else 1, str(node))


def turtle(graph: Graph, *, header: Iterable[str] = ()) -> str:
    """``graph`` as Turtle, byte-identical for any two graphs holding the same triples."""
    lines = [f"# {line}".rstrip() for line in header]
    if lines:
        lines.append("")
    lines += [f"@prefix {prefix}: <{namespace}> ." for prefix, namespace in sorted(PREFIXES)]

    for subject in sorted(set(graph.subjects()), key=str):
        lines.append("")
        lines.append(term(subject))
        statements = sorted(
            (_predicate_order(predicate), term(obj), _predicate(predicate))
            for predicate, obj in graph.predicate_objects(subject)
        )
        for index, (_, obj, predicate) in enumerate(statements):
            end = " ." if index == len(statements) - 1 else " ;"
            lines.append(f"    {predicate} {obj}{end}")

    return "\n".join(lines) + "\n"


def ntriples(graph: Graph) -> str:
    """``graph`` as sorted N-Triples: one canonical line per triple, no prefixes.

    What a machine consumer is handed. Turtle is for the reviewer; this is for the
    reader who has to hash it and get the same answer as whoever produced it.
    """
    return "".join(
        sorted(" ".join(term(node, compact=False) for node in triple) + " .\n" for triple in graph)
    )
