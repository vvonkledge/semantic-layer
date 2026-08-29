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
wherever in a shape it is written, nested inside another shape included, and whether
or not this file has heard of the parameter that states it. The parameters it has
heard of are held against the list pyshacl enforces, because the way this audit went
wrong twice was a hand-written list of SHACL terms falling behind SHACL.
"""

import re

import pytest
from pyshacl import validate
from pyshacl.constraints import ALL_CONSTRAINT_PARAMETERS
from rdflib import RDF, SH, Graph, URIRef

from semantic_layer import graph

#: The SHACL Core constraint parameters, by family, plus the SPARQL constraint's own.
#: Completeness of the audit does not rest on this set - ``_parameters`` reads every
#: unrecognized sh: term as a constraint, so a parameter missing here still fails
#: rather than passing quietly. Its job is the opposite one: to fail the build if a
#: parameter is ever classified as structure below, which is the single way the
#: complement rule can be made to lie. That job is only as good as this set is
#: complete, so what is absent from it is not left to a reading of this comment:
#: every parameter pyshacl enforces is either listed here or named in
#: NOT_A_CONSTRAINT_ALONE with the reason it states no rule of its own, and a term
#: that is neither fails the build.
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
        # Shape-based. The two qualified counts are separate constraint components
        # with separate results, so a range written as one block is two rules under
        # one message - which is the pairing this file exists to refuse.
        SH.node,
        SH.qualifiedMinCount,
        SH.qualifiedMaxCount,
        # Other.
        SH.closed,
        SH.hasValue,
        SH["in"],
        # SPARQL-based.
        SH.select,
        SH.ask,
    }
)

#: The parameters pyshacl enforces that state no rule on their own, each with the
#: reason. Together with CONSTRAINT_PARAMETERS this accounts for every term the
#: validator acts on, which is what stops that set falling silently behind the
#: validator the way it did for the qualified counts.
NOT_A_CONSTRAINT_ALONE = frozenset(
    {
        # Structural: the block each of these reaches is enumerated and audited as a
        # constraint in its own right, so counting it against its parent as well
        # would demand two messages for one rule.
        SH.property,
        SH.sparql,
        # Mandatory to both qualified components and sufficient for neither: pyshacl
        # refuses to load a sh:qualifiedValueShape written without one of the counts,
        # so it cannot be the term that quietly enforces something.
        SH.qualifiedValueShape,
        # Optional: each tunes the parameter beside it rather than stating a rule.
        SH.qualifiedValueShapesDisjoint,
        SH.ignoredProperties,
    }
)

#: The sh: terms a shape node carries that constrain nothing: how shapes are wired
#: together, what they aim at, what they say to a reader, and the parameters that
#: state no rule without another one beside them. Everything else in the sh: namespace
#: reads as a constraint, so this is the list that has to be extended - deliberately,
#: and with the knowledge that the guarantee gives up one term - when the shapes file
#: starts using a SHACL term that enforces nothing. A term listed here can still
#: loosen the rule beside it: sh:flags "i" on a sh:pattern, another entry under
#: sh:ignoredProperties, a wider sh:qualifiedValueShape. None of them can hide a
#: second rule the way a misfiled constraint parameter does, and the fixture that
#: trips the rule they qualify is what holds them. A constraint stated outside the sh:
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
        SH.qualifiedValueShape,
        SH.qualifiedValueShapesDisjoint,
        # SPARQL plumbing: how a query is written down, not what it asks.
        SH.prefixes,
        SH.declare,
        SH.prefix,
        SH.namespace,
    }
)

#: Edges that carry a nested shape without naming anything a reader could act on: the
#: two structural containers, whose block is enumerated separately anyway, and the
#: rest of an RDF list. The predicate that reaches into a list - sh:or and its
#: siblings - is named instead, together with the member's position in it.
SILENT_EDGES = frozenset({SH.property, SH.sparql, RDF.rest})

SHAPES = graph.shapes_graph()

COMMITTED_MESSAGES = [
    path.read_text(encoding="utf-8").strip()
    for path in sorted(graph.INVALID_FIXTURES_DIR.glob("*.expected.txt"))
]


def _local(term) -> str:
    return re.split(r"[#/]", str(term))[-1]


def _parameters(shapes, node) -> frozenset:
    """Every predicate on ``node`` that states a constraint.

    Read by complement: a SHACL term this file does not recognize counts as a
    constraint rather than as nothing. Recognizing parameters instead is what let the
    gap in - a parameter nobody had listed was enforced against every graph, with no
    message, no fixture, and a green suite, because the audit could not see the node
    carrying it.
    """
    return frozenset(
        p
        for p in shapes.predicates(node)
        if str(p).startswith(str(SH)) and p not in SHAPE_PREDICATES
    )


def _incoming(shapes, node):
    """The one edge pointing at ``node``, chosen in a stable order."""
    edges = sorted(shapes.subject_predicates(node), key=lambda edge: (str(edge[0]), str(edge[1])))
    return edges[0] if edges else (None, None)


def _ancestry(shapes, node) -> list:
    """Every edge from the nearest named shape down to ``node``, outermost first.

    A constraint written inline - inside sh:qualifiedValueShape, or as a member of an
    sh:or list - hangs off blank nodes the whole way up. Stopping at the first parent
    reports one of them, and rdflib's BNode is a str subclass, so it survives every
    filter that looks written to exclude it and reaches the reader as an ``n...``
    label naming nothing. Walking on to a URIRef names the shape to go and edit.
    """
    edges = []
    current = node
    seen = {node}
    while not isinstance(current, URIRef):
        parent, predicate = _incoming(shapes, current)
        if parent is None or parent in seen:
            break
        seen.add(parent)
        edges.append((parent, predicate))
        current = parent
    return list(reversed(edges))


def _list_position(shapes, cell) -> int:
    """Where ``cell`` sits in the RDF list it is a cell of, counting from one.

    Two members of one sh:or state the same parameter as often as not, so the
    position is what keeps their ids distinct, stable across runs, and pointed at the
    alternative that failed rather than at "one of them".
    """
    position = 1
    seen = {cell}
    previous = next(iter(sorted(shapes.subjects(RDF.rest, cell), key=str)), None)
    while previous is not None and previous not in seen:
        seen.add(previous)
        position += 1
        previous = next(iter(sorted(shapes.subjects(RDF.rest, previous), key=str)), None)
    return position


def _name(shapes, node) -> str:
    """A readable id for a constraint: which named shape, which path, which parameter."""
    edges = _ancestry(shapes, node)
    root = edges[0][0] if edges else node
    parts = [_local(root)]
    for subject, predicate in edges:
        path = shapes.value(subject, SH.path)
        if path is not None:
            parts.append(_local(path))
        if predicate == RDF.first:
            parts.append(str(_list_position(shapes, subject)))
        elif predicate not in SILENT_EDGES:
            parts.append(_local(predicate))
    path = shapes.value(node, SH.path)
    if path is not None:
        parts.append(_local(path))
    parts.extend(sorted(_local(p) for p in _parameters(shapes, node)))
    return "-".join(parts)


def _constraints(shapes) -> list:
    """Every constraint ``shapes`` states, found by the message it carries."""
    return sorted(
        (
            (_name(shapes, node), str(message), _parameters(shapes, node))
            for node, message in shapes.subject_objects(SH.message)
        ),
        key=lambda constraint: constraint[:2],
    )


def _constraint_blocks(shapes) -> list:
    """Every block of ``shapes`` that can hold a constraint, found by structure.

    A property shape, a SPARQL constraint, or any node stating a parameter directly.
    The first two are found by structure and the third by the complement rule above,
    because neither reads sh:message - a block written without one is precisely what
    ``_constraints`` cannot see and what the tests below exist to catch.
    """
    return sorted(
        (
            (
                _name(shapes, node),
                _parameters(shapes, node),
                frozenset(str(m) for m in shapes.objects(node, SH.message)),
            )
            for node in set(shapes.objects(None, SH.property))
            | set(shapes.objects(None, SH.sparql))
            | {subject for subject in shapes.subjects() if _parameters(shapes, subject)}
        ),
        key=lambda block: (block[0], sorted(block[2])),
    )


CONSTRAINTS = _constraints(SHAPES)

#: pytest ids: the shape, the path and the parameter, not the whole message.
CONSTRAINT_IDS = [name for name, _, _ in CONSTRAINTS]

CONSTRAINT_BLOCKS = _constraint_blocks(SHAPES)

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


def test_every_parameter_the_validator_enforces_is_classified():
    """The other half of that guard: a parameter dropped rather than misfiled.

    The test above compares two hand-written sets against each other, so moving a term
    out of CONSTRAINT_PARAMETERS and into SHAPE_PREDICATES in one edit satisfies it
    while doing exactly the damage it exists to prevent - which is how
    sh:qualifiedMinCount and sh:qualifiedMaxCount spent a release filed as structure.
    Anchoring the classification to the parameter list pyshacl actually enforces is
    what makes that edit red, and what makes a SHACL term the validator gains later
    something someone has to classify on purpose.
    """
    unclassified = sorted(
        _local(p)
        for p in set(ALL_CONSTRAINT_PARAMETERS) - CONSTRAINT_PARAMETERS - NOT_A_CONSTRAINT_ALONE
    )
    assert not unclassified, (
        f"pyshacl enforces {unclassified}, and this file classifies them as neither a "
        f"constraint parameter nor a term that states no rule alone. Add each to "
        f"CONSTRAINT_PARAMETERS, or to NOT_A_CONSTRAINT_ALONE with the reason it "
        f"constrains nothing on its own."
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


PREFIXES = """
@prefix biz: <https://semantic-layer.19h09.co/vocab/biz#> .
@prefix sh:  <http://www.w3.org/ns/shacl#> .
@prefix shp: <https://semantic-layer.19h09.co/shapes/biz#> .
"""

#: Two shapes written inline, the two ways SHACL allows: nested under a shape-valued
#: parameter, and as members of an RDF list. Neither is written in biz.ttl today,
#: which is why the ids they produce have to be pinned here rather than observed
#: there. Both blocks are deliberately left without an sh:message: what is under test
#: is the name the failure carries, and these are the shapes that used to carry none.
INLINE_SHAPES = (
    PREFIXES
    + """
