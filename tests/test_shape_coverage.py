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

Two groups of SHACL terms are outside that guarantee rather than inside it, and are
therefore refused rather than audited. The qualified family says two things at once -
how many values, and which values count - and only the first has a shape a fixture can
be written against: a fixture that trips a count trips it at any value shape, so
widening sh:qualifiedValueShape loosens both counts while every committed fixture goes
on failing for exactly its committed reason. The modifiers sh:flags and
sh:ignoredProperties do the same to the parameter they sit beside: a fixture committed
against a sh:pattern is a value that fails under either casing, and one committed
against a sh:closed is a node carrying a property nobody would ignore, so both go on
failing for their committed reason after the rule they defend has widened. Phase 0 does
not accept a constraint whose meaning the suite cannot hold, and nothing in the shapes
file writes either group today, so both are prohibited outright here until the half
they move can be audited. That is a boundary, not a statement about SHACL: the
prohibition is what is guaranteed, and no wider guarantee is claimed for it.
"""

import re
from typing import NamedTuple

import pytest
from pyshacl import validate
from pyshacl.constraints import ALL_CONSTRAINT_PARAMETERS
from rdflib import RDF, SH, Graph, URIRef

from semantic_layer import graph

#: The SHACL Core constraint parameters this layer supports, by family, plus the
#: SPARQL constraint's own. Completeness of the audit does not rest on this set -
#: ``_parameters`` reads every unrecognized sh: term as a constraint, so a parameter
#: missing here still fails rather than passing quietly. Its job is the opposite one:
#: to fail the build if a parameter is ever classified as structure below, which is
#: the single way the complement rule can be made to lie. That job is only as good as
#: this set is complete, so what is absent from it is not left to a reading of this
#: comment: every parameter pyshacl enforces is either listed here, named in
#: NOT_A_CONSTRAINT_ALONE with the reason it states no rule of its own, or named in
#: FORBIDDEN_PARAMETERS as a term this layer does not support - and a term that is
#: none of the three fails the build.
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
        # String-based. sh:flags is not here: see UNSAFE_MODIFIERS.
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
        # Shape-based. The qualified family is not here: see QUALIFIED_FAMILY.
        SH.node,
        # Other. sh:ignoredProperties is not here: see UNSAFE_MODIFIERS.
        SH.closed,
        SH.hasValue,
        SH["in"],
        # SPARQL-based.
        SH.select,
        SH.ask,
    }
)

#: The SHACL qualified family, which this layer refuses to write rather than audit.
#: sh:qualifiedValueShape decides which values the counts beside it apply to, so it is
#: half of what a qualified constraint says - and it is the half no fixture can hold.
#: A fixture that trips sh:qualifiedMinCount is a node with too few values and trips
#: at any value shape whatsoever, so widening the value shape loosens both counts with
#: every fixture still failing for its committed reason and the suite green. Filing
#: these as constraint parameters does not help either: pyshacl refuses to load a
#: sh:qualifiedValueShape written without a count, so the audit's one-parameter rule
#: forces the value shape and its count apart and the value shape cannot then carry a
#: message of its own. Neither classification is sound, so the family is refused in
#: phase 0 instead, and the refusal is what this file guarantees about it.
QUALIFIED_FAMILY = frozenset(
    {
        SH.qualifiedValueShape,
        SH.qualifiedMinCount,
        SH.qualifiedMaxCount,
        SH.qualifiedValueShapesDisjoint,
    }
)

#: The SHACL modifiers this layer refuses for the same reason, one step smaller. A
#: modifier states no rule of its own - which is why both of these were filed as
#: structure until now - but it decides where the rule beside it draws its line, and
#: that is the half no fixture holds. sh:flags "i" turns a sh:pattern into a
#: case-insensitive one, and one more entry under sh:ignoredProperties exempts one more
#: property from a sh:closed; either way the fixture defending that rule was chosen to
#: fail under the narrower spelling, so it goes on failing for exactly its committed
#: reason while the rule has widened. Stating no rule is not the same as moving none,
#: so neither term is structure, neither has a fixture-shaped half to be audited as,
#: and both are refused in phase 0 instead. The parameters they modify - sh:pattern and
#: sh:closed - stay supported and audited like any other. This group is explicit rather
#: than read off the validator, so a term added here is refused from that moment on and
#: has to bring the evidence below that says why.
UNSAFE_MODIFIERS = frozenset({SH.flags, SH.ignoredProperties})

#: Every term phase 0 refuses outright. The audit searches the shapes graph for each of
#: these, so the two groups above are the whole of what may not be written.
FORBIDDEN_PARAMETERS = QUALIFIED_FAMILY | UNSAFE_MODIFIERS


class Unsupported(NamedTuple):
    """A group of refused terms, and the sentence a reader who wrote one is given."""

    name: str
    terms: frozenset
    why: str


#: What the prohibition says, per group, so whoever wrote sh:flags is told about
#: modifiers rather than about qualified counts: why the audit cannot hold the group,
#: and what to write instead.
UNSUPPORTED = (
    Unsupported(
        "the SHACL qualified family",
        QUALIFIED_FAMILY,
        "A qualified constraint states two things - how many values, and which values "
        "count - and only the count has a shape a fixture can be written against: a "
        "fixture that trips sh:qualifiedMinCount trips it at any value shape, so a wider "
        "sh:qualifiedValueShape loosens the rule with the whole suite green. Write the "
        "rule some other way - sh:node with sh:minCount, or a separately targeted named "
        "shape - or raise the boundary as a decision before moving it.",
    ),
    Unsupported(
        "the SHACL modifiers that move the rule beside them",
        UNSAFE_MODIFIERS,
        "A modifier decides where the parameter beside it draws its line without changing "
        "which rule is stated, so the fixture defending that rule goes on failing for its "
        "committed reason once the rule has widened: sh:flags beside a sh:pattern, one "
        "more entry under sh:ignoredProperties beside a sh:closed. The parameter itself is "
        "supported - write the rule it states on its own, as a pattern spelling out every "
        "form it accepts or a closed shape declaring the property it means to allow - or "
        "raise the boundary as a decision before moving it.",
    ),
)

#: The parameters pyshacl enforces that state no rule on their own, each with the
#: reason. Together with CONSTRAINT_PARAMETERS and FORBIDDEN_PARAMETERS this accounts
#: for every term the validator acts on, which is what stops those sets falling
#: silently behind the validator the way they did for the qualified counts. Stating no
#: rule alone does not on its own earn a term a place here: sh:ignoredProperties states
#: none either and is refused above, because a term that states no rule can still move
#: one.
NOT_A_CONSTRAINT_ALONE = frozenset(
    {
        # Structural: the block each of these reaches is enumerated and audited as a
        # constraint in its own right, so counting it against its parent as well
        # would demand two messages for one rule.
        SH.property,
        SH.sparql,
    }
)

#: The sh: terms a shape node carries that constrain nothing: how shapes are wired
#: together, what they aim at, what they say to a reader, and the parameters that
#: state no rule without another one beside them. Everything else in the sh: namespace
#: reads as a constraint, so this is the list that has to be extended - deliberately,
#: and with the knowledge that the guarantee gives up one term - when the shapes file
#: starts using a SHACL term that enforces nothing. Enforcing nothing is not enough: a
#: term listed here must also be unable to move where a rule beside it draws its line,
#: because the fixture defending that rule was written against the line as it stood and
#: goes on failing for its committed reason once it has moved. That is what stopped
#: being true for sh:qualifiedValueShape, and it was never true for sh:flags or
#: sh:ignoredProperties, which is why both groups are refused above rather than listed
#: here. A constraint stated outside the sh: namespace, as a custom constraint
#: component, is beyond what this audits and beyond what this shapes file writes.
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

    A constraint written inline - inside sh:node, or as a member of an sh:or list -
    hangs off blank nodes the whole way up. Stopping at the first parent reports one of
    them, and rdflib's BNode is a str subclass, so it survives every filter that looks
    written to exclude it and reaches the reader as an ``n...`` label naming nothing.
    Walking on to a URIRef names the shape to go and edit.
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


def _where(shapes, node) -> str:
    """Where ``node`` sits: the nearest named shape, and the path down to it.

    The half of a constraint's id that says which block to go and edit, without saying
    what the block states. A refused term needs that half on its own, because the
    parameter it would otherwise be named by is the term being refused.
    """
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
    return "-".join(parts)


def _name(shapes, node) -> str:
    """A readable id for a constraint: which named shape, which path, which parameter."""
    return "-".join([_where(shapes, node), *sorted(_local(p) for p in _parameters(shapes, node))])


def _forbidden_terms(shapes) -> list:
    """Every refused term ``shapes`` writes, each with the block writing it.

    Read from the graph rather than from the file's text, so a spelling reaches this
    however it is written: value shape named or inline, counts together in one block or
    split across two, a modifier beside the parameter it moves or alone, nested inside
    another shape or stated straight onto a node shape.
    """
    return sorted(
        {
            f"{_where(shapes, node)}: sh:{_local(term)}"
            for term in FORBIDDEN_PARAMETERS
            for node in shapes.subjects(term)
        }
    )


def _groups_of(written: list) -> list:
    """The refused groups the reported terms belong to, in declaration order."""
    return [
        group
        for group in UNSUPPORTED
        if any(entry.endswith(f": sh:{_local(term)}") for term in group.terms for entry in written)
    ]


def _prohibition(written: list) -> str:
    """What the build says when a refused term reaches the shapes graph.

    Only the groups actually written are explained, because a reader who added
    sh:flags is not helped by a paragraph about qualified counts.
    """
    groups = _groups_of(written)
    return " ".join(
        [
            f"phase 0 does not support {' and '.join(group.name for group in groups)}, and "
            f"the shapes graph writes {written}.",
            *(group.why for group in groups),
            "Adding any of these terms to CONSTRAINT_PARAMETERS, to SHAPE_PREDICATES or to "
            "NOT_A_CONSTRAINT_ALONE is the silent loosening this refuses, not a way around "
            "it.",
        ]
    )


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


def test_no_forbidden_parameter_is_classified_anywhere_else():
    """A refused term is refused and nothing else, or it is not refused at all.

    The classifications are what the audit acts on, and a term in two of them is read
    by whichever rule looks first. Listing a qualified term as structure is the move
    that opened the hole this file now refuses - ``_parameters`` stops seeing it, and
    the prohibition below is the only thing left standing between it and a green suite.
    Filing a refused term as a supported parameter, or as one that states no rule
    alone, is the same weakening written the other two ways round - and the last of
    those is the classification sh:ignoredProperties is being moved out of, so it is
    the one a reader would reach for first.
    """
    elsewhere = {
        name: sorted(_local(p) for p in FORBIDDEN_PARAMETERS & classified)
        for name, classified in (
            ("CONSTRAINT_PARAMETERS", CONSTRAINT_PARAMETERS),
            ("SHAPE_PREDICATES", SHAPE_PREDICATES),
            ("NOT_A_CONSTRAINT_ALONE", NOT_A_CONSTRAINT_ALONE),
        )
        if FORBIDDEN_PARAMETERS & classified
    }
    assert not elsewhere, (
        f"phase 0 refuses these terms and this file classifies them as well: {elsewhere}. "
        f"A term cannot be both refused and classified: pick one, and if the boundary is "
        f"to move, move it as a decision rather than as an overlap."
    )


def test_the_whole_qualified_family_is_forbidden():
    """The prohibition covers the family, not the terms somebody remembered.

    QUALIFIED_FAMILY is hand-written, so on its own it says only that four terms were
    typed once. Reading the family off the validator instead is what makes moving one of
    them into another classification a red build rather than a quiet narrowing of what is
    refused, and what makes a qualified term SHACL gains later refused on arrival instead
    of admitted by omission. UNSAFE_MODIFIERS has no such spelling to read, and is
    anchored by the evidence each of its terms carries instead.
    """
    family = {p for p in ALL_CONSTRAINT_PARAMETERS if _local(p).startswith("qualified")}
    assert family, "pyshacl enforces no qualified parameter; this test proves nothing"
    unforbidden = sorted(_local(p) for p in family - FORBIDDEN_PARAMETERS)
    assert not unforbidden, (
        f"pyshacl enforces {unforbidden} as part of the qualified family, and this file "
        f"does not refuse them. Every term of that family is prohibited in phase 0, "
        f"because the value-shape half of what it states cannot be held by a fixture. "
        f"Add each to QUALIFIED_FAMILY."
    )


def test_every_parameter_the_validator_enforces_is_classified():
    """The other half of that guard: a parameter dropped rather than misfiled.

    The tests above compare hand-written sets against each other, so moving a term out
    of CONSTRAINT_PARAMETERS and into SHAPE_PREDICATES in one edit satisfies them while
    doing exactly the damage they exist to prevent - which is how sh:qualifiedMinCount
    and sh:qualifiedMaxCount spent a release filed as structure. Anchoring the
    classification to the parameter list pyshacl actually enforces is what makes that
    edit red, and what makes a SHACL term the validator gains later something someone
    has to classify on purpose: supported, stating no rule alone, or refused.
    """
    unclassified = sorted(
        _local(p)
        for p in set(ALL_CONSTRAINT_PARAMETERS)
        - CONSTRAINT_PARAMETERS
        - NOT_A_CONSTRAINT_ALONE
        - FORBIDDEN_PARAMETERS
    )
    assert not unclassified, (
        f"pyshacl enforces {unclassified}, and this file classifies them as none of a "
        f"supported constraint parameter, a term that states no rule alone, or a term "
        f"this layer refuses. Add each to CONSTRAINT_PARAMETERS, to "
        f"NOT_A_CONSTRAINT_ALONE with the reason it constrains nothing on its own, or "
        f"to FORBIDDEN_PARAMETERS with the reason it cannot be audited."
    )


def test_each_classification_accounts_for_a_term_once():
    """Three sets, one home per term, and a count that has to add up.

    Each guard above reads one pair of sets, so a term added to two sets that no single
    pair compares stays invisible to all of them. Requiring the three to partition the
    validator's own parameter list is what leaves no such gap - and the arithmetic fails
    on a term counted twice as loudly as on one counted never.
    """
    enforced = set(ALL_CONSTRAINT_PARAMETERS)
    classified = [
        CONSTRAINT_PARAMETERS & enforced,
        NOT_A_CONSTRAINT_ALONE & enforced,
        FORBIDDEN_PARAMETERS & enforced,
    ]
    counted = sum(len(part) for part in classified)
    unclassified = sorted(_local(p) for p in enforced - set().union(*classified))
    twice = sorted(_local(p) for p in enforced if sum(p in part for part in classified) > 1)
    assert counted == len(enforced), (
        f"pyshacl enforces {len(enforced)} parameters and this file accounts for "
        f"{counted}: {unclassified} is classified nowhere, and {twice} is classified more "
        f"than once. Every parameter belongs to exactly one of CONSTRAINT_PARAMETERS, "
        f"NOT_A_CONSTRAINT_ALONE and FORBIDDEN_PARAMETERS."
    )


def test_the_shapes_file_writes_no_refused_term():
    """The prohibition, against the shapes file the build actually validates.

    Everything else about the refused groups here is checked against graphs written in
    this file. This is the one that reads ontology/shapes/biz.ttl, so adding a
    qualified term or an unsafe modifier there fails the build by name whatever else
    the audit makes of it.
    """
    written = _forbidden_terms(SHAPES)
    assert not written, _prohibition(written)


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
        f"terms constrains nothing and moves nothing - add it to SHAPE_PREDICATES. A term "
        f"phase 0 refuses is neither, and belongs in neither."
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
        f"terms constrains nothing and moves nothing - add it to SHAPE_PREDICATES. A term "
        f"phase 0 refuses is neither, and belongs in neither."
    )
    assert len(messages) == 1, (
        f"{name} carries no single sh:message ({len(messages)} found), so it is invisible "
        f"to the fixture check above and can be removed or loosened with a green suite. "
        f"Give it one message, and a fixture under {graph.INVALID_FIXTURES_DIR.name}/ that "
        f"commits it."
    )


PREFIXES = """
@prefix biz:  <https://semantic-layer.19h09.co/vocab/biz#> .
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix sh:   <http://www.w3.org/ns/shacl#> .
@prefix shp:  <https://semantic-layer.19h09.co/shapes/biz#> .
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
        sh:node [ sh:class biz:Capability ] ;
    ] ;

    sh:property [
        sh:path biz:grantsRole ;
        sh:or ( [ sh:class biz:Capability ] [ sh:class biz:Role ] ) ;
    ] .
