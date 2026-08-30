"""An L2 identifier is minted from the source's immutable id, and never from a name.

This is the whole difference from L1. An L1 slug is authored by a human who will not
change their mind quietly; an L2 local id is handed over by a system that renames things
without telling anyone, and means nothing outside that system. So the rules here are
about two failures L1 cannot have: a rename minting a second entity, and two sources
minting the same one.
"""

import pytest
from rdflib import RDF, URIRef

from semantic_layer import graph, ids

TECH = "https://semantic-layer.19h09.co/vocab/tech#"


def test_a_source_is_named_by_the_scope_it_is():
    assert (
        ids.mint_source("github", "api-github-com")
        == "https://semantic-layer.19h09.co/l2/github/api-github-com"
    )


def test_an_entity_is_minted_under_its_source():
    """Which is the whole of what "source-scoped" means: the source IRI is the prefix."""
    source = ids.mint_source("github", "api-github-com")
    repository = ids.mint_observed("github", "api-github-com", "repository", "1347717349")
    assert repository == f"{source}/repository/1347717349"


def test_fixtures_are_minted_under_a_namespace_accepted_observations_never_use():
    assert (
        ids.mint_observed("github", "api-github-com", "repository", "1", fixture=True)
        == "https://semantic-layer.19h09.co/fixture/l2/github/api-github-com/repository/1"
    )
    assert ids.FIXTURE_OBSERVED_SEGMENT not in ids.mint_observed(
        "github", "api-github-com", "repository", "1"
    )


def test_a_rename_changes_no_identifier():
    """The point of minting from the id: the same repository under a new path.

    Nothing about minting takes a name, so this cannot be got wrong by passing the
    wrong argument - there is no argument to pass. The reconciler's half of it is in
    tests/test_reconciliation.py, which renames a repository and compares the graphs.
    """
    before = ids.mint_observed("github", "api-github-com", "repository", "1347717349")
    after = ids.mint_observed("github", "api-github-com", "repository", "1347717349")
    assert before == after


@pytest.mark.parametrize(
    ("provider", "instance"),
    [
        ("gitlab", "api-github-com"),
        ("github", "github-example-org"),
    ],
    ids=["another provider", "another installation"],
)
def test_the_same_local_id_at_another_source_is_another_entity(provider, instance):
    """The collision source scoping exists to prevent.

    GitHub's numeric ids mean nothing outside GitHub, and nothing outside the
    installation that issued them: a GitHub Enterprise host issues id 1347717349 to
    something else entirely. Two entities sharing a local id have to end up with two
    identifiers, or the graph says they are one thing.
    """
    assert ids.mint_observed("github", "api-github-com", "repository", "1347717349") != (
        ids.mint_observed(provider, instance, "repository", "1347717349")
    )


def test_a_branch_carries_the_repository_that_gives_its_name_meaning():
    """GitHub issues a branch no id, and git has none to issue.

    So the identity is the pair, and it is spelled out rather than flattened into one
    string somebody would later have to split on a character branch names can contain.
    """
    assert (
        ids.mint_observed("github", "api-github-com", "branch", "1347717349", "main")
        == "https://semantic-layer.19h09.co/l2/github/api-github-com/branch/1347717349/main"
    )


@pytest.mark.parametrize(
    ("kind", "local_id"),
    [("repository", ("1", "2")), ("branch", ("1",)), ("branch", ("1", "main", "extra"))],
    ids=["repository given two", "branch given one", "branch given three"],
)
def test_a_kind_takes_the_number_of_local_id_segments_it_takes(kind, local_id):
    with pytest.raises(ids.IdentifierError):
        ids.mint_observed("github", "api-github-com", kind, *local_id)


@pytest.mark.parametrize(
    "name",
    [
        "../../etc/passwd",
        "feature/a b",
        "wat?x=1",
        "frag#ment",
        "semi;colon",
        "percent%2F",
        "unicode-é",
    ],
)
def test_hostile_text_from_the_source_cannot_become_structure(name):
    """A branch name is whatever somebody pushed, and it lands in an identifier.

    Percent-encoding is the one seam where that stops being dangerous: whatever the
    source called it, the identifier has exactly the segments minting gave it, and
    parsing hands the original text back unchanged.
    """
    iri = ids.mint_observed("github", "api-github-com", "branch", "1347717349", name)
    parsed = ids.parse_observed(iri)
    assert parsed.local_id == ("1347717349", name)
    assert iri.count("/") == ids.mint_observed(
        "github", "api-github-com", "branch", "1347717349", "main"
    ).count("/")


