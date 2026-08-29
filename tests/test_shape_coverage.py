"""Every constraint in the shapes file is defended by a negative fixture.

ontology/shapes/biz.ttl claims that one constraint carries one message, and that one
committed fixture asserts that exact message. That pairing is the entire value of the
negative fixtures: it is what makes "a constraint cannot be removed or loosened
without the build going red" true rather than intended. Remove a constraint and the
fixture that named its message stops being rejected for the reason it committed;
loosen one and the fixture conforms.

The claim used to live only in a comment at the top of the shapes file, and it was
false for ten of the seventeen constraints. Auditing it by eye is what failed, so it
is audited here instead, and a constraint added without a fixture fails this file.
"""

import re

import pytest
from rdflib import SH, URIRef

from semantic_layer import graph

#: The SHACL constraint parameters this shapes file uses. A parameter missing from
#: this set reads as no constraint at all, which fails the count below rather than
#: passing quietly - so the fix when it fires is to add the parameter here.
CONSTRAINT_PARAMETERS = frozenset(
    {
        SH.minCount,
        SH.maxCount,
        SH["class"],
        SH.datatype,
        SH.nodeKind,
        SH.pattern,
        SH.hasValue,
        SH["in"],
        SH.minInclusive,
        SH.maxInclusive,
        SH.select,
    }
)

SHAPES = graph.shapes_graph()

COMMITTED_MESSAGES = [
    path.read_text(encoding="utf-8").strip()
    for path in sorted(graph.INVALID_FIXTURES_DIR.glob("*.expected.txt"))
]


def _local(term) -> str:
    return re.split(r"[#/]", str(term))[-1]


def _name(node) -> str:
    """A readable id for a constraint: which shape, which path, which parameter."""
    parent = next(SHAPES.subjects(SH.property, node), None) or next(
        SHAPES.subjects(SH.sparql, node), None
    )
    path = SHAPES.value(node, SH.path)
    parameters = sorted(_local(p) for p in SHAPES.predicates(node) if p in CONSTRAINT_PARAMETERS)
    parts = [parent if parent is not None else node, path, *parameters]
    return "-".join(_local(part) for part in parts if isinstance(part, URIRef | str))


def _parameters(node) -> frozenset:
    return frozenset(p for p in SHAPES.predicates(node) if p in CONSTRAINT_PARAMETERS)


CONSTRAINTS = sorted(
    (_name(node), str(message), _parameters(node))
    for node, message in SHAPES.subject_objects(SH.message)
)

#: pytest ids: the shape, the path and the parameter, not the whole message.
CONSTRAINT_IDS = [name for name, _, _ in CONSTRAINTS]


def _reads_like(message: str) -> re.Pattern:
    """A pattern matching what ``message`` reads like once its slots are filled in.

    ``{$this}`` and ``{?value}`` are substituted from the validation result, so the
    committed text differs from the template exactly at the slots and nowhere else.
    """
    literals = re.split(r"\{[^}]*\}", message)
    return re.compile(".+".join(re.escape(literal) for literal in literals), re.DOTALL)


def test_the_shapes_file_has_constraints_to_cover():
    assert CONSTRAINTS, "no messages found in the shapes graph; this test proves nothing"


@pytest.mark.parametrize(("name", "message", "parameters"), CONSTRAINTS, ids=CONSTRAINT_IDS)
def test_each_message_belongs_to_exactly_one_constraint(name, message, parameters):
    """One constraint, one message - otherwise one fixture appears to defend two.

    A message shared by a sh:minCount and a sh:maxCount reads as one rule and regresses
    as two: a fixture asserting it pins whichever of the pair it happens to trip, and
    the other can be loosened in silence.
    """
    assert len(parameters) == 1, (
        f"{name}: expected exactly one constraint parameter under this message, found "
        f"{sorted(_local(p) for p in parameters)}. Split the block, or add the parameter "
        f"to CONSTRAINT_PARAMETERS if it is one this test does not know."
    )


@pytest.mark.parametrize(("name", "message", "parameters"), CONSTRAINTS, ids=CONSTRAINT_IDS)
def test_each_constraint_is_asserted_by_a_negative_fixture(name, message, parameters):
    pattern = _reads_like(message)
    assert any(pattern.fullmatch(committed) for committed in COMMITTED_MESSAGES), (
        f"{name} can be removed or loosened with a green suite: no fixture under "
        f"{graph.INVALID_FIXTURES_DIR.name}/ commits its message. Add one that trips this "
        f"constraint and nothing else."
    )