"""
)

#: Every spelling of a qualified constraint the prohibition has to catch: each term of
#: the family on its own, and a complete range both ways SHACL lets its value shape be
#: written. biz.ttl writes none of them, so a refusal exercised only against biz.ttl
#: is a refusal exercised against nothing.
QUALIFIED_SPELLINGS = (
    (
        "a value shape alone",
        "sh:qualifiedValueShape shp:CapabilityValueShape ;",
        ["RoleShape-permits: sh:qualifiedValueShape"],
    ),
    (
        "a minimum alone",
        "sh:qualifiedMinCount 1 ;",
        ["RoleShape-permits: sh:qualifiedMinCount"],
    ),
    (
        "a maximum alone",
        "sh:qualifiedMaxCount 2 ;",
        ["RoleShape-permits: sh:qualifiedMaxCount"],
    ),
    (
        "a disjointness flag alone",
        "sh:qualifiedValueShapesDisjoint true ;",
        ["RoleShape-permits: sh:qualifiedValueShapesDisjoint"],
    ),
    (
        "a range over a named value shape",
        """
        sh:qualifiedValueShape shp:CapabilityValueShape ;
        sh:qualifiedMinCount 1 ;
        sh:qualifiedMaxCount 2 ;
        """,
        [
            "RoleShape-permits: sh:qualifiedMaxCount",
            "RoleShape-permits: sh:qualifiedMinCount",
            "RoleShape-permits: sh:qualifiedValueShape",
        ],
    ),
    (
        "a range over an inline value shape",
        """
        sh:qualifiedValueShape [ sh:class biz:Capability ] ;
        sh:qualifiedMinCount 1 ;
        sh:qualifiedMaxCount 2 ;
        """,
        [
            "RoleShape-permits: sh:qualifiedMaxCount",
            "RoleShape-permits: sh:qualifiedMinCount",
            "RoleShape-permits: sh:qualifiedValueShape",
        ],
    ),
)

#: The same range split into one block per count, each with its own message and its
#: own fixture. That is the shape a qualified constraint has to take to satisfy every
#: other rule in this file, so it is the arrangement someone would reach for, and it
#: is refused like the rest.
QUALIFIED_RANGE_IN_TWO_BLOCKS = (
    PREFIXES
    + """