@pytest.mark.parametrize("segment", ["", ".", ".."])
def test_a_local_id_a_resolver_would_collapse_is_refused(segment):
    """Nothing resolves these IRIs, so neither dot segment is a vulnerability here.

    They are refused because an identifier that means one thing before normalization
    and another after is not a stable identifier, and the two readers who disagree
    about it will not find out that they do.
    """
    with pytest.raises(ids.IdentifierError):
        ids.mint_observed("github", "api-github-com", "branch", "1347717349", segment)


@pytest.mark.parametrize("provider", ["GitHub", "git_hub", "git--hub", "-github", ""])
def test_a_provider_that_could_be_written_two_ways_is_refused(provider):
    with pytest.raises(ids.IdentifierError):
        ids.mint_source(provider, "api-github-com")


def test_an_unknown_observed_kind_is_rejected():
    with pytest.raises(ids.IdentifierError):
        ids.mint_observed("github", "api-github-com", "pull-request", "7")


@pytest.mark.parametrize("fixture", [False, True])
def test_parse_is_the_inverse_of_mint(fixture):
    iri = ids.mint_observed(
        "github", "api-github-com", "branch", "1347717349", "release/1.4", fixture=fixture
    )
    assert ids.parse_observed(iri) == ids.ObservedIdentifier(
        provider="github",
        instance="api-github-com",
        kind="branch",
        local_id=("1347717349", "release/1.4"),
        fixture=fixture,
    )
    source = ids.mint_source("github", "api-github-com", fixture=fixture)
    assert ids.parse_source(source) == ids.SourceIdentifier("github", "api-github-com", fixture)


@pytest.mark.parametrize(
    "iri",
    [
        "https://example.org/l2/github/api-github-com/repository/1",
        "https://semantic-layer.19h09.co/biz/capability/payments",
        "https://semantic-layer.19h09.co/l2/github/api-github-com/pull-request/7",
        "https://semantic-layer.19h09.co/l2/github/api-github-com/repository/1/2",
        "https://semantic-layer.19h09.co/l2/github/api-github-com/branch/1",
        "https://semantic-layer.19h09.co/l2/GitHub/api-github-com/repository/1",
        # The same branch spelled with lower-case percent escapes. It denotes the same
        # name and is a different string, so two graphs written either way would hold
        # two entities; only one spelling is minted, so only one is accepted.
        "https://semantic-layer.19h09.co/l2/github/api-github-com/branch/1/release%2f1.4",
    ],
)
def test_parse_rejects_anything_minting_would_not_have_produced(iri):
    with pytest.raises(ids.IdentifierError):
        ids.parse_observed(iri)


def _typed_observed_entities(paths):
    """Every technical entity in ``paths`` that has an identifier to check.

    Whether it has one at all is shpt:TechIdentityShape's question, which is why a
    blank node is skipped here rather than failed: one of the invalid fixtures is
    deliberately anonymous, and it is the shape that must reject it.
    """
    data = graph.load(paths)
    for subject, _, rdf_class in data.triples((None, RDF.type, None)):
        if isinstance(subject, URIRef) and str(rdf_class).startswith(TECH):
            yield subject, rdf_class


@pytest.mark.parametrize(
    ("directory", "fixture"),
    [
        (graph.TECHNICAL_DIR, False),
        (graph.TECHNICAL_VALID_FIXTURES_DIR, True),
        (graph.TECHNICAL_INVALID_FIXTURES_DIR, True),
        (graph.INVALID_FIXTURES_DIR, True),
    ],
    ids=["accepted", "valid-fixtures", "invalid-fixtures", "l1-invalid-fixtures"],
)
def test_every_committed_observed_entity_carries_the_identifier_minting_would_give_it(
    directory, fixture
):
    for subject, rdf_class in _typed_observed_entities(graph.turtle_files(directory)):
        if str(rdf_class) == f"{TECH}Source":
            identifier = ids.parse_source(str(subject))
        else:
            kind = ids.OBSERVED_KIND_BY_CLASS.get(str(rdf_class))
            assert kind is not None, f"{subject} is typed {rdf_class}, which mints no identifier"
            identifier = ids.parse_observed(str(subject))
            assert identifier.kind == kind, (
                f"{subject} is a {kind} but its IRI says {identifier.kind}"
            )
        assert identifier.fixture is fixture, (
            f"{subject} lives in {directory.name} but is minted in the wrong namespace"
        )


def test_the_accepted_graph_holds_observed_entities_to_check():
    """An empty walk above would prove nothing, and this is the directory that matters."""
    assert list(_typed_observed_entities(graph.turtle_files(graph.TECHNICAL_DIR)))