shp:RoleShape
    a sh:NodeShape ;
    sh:targetClass biz:Role ;

    sh:property [
        sh:path biz:permits ;
        sh:qualifiedValueShape [ sh:class biz:Capability ] ;
        sh:qualifiedMinCount 1 ;
    ] ;

    sh:property [
        sh:path biz:grantsRole ;
        sh:or ( [ sh:class biz:Capability ] [ sh:class biz:Role ] ) ;
    ] .
"""
)

#: A qualified range written the only way this audit accepts one: two property blocks
#: over the same path and the same named value shape, one count each, one message
#: each. Written as a single block it would be two constraint components under one
#: message, which is what test_each_message_belongs_to_exactly_one_constraint refuses.
QUALIFIED_RANGE_SHAPES = (
    PREFIXES
    + """
shp:RoleShape
    a sh:NodeShape ;
    sh:targetClass biz:Role ;

    sh:property [
        sh:path biz:permits ;
        sh:qualifiedValueShape shp:PermittedCapabilityShape ;
        sh:qualifiedMinCount 1 ;
        sh:message "Role {$this} permits no capability." ;
    ] ;

    sh:property [
        sh:path biz:permits ;
        sh:qualifiedValueShape shp:PermittedCapabilityShape ;
        sh:qualifiedMaxCount 2 ;
        sh:message "Role {$this} permits more than two capabilities." ;
    ] .