shp:RoleShape
    a sh:NodeShape ;
    sh:targetClass biz:Role ;

    sh:property [
        sh:path biz:permits ;
        sh:qualifiedValueShape shp:CapabilityValueShape ;
        sh:qualifiedMinCount 1 ;
        sh:message "Role {$this} permits no capability." ;
    ] ;

    sh:property [
        sh:path biz:permits ;
        sh:qualifiedValueShape shp:CapabilityValueShape ;
        sh:qualifiedMaxCount 2 ;
        sh:message "Role {$this} permits more than two capabilities." ;
    ] .

shp:CapabilityValueShape a sh:NodeShape ; sh:class biz:Capability .
"""
)

#: A role permitting nothing, and a role permitting one goal. The first is the fixture
#: a sh:qualifiedMinCount would be defended by; the second is the graph the rule
#: accepts or rejects depending only on its value shape, which is the half no fixture
#: written against a count is ever able to be.
ROLE_PERMITTING_NOTHING = "biz:r a biz:Role ."
ROLE_PERMITTING_A_GOAL = "biz:r a biz:Role ; biz:permits biz:g . biz:g a biz:Goal ."


def _role_shape_stating(block: str) -> str:
    """A shapes graph whose one property block over biz:permits states ``block``."""
    return f"""{PREFIXES}
