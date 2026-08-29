"""Every constraint in the shapes file is defended by a negative fixture.

ontology/shapes/biz.ttl claims that one constraint carries one message, and that one
committed fixture asserts that exact message. That pairing is the entire value of the
negative fixtures: it is what makes "a constraint cannot be removed or loosened
without the build going red" true rather than intended. Remove a constraint and the
fixture that named its message stops being rejected for the reason it committed;
loosen one and the fixture conforms.

The claim used to live only in a comment at the top of the shapes file, and it was
false for ten of the seventeen constraints. Auditing it by eye is what failed, so it
is audited here instead, and a constraint added without a fixture fails this file -
wherever in a shape it is written, and whether or not this file has heard of the
parameter that states it.
"""

import re

import pytest
from rdflib import SH, URIRef

from semantic_layer import graph

#: The SHACL Core constraint parameters, by family, plus the SPARQL constraint's own.
#: Completeness of the audit does not rest on this set - ``_parameters`` reads every
#: unrecognized sh: term as a constraint, so a parameter missing here still fails
#: rather than passing quietly. Its job is the opposite one: to fail the build if a
#: parameter is ever classified as structure below, which is the single way the
#: complement rule can be made to lie. Two Core parameters are deliberately absent:
#: sh:property and sh:sparql, which do constrain, but whose block is enumerated and
#: audited as a constraint in its own right rather than counted against its parent.
CONSTRAINT_PARAMETERS = frozenset(
    {
        # Cardinality.
        SH.minCount,
        SH.maxCount,
        # Value type.
        SH["class"],
        SH.datatype,
        SH.nodeKind,
        # Value range.
        SH.minInclusive,
        SH.maxInclusive,
        SH.minExclusive,
        SH.maxExclusive,
        # String-based.
        SH.minLength,
        SH.maxLength,
        SH.pattern,
        SH.languageIn,
        SH.uniqueLang,
        # Property pairs.
        SH.equals,
        SH.disjoint,
        SH.lessThan,
        SH.lessThanOrEquals,
        # Logical.
        SH["not"],
        SH["and"],
        SH["or"],
        SH.xone,
        # Shape-based.
        SH.node,
        SH.qualifiedValueShape,
        # Other.
        SH.closed,
        SH.hasValue,
        SH["in"],
        # SPARQL-based.
        SH.select,
        SH.ask,
    }
)

#: The sh: terms a shape node carries that constrain nothing: how shapes are wired
#: together, what they aim at, what they say to a reader, and the modifiers that only
#: qualify the parameter beside them. Everything else in the sh: namespace reads as a
#: constraint, so this is the list that has to be extended - deliberately, and with
#: the knowledge that the guarantee gives up one term - when the shapes file starts
#: using a SHACL term that enforces nothing. A constraint stated outside the sh:
#: namespace, as a custom constraint component, is beyond what this audits and beyond
#: what this shapes file writes.
SHAPE_PREDICATES = frozenset(
    {
        # Structure. Each block these reach is enumerated as a constraint of its own.
        SH.property,
        SH.sparql,
        SH.path,
        # Targets: which nodes the shape judges, not what it demands of them.
        SH.targetClass,
        SH.targetNode,
        SH.targetObjectsOf,
        SH.targetSubjectsOf,
        # What the shape says to whoever tripped it, and how loudly.
        SH.message,
        SH.severity,
        SH.name,
        SH.description,
        SH.order,
        SH.group,
        SH.deactivated,
        # Modifiers: meaningless alone, each qualifies a parameter beside it.
        SH.flags,
        SH.ignoredProperties,
        SH.qualifiedMinCount,
        SH.qualifiedMaxCount,
        SH.qualifiedValueShapesDisjoint,
        # SPARQL plumbing: how a query is written down, not what it asks.
        SH.prefixes,
        SH.declare,
        SH.prefix,
        SH.namespace,
    }
)

SHAPES = graph.shapes_graph()

COMMITTED_MESSAGES = [
    path.read_text(encoding="utf-8").strip()
    for path in sorted(graph.INVALID_FIXTURES_DIR.glob("*.expected.txt"))
]


def _local(term) -> str:
    return re.split(r"[#/]", str(term))[-1]


def _parameters(node) -> frozenset:
    """Every predicate on ``node`` that states a constraint.

    Read by complement: a SHACL term this file does not recognize counts as a
    constraint rather than as nothing. Recognizing parameters instead is what let the
    gap in - a parameter nobody had listed was enforced against every graph, with no
    message, no fixture, and a green suite, because the audit could not see the node
    carrying it.
    """
    return frozenset(
        p
        for p in SHAPES.predicates(node)
        if str(p).startswith(str(SH)) and p not in SHAPE_PREDICATES
    )


def _name(node) -> str:
    """A readable id for a constraint: which shape, which path, which parameter."""
    parent = next(iter(sorted(SHAPES.subjects(object=node), key=str)), None)
    path = SHAPES.value(node, SH.path)
    parameters = sorted(_local(p) for p in _parameters(node))
    parts = [parent if parent is not None else node, path, *parameters]
    return "-".join(_local(part) for part in parts if isinstance(part, URIRef | str))


CONSTRAINTS = sorted(
    (_name(node), str(message), _parameters(node))
    for node, message in SHAPES.subject_objects(SH.message)
)

#: pytest ids: the shape, the path and the parameter, not the whole message.
CONSTRAINT_IDS = [name for name, _, _ in CONSTRAINTS]