shp:PermittedCapabilityShape
    a sh:NodeShape ;
    sh:class biz:Capability .
"""
)


def _role_permitting(count: int) -> Graph:
    permits = " , ".join(f"biz:c{n}" for n in range(count))
    capabilities = "\n".join(f"biz:c{n} a biz:Capability ." for n in range(count))
    role = "biz:r a biz:Role" + (f" ; biz:permits {permits}" if permits else "") + " ."
    return Graph().parse(data=f"{PREFIXES}\n{role}\n{capabilities}", format="turtle")


def _messages_against(shapes: str, data: Graph) -> set:
    conforms, results, _ = validate(
        data,
        shacl_graph=Graph().parse(data=shapes, format="turtle"),
        advanced=True,
        inference="none",
    )
    return set() if conforms else {str(m) for m in results.objects(None, SH.resultMessage)}


def test_a_nested_constraint_is_named_by_its_nearest_named_shape():
    """A blank-node id is not a constraint name anybody can act on.

    Every ancestor of an inline shape is itself a blank node, and rdflib's BNode is a
    str subclass, so a walk that stops at the first parent prints an ``n...`` label
    that names no shape, no path and nothing to edit - and prints a different one on
    every run, because the ids are minted at parse time. Both spellings are pinned
    here so the diagnostic stays a sentence a reader can follow back into biz.ttl.
    """
    shapes = Graph().parse(data=INLINE_SHAPES, format="turtle")
    assert [name for name, _, _ in _constraint_blocks(shapes)] == [
        "RoleShape-grantsRole-or",
        "RoleShape-grantsRole-or-1-class",
        "RoleShape-grantsRole-or-2-class",
        "RoleShape-permits-qualifiedMinCount",
        "RoleShape-permits-qualifiedValueShape-class",
    ]


def test_a_qualified_range_is_audited_as_two_separate_constraints():
    """The audit has to leave a legitimate qualified constraint writable.

    sh:qualifiedMinCount and sh:qualifiedMaxCount became constraint parameters because
    each states a rule of its own. That only helps if a range can still be written:
    one block per count, each with the message and the fixture that its own rule is
    held by, and neither message able to stand in for the other's.
    """
    blocks = _constraint_blocks(Graph().parse(data=QUALIFIED_RANGE_SHAPES, format="turtle"))
    assert [(name, sorted(_local(p) for p in parameters)) for name, parameters, _ in blocks] == [
        ("PermittedCapabilityShape-class", ["class"]),
        ("RoleShape-permits-qualifiedMaxCount", ["qualifiedMaxCount"]),
        ("RoleShape-permits-qualifiedMinCount", ["qualifiedMinCount"]),
    ]
    counts = [block for block in blocks if block[0].startswith("RoleShape-")]
    assert all(len(messages) == 1 for _, _, messages in counts)

    committed = [
        "Role https://example.org/r permits no capability.",
        "Role https://example.org/r permits more than two capabilities.",
    ]
    defended = {
        name: [text for text in committed if _reads_like(next(iter(messages))).fullmatch(text)]
        for name, _, messages in counts
    }
    assert defended == {
        "RoleShape-permits-qualifiedMaxCount": [committed[1]],
        "RoleShape-permits-qualifiedMinCount": [committed[0]],
    }


def test_each_qualified_count_is_separately_enforceable():
    """Why the audit owes each count its own message, checked against the validator.

    Filed as structure the pair was invisible: QA loosened a committed
    sh:qualifiedMaxCount from 3 to 999 and the suite stayed byte-identically green.
    The two counts are separate SHACL constraint components producing separate
    results, so one message over both would let either be loosened behind the other's
    fixture.
    """
    assert _messages_against(QUALIFIED_RANGE_SHAPES, _role_permitting(0)) == {
        "Role {$this} permits no capability."
    }
    assert _messages_against(QUALIFIED_RANGE_SHAPES, _role_permitting(2)) == set()
    assert _messages_against(QUALIFIED_RANGE_SHAPES, _role_permitting(3)) == {
        "Role {$this} permits more than two capabilities."
    }