shp:RoleShape
    a sh:NodeShape ;
    sh:targetClass biz:Role ;

    sh:property [
        sh:path biz:permits ;
        {block}
    ] .

shp:CapabilityValueShape a sh:NodeShape ; sh:class biz:Capability .
"""


def _node_shape_stating(block: str) -> str:
    """A shapes graph whose one node shape states ``block`` directly.

    Where sh:closed and the properties it ignores are written in practice: on the shape
    itself rather than inside a property block.
    """
    return f"""{PREFIXES}
shp:RoleShape
    a sh:NodeShape ;
    sh:targetClass biz:Role ;
    {block}
    .
"""


def _qualified_minimum_over(value_shape: str) -> str:
    """A sh:qualifiedMinCount of one, counting whatever ``value_shape`` admits."""
    return f"""{PREFIXES}
shp:RoleShape
    a sh:NodeShape ;
    sh:targetClass biz:Role ;

    sh:property [
        sh:path biz:permits ;
        sh:qualifiedValueShape {value_shape} ;
        sh:qualifiedMinCount 1 ;
        sh:message "Role {{$this}} permits no capability." ;
    ] .

shp:CapabilityValueShape a sh:NodeShape ; sh:class biz:Capability .
shp:AnyIdentifiedValueShape a sh:NodeShape ; sh:nodeKind sh:IRI .
"""


#: Both modifiers written where a shape nests another: inside an sh:node, under a
#: property shape. Nothing about the refusal reads the top level of the graph, and this
#: is the spelling that says so.
MODIFIERS_ON_A_NESTED_SHAPE = (
    PREFIXES
    + """