#: Every block that can hold a constraint: a property shape, a SPARQL constraint, or
#: any node stating a parameter directly. The first two are found by structure and the
#: third by the complement rule above, because neither reads sh:message - a block
#: written without one is precisely what CONSTRAINTS cannot see and what the tests
#: below exist to catch.
CONSTRAINT_BLOCKS = sorted(
    (
        (
            _name(node),
            _parameters(node),
            frozenset(str(m) for m in SHAPES.objects(node, SH.message)),
        )
        for node in set(SHAPES.objects(None, SH.property))
        | set(SHAPES.objects(None, SH.sparql))
        | {subject for subject in SHAPES.subjects() if _parameters(subject)}
    ),
    key=lambda block: (block[0], sorted(block[2])),
)

CONSTRAINT_BLOCK_IDS = [name for name, _, _ in CONSTRAINT_BLOCKS]


def _reads_like(message: str) -> re.Pattern:
    """A pattern matching what ``message`` reads like once its slots are filled in.

    ``{$this}`` and ``{?value}`` are substituted from the validation result, so the
    committed text differs from the template exactly at the slots and nowhere else.
    """
    literals = re.split(r"\{[^}]*\}", message)
    return re.compile(".+".join(re.escape(literal) for literal in literals), re.DOTALL)


def test_the_shapes_file_has_constraints_to_cover():
    assert CONSTRAINTS, "no messages found in the shapes graph; this test proves nothing"


def test_the_shapes_file_has_constraint_blocks_to_cover():
    """An empty parametrization is a silent skip, not a failure.

    The enumeration below is found by structure rather than by sh:message, so a change
    that stops it finding anything would take the whole added-without-a-message check
    away without a single red test.
    """
    assert CONSTRAINT_BLOCKS, "no constraint blocks found in the shapes graph; this proves nothing"


def test_no_constraint_parameter_is_classified_as_structure():
    """The one way the complement rule in ``_parameters`` can be made to lie.

    Everything outside SHAPE_PREDICATES is read as a constraint, so the audit stays
    complete however SHACL is written - unless a term that really does constrain is
    listed as structure, at which point that constraint goes quiet again. Naming the
    SHACL Core families is what turns that mistake into a red build.
    """
    misclassified = sorted(_local(p) for p in CONSTRAINT_PARAMETERS & SHAPE_PREDICATES)
    assert not misclassified, (
        f"{misclassified} state constraints and are listed in SHAPE_PREDICATES, so a shape "
        f"carrying one is enforced against every graph while this file reads it as "
        f"structure. Remove them from SHAPE_PREDICATES."
    )


def test_the_two_enumerations_cover_the_same_constraints():
    """The structural enumeration and the message-driven one are the same set.

    Nothing else says so: the fixture checks read sh:message and the block check reads
    structure, so the two can drift apart - a block enumerated by neither, or a message
    defending nothing - and each test go on passing over its own half.
    """
    unmessaged = sorted(set(CONSTRAINT_BLOCK_IDS) - set(CONSTRAINT_IDS))
    unstated = sorted(set(CONSTRAINT_IDS) - set(CONSTRAINT_BLOCK_IDS))
    assert not unmessaged and not unstated, (
        f"the two enumerations disagree. Enumerated as constraints but carrying no "
        f"message, so defended by no fixture: {unmessaged}. Carrying a message but "
        f"stating no constraint this file can see, so the message defends nothing: "
        f"{unstated}."
    )


@pytest.mark.parametrize(("name", "message", "parameters"), CONSTRAINTS, ids=CONSTRAINT_IDS)
def test_each_message_belongs_to_exactly_one_constraint(name, message, parameters):
    """One constraint, one message - otherwise one fixture appears to defend two.

    A message shared by a sh:minCount and a sh:maxCount reads as one rule and regresses
    as two: a fixture asserting it pins whichever of the pair it happens to trip, and
    the other can be loosened in silence.
    """
    assert len(parameters) == 1, (
        f"{name}: expected exactly one constraint parameter under this message, found "
        f"{sorted(_local(p) for p in parameters)}. Split the block, or - if one of those "
        f"terms constrains nothing - add it to SHAPE_PREDICATES."
    )


@pytest.mark.parametrize(("name", "message", "parameters"), CONSTRAINTS, ids=CONSTRAINT_IDS)
def test_each_constraint_is_asserted_by_a_negative_fixture(name, message, parameters):
    pattern = _reads_like(message)
    assert any(pattern.fullmatch(committed) for committed in COMMITTED_MESSAGES), (
        f"{name} can be removed or loosened with a green suite: no fixture under "
        f"{graph.INVALID_FIXTURES_DIR.name}/ commits its message. Add one that trips this "
        f"constraint and nothing else."
    )


@pytest.mark.parametrize(
    ("name", "parameters", "messages"), CONSTRAINT_BLOCKS, ids=CONSTRAINT_BLOCK_IDS
)
def test_each_constraint_carries_exactly_one_message(name, parameters, messages):
    """The inverse of the two tests above, without which "added" is only an intention.

    Both of them are parametrized from sh:message, so a constraint written without one
    is invisible to them: it is enforced by the shapes file, defended by nothing, and
    can be removed or loosened again with a green suite. Enumerating the blocks instead
    is what makes a constraint added without a message fail here.
    """
    assert len(parameters) == 1, (
        f"{name}: expected exactly one constraint parameter in this block, found "
        f"{sorted(_local(p) for p in parameters)}. Split the block, or - if one of those "
        f"terms constrains nothing - add it to SHAPE_PREDICATES."
    )
    assert len(messages) == 1, (
        f"{name} carries no single sh:message ({len(messages)} found), so it is invisible "
        f"to the fixture check above and can be removed or loosened with a green suite. "
        f"Give it one message, and a fixture under {graph.INVALID_FIXTURES_DIR.name}/ that "
        f"commits it."
    )