shp:RoleShape
    a sh:NodeShape ;
    sh:targetClass biz:Role ;

    sh:property [
        sh:path biz:permits ;
        sh:node [
            sh:closed true ;
            sh:ignoredProperties ( rdf:type ) ;
            sh:pattern "^[a-z]+$" ;
            sh:flags "i" ;
        ] ;
    ] .
"""
)

#: Every spelling of an unsafe modifier the prohibition has to catch: each term beside
#: the parameter it moves, each on its own, and both nested inside another shape. A
#: modifier written alone states nothing at all, which is exactly why it has to be
#: refused there too - it is the arrangement that gets added first and completed later.
UNSAFE_MODIFIER_SPELLINGS = (
    (
        "flags beside a pattern",
        _role_shape_stating('sh:pattern "^[a-z]+$" ; sh:flags "i" ;'),
        ["RoleShape-permits: sh:flags"],
    ),
    (
        "flags alone",
        _role_shape_stating('sh:flags "i" ;'),
        ["RoleShape-permits: sh:flags"],
    ),
    (
        "ignored properties beside a closed shape",
        _node_shape_stating("sh:closed true ; sh:ignoredProperties ( rdf:type ) ;"),
        ["RoleShape: sh:ignoredProperties"],
    ),
    (
        "ignored properties alone",
        _node_shape_stating("sh:ignoredProperties ( rdf:type ) ;"),
        ["RoleShape: sh:ignoredProperties"],
    ),
    (
        "both on a nested property shape",
        MODIFIERS_ON_A_NESTED_SHAPE,
        ["RoleShape-permits-node: sh:flags", "RoleShape-permits-node: sh:ignoredProperties"],
    ),
)


def _label_pattern_with(flags: str) -> str:
    """A rule that a role's label is lower-case, with ``flags`` beside the pattern."""
    return f"""{PREFIXES}
shp:RoleShape
    a sh:NodeShape ;
    sh:targetClass biz:Role ;

    sh:property [
        sh:path rdfs:label ;
        sh:pattern "^[a-z ]+$" ;
        {flags}
        sh:message "Role {{$this}} has a label that is not lower-case." ;
    ] .
"""


def _closed_role_ignoring(ignored: str) -> str:
    """A role shape closed to all but biz:permits, also ignoring ``ignored``."""
    return f"""{PREFIXES}
shp:RoleShape
    a sh:NodeShape ;
    sh:targetClass biz:Role ;
    sh:closed true ;
    sh:ignoredProperties ( rdf:type {ignored} ) ;
    sh:message "Role {{$this}} carries a property this shape does not declare." ;

    sh:property [ sh:path biz:permits ] .
"""


class Widening(NamedTuple):
    """One modifier, moving a rule while the fixture defending that rule stays red.

    ``committed`` is the graph a negative fixture would commit: rejected under both
    spellings, and for the same message both times. ``moved`` is where the two disagree,
    and it is the graph no fixture written against the parameter alone ever is.
    """

    narrow: str
    widened: str
    committed: str
    moved: str
    message: str


#: The evidence that each unsafe modifier is unsafe, one entry per term, run against
#: pyshacl rather than asserted. This is what anchors an otherwise hand-written family:
#: a term dropped from UNSAFE_MODIFIERS while its widening still stands fails the build.
MODIFIER_WIDENINGS = {
    SH.flags: Widening(
        narrow=_label_pattern_with(""),
        widened=_label_pattern_with('sh:flags "i" ;'),
        committed='biz:r a biz:Role ; rdfs:label "role 2" .',
        moved='biz:r a biz:Role ; rdfs:label "Deploy Engineer" .',
        message="Role {$this} has a label that is not lower-case.",
    ),
    SH.ignoredProperties: Widening(
        narrow=_closed_role_ignoring(""),
        widened=_closed_role_ignoring("rdfs:label"),
        committed="biz:r a biz:Role ; biz:grantsRole biz:other .",
        moved='biz:r a biz:Role ; rdfs:label "deploy engineer" .',
        message="Role {$this} carries a property this shape does not declare.",
    ),
}


def _data(body: str) -> Graph:
    return Graph().parse(data=f"{PREFIXES}\n{body}", format="turtle")


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
        "RoleShape-permits-node",
        "RoleShape-permits-node-class",
    ]


@pytest.mark.parametrize(
    ("block", "expected"),
    [spelling[1:] for spelling in QUALIFIED_SPELLINGS],
    ids=[spelling[0] for spelling in QUALIFIED_SPELLINGS],
)
def test_every_spelling_of_a_qualified_constraint_is_refused(block, expected):
    """Each term of the family, alone and in a complete range, named and inline.

    The prohibition reads the parsed graph rather than the file's text, so what has to
    be exercised is every way the family can reach that graph. A spelling missed here
    is a spelling that reaches biz.ttl with nothing to stop it.
    """
    written = _forbidden_terms(Graph().parse(data=_role_shape_stating(block), format="turtle"))
    assert written == expected
    assert "the SHACL qualified family" in _prohibition(written)


def test_a_qualified_range_split_across_two_blocks_is_refused():
    """The arrangement the rest of this file would otherwise accept.

    One block per count, one message each, one fixture each: that satisfies every other
    rule here, which is exactly why the refusal has to reach it. Both blocks report at
    the same place, because the place to go and edit is the path, not the block.
    """
    shapes = Graph().parse(data=QUALIFIED_RANGE_IN_TWO_BLOCKS, format="turtle")
    assert _forbidden_terms(shapes) == [
        "RoleShape-permits: sh:qualifiedMaxCount",
        "RoleShape-permits: sh:qualifiedMinCount",
        "RoleShape-permits: sh:qualifiedValueShape",
    ]


def test_a_qualified_value_shape_moves_the_rule_its_counts_state():
    """The reason for the prohibition, run against the validator rather than asserted.

    Widening the value shape changes which values a count counts, and the fixture that
    defends the count cannot see it: a role permitting nothing trips the minimum under
    either value shape, so it goes on failing for exactly its committed reason while
    the rule it was committed against has moved. A role permitting one goal is where
    the two disagree, and no fixture written against a count is ever that graph.
    """
    strict = _qualified_minimum_over("shp:CapabilityValueShape")
    widened = _qualified_minimum_over("shp:AnyIdentifiedValueShape")
    tripped = {"Role {$this} permits no capability."}

    assert _messages_against(strict, _data(ROLE_PERMITTING_NOTHING)) == tripped
    assert _messages_against(widened, _data(ROLE_PERMITTING_NOTHING)) == tripped

    assert _messages_against(strict, _data(ROLE_PERMITTING_A_GOAL)) == tripped
    assert _messages_against(widened, _data(ROLE_PERMITTING_A_GOAL)) == set()


@pytest.mark.parametrize(
    ("shapes", "expected"),
    [spelling[1:] for spelling in UNSAFE_MODIFIER_SPELLINGS],
    ids=[spelling[0] for spelling in UNSAFE_MODIFIER_SPELLINGS],
)
def test_every_spelling_of_an_unsafe_modifier_is_refused(shapes, expected):
    """Each modifier beside its parameter, alone, and nested inside another shape.

    The prohibition reads the parsed graph rather than the file's text, so what has to
    be exercised is every way a modifier can reach that graph. A spelling missed here is
    a spelling that reaches biz.ttl with nothing to stop it - and the message a reader
    gets has to be the one about modifiers, not the one about qualified counts.
    """
    written = _forbidden_terms(Graph().parse(data=shapes, format="turtle"))
    assert written == expected
    assert "the SHACL modifiers that move the rule beside them" in _prohibition(written)


def test_a_refused_term_in_a_second_shapes_file_is_refused(tmp_path):
    """The shapes graph is every *.ttl under ontology/shapes/, loaded into one graph.

    So a refused term is not made acceptable by being written in a file of its own,
    which is the first thing a reader blocked by the prohibition would try. The audit
    reads the loaded graph, and this reads it the way the build does - through
    ``graph.turtle_files`` and ``graph.load`` - so both files report by the block that
    wrote them.
    """
    (tmp_path / "biz.ttl").write_text(
        _node_shape_stating("sh:ignoredProperties ( rdf:type ) ;"), encoding="utf-8"
    )
    (tmp_path / "extra.ttl").write_text(_role_shape_stating('sh:flags "i" ;'), encoding="utf-8")

    assert _forbidden_terms(graph.load(graph.turtle_files(tmp_path))) == [
        "RoleShape-permits: sh:flags",
        "RoleShape: sh:ignoredProperties",
    ]


def test_the_unsafe_modifier_family_agrees_with_its_evidence_and_its_spellings():
    """The one thing anchoring a family that cannot be read off the validator.

    The qualified family is computed from ALL_CONSTRAINT_PARAMETERS, so narrowing it is
    a red build. The modifiers have no such spelling in common: dropping sh:flags from
    UNSAFE_MODIFIERS would take the prohibition with it and nothing else here would
    notice. What stands in for the validator is the evidence each term has to carry - a
    widening demonstrated against pyshacl, and a spelling proved refused - which a term
    cannot be added without and cannot be removed while it stands.
    """
    family = sorted(_local(term) for term in UNSAFE_MODIFIERS)
    demonstrated = sorted(_local(term) for term in MODIFIER_WIDENINGS)
    refused = sorted(
        {
            name.rsplit(": sh:", 1)[-1]
            for _, _, expected in UNSAFE_MODIFIER_SPELLINGS
            for name in expected
        }
    )
    assert family == demonstrated == refused, (
        f"UNSAFE_MODIFIERS refuses {family}, MODIFIER_WIDENINGS shows {demonstrated} "
        f"moving a rule, and UNSAFE_MODIFIER_SPELLINGS proves {refused} refused. The "
        f"three are the whole of what makes this family more than a list somebody typed: "
        f"a term added to it brings a widening and a spelling with it, and a term removed "
        f"from it while either still stands fails here."
    )


@pytest.mark.parametrize(
    ("term", "widening"),
    sorted(MODIFIER_WIDENINGS.items(), key=lambda entry: str(entry[0])),
    ids=[_local(term) for term in sorted(MODIFIER_WIDENINGS, key=str)],
)
def test_each_unsafe_modifier_moves_the_rule_beside_it(term, widening):
    """The reason for the prohibition, run against the validator rather than asserted.

    A modifier changes where its parameter draws the line, and the fixture defending
    that parameter cannot see it: the graph a fixture commits is rejected under both
    spellings, with the same message both times, so it goes on failing for exactly its
    committed reason while the rule it was committed against has moved. The graph where
    the two disagree is the one no such fixture is.
    """
    tripped = {widening.message}

    assert _messages_against(widening.narrow, _data(widening.committed)) == tripped
    assert _messages_against(widening.widened, _data(widening.committed)) == tripped

    assert _messages_against(widening.narrow, _data(widening.moved)) == tripped
    assert _messages_against(widening.widened, _data(widening.moved)) == set()
