"""IRI minting for the semantic layer. The one place identity rules live.

An identifier is a URL because a URL is globally unique without a registry, not
because anything is expected to be served from it. See docs/identifiers.md.

Identifiers are never reused and never renamed. A rename mints a new IRI and points
it at the old one with ``core:supersedes``; the old one stays, deprecated.
"""

from __future__ import annotations

import re
from typing import NamedTuple
from urllib.parse import quote, unquote

BASE = "https://semantic-layer.19h09.co/"

#: Curated L1 content, authored by humans under review.
BUSINESS_SEGMENT = "biz/"

#: Test data. No curated entity ever uses this segment, so a fixture cannot be
#: mistaken for a statement about the organization.
FIXTURE_SEGMENT = "fixture/biz/"

#: The entity kinds L1 mints identifiers for, one per concrete business class.
KIND_BY_CLASS = {
    "https://semantic-layer.19h09.co/vocab/biz#Goal": "goal",
    "https://semantic-layer.19h09.co/vocab/biz#Capability": "capability",
    "https://semantic-layer.19h09.co/vocab/biz#Person": "person",
    "https://semantic-layer.19h09.co/vocab/biz#Team": "team",
    "https://semantic-layer.19h09.co/vocab/biz#AgentIdentity": "agent",
    "https://semantic-layer.19h09.co/vocab/biz#Role": "role",
    "https://semantic-layer.19h09.co/vocab/biz#Policy": "policy",
    "https://semantic-layer.19h09.co/vocab/biz#Assignment": "assignment",
}

KINDS = frozenset(KIND_BY_CLASS.values())

#: Lowercase words joined by single hyphens. Narrow on purpose: a slug that can only
#: be written one way cannot be written two ways for the same entity.
SLUG_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


class IdentifierError(ValueError):
    """An identifier could not be minted, or does not follow the minting rules."""


class Identifier(NamedTuple):
    kind: str
    slug: str
    fixture: bool


def mint(kind: str, slug: str, *, fixture: bool = False) -> str:
    """Return the IRI for a business entity of ``kind`` with the stable ``slug``."""
    if kind not in KINDS:
        raise IdentifierError(f"unknown entity kind {kind!r}; expected one of {sorted(KINDS)}")
    if not SLUG_PATTERN.fullmatch(slug):
        raise IdentifierError(
            f"{slug!r} is not a valid slug: lowercase letters and digits, joined by single hyphens"
        )
    segment = FIXTURE_SEGMENT if fixture else BUSINESS_SEGMENT
    return f"{BASE}{segment}{kind}/{slug}"


def parse(iri: str) -> Identifier:
    """Take an IRI apart, rejecting anything ``mint`` would not have produced."""
    if not iri.startswith(BASE):
        raise IdentifierError(f"{iri!r} is not under the semantic layer base {BASE!r}")
    rest = iri[len(BASE) :]
    fixture = rest.startswith(FIXTURE_SEGMENT)
    segment = FIXTURE_SEGMENT if fixture else BUSINESS_SEGMENT
    if not rest.startswith(segment):
        raise IdentifierError(f"{iri!r} names no known content segment")
    parts = rest[len(segment) :].split("/")
    if len(parts) != 2:
        raise IdentifierError(f"{iri!r} is not of the form <base><segment><kind>/<slug>")
    kind, slug = parts
    if mint(kind, slug, fixture=fixture) != iri:
        raise IdentifierError(f"{iri!r} is not the identifier minting would produce")
    return Identifier(kind=kind, slug=slug, fixture=fixture)


## L2: observed technical truth.
#
# An L1 identifier is a human-authored slug, because L1 is small, curated and named in
# the language the business uses. Nothing about that carries over. An L2 entity is not
# authored, it is observed, and the thing being observed already has a name in the
# system it was observed from - one that is often renamed, and one that only means
# anything alongside the system that issued it. So an L2 identifier is scoped by its
# source and built from the source's own immutable identity, never from a display name
# or a path a human can change.
#
# The source is the scope, so it is named by the scope and nothing more:
#
#     source     https://semantic-layer.19h09.co/l2/<provider>/<instance>
#     entity     https://semantic-layer.19h09.co/l2/<provider>/<instance>/<kind>/<local id>
#
# Two providers cannot collide because they differ at <provider>; two installations of
# one provider - github.com and a GitHub Enterprise host - cannot collide because they
# differ at <instance>. That is what "source-scoped" buys, and it is why the numeric
# id GitHub hands out is safe to use verbatim as a local id despite meaning nothing
# outside GitHub.

#: Accepted L2 truth, promoted by a reviewed change.
OBSERVED_SEGMENT = "l2/"

#: L2 test data. No accepted observation ever uses this segment.
FIXTURE_OBSERVED_SEGMENT = "fixture/l2/"

#: The L2 entity kinds, one per concrete technical class, mapped to the number of
#: local-id segments the kind takes. A kind's arity is part of the minting rule: it is
#: what makes an identifier parse back to exactly the parts it was built from, so a
#: branch of a repository can never be read as a repository of some other name.
OBSERVED_KIND_BY_CLASS = {
    "https://semantic-layer.19h09.co/vocab/tech#Observation": "observation",
    "https://semantic-layer.19h09.co/vocab/tech#Account": "account",
    "https://semantic-layer.19h09.co/vocab/tech#Repository": "repository",
    "https://semantic-layer.19h09.co/vocab/tech#Branch": "branch",
}

#: How many local-id segments each kind carries. One for anything the provider issues
#: an immutable id for; two for a branch, which the provider issues none for and which
#: git identifies by name within one repository.
OBSERVED_KIND_ARITY = {
    "observation": 1,
    "account": 1,
    "repository": 1,
    "branch": 2,
}

OBSERVED_KINDS = frozenset(OBSERVED_KIND_ARITY)

#: The two segments a path resolver would collapse. Nothing resolves these IRIs, so
#: neither is a vulnerability here, but an identifier whose meaning depends on whether
#: the reader normalized it is not a stable identifier, so both are refused outright.
TRAVERSAL_SEGMENTS = frozenset({".", ".."})


class ObservedIdentifier(NamedTuple):
    provider: str
    instance: str
    kind: str
    local_id: tuple[str, ...]
    fixture: bool


class SourceIdentifier(NamedTuple):
    provider: str
    instance: str
    fixture: bool


def _observed_segment(fixture: bool) -> str:
    return FIXTURE_OBSERVED_SEGMENT if fixture else OBSERVED_SEGMENT


def _scope(provider: str, instance: str) -> str:
    for name, value in (("provider", provider), ("instance", instance)):
        if not SLUG_PATTERN.fullmatch(value):
            raise IdentifierError(
                f"{value!r} is not a valid source {name}: lowercase letters and digits, "
                f"joined by single hyphens"
            )
    return f"{provider}/{instance}"


def _encode(segment: str, kind: str) -> str:
    """Percent-encode one local-id segment so a source's own text cannot escape it.

    A GitHub numeric id passes through untouched. A branch name is whatever somebody
    pushed, and this is the one place that stops a slash, a fragment or a query in it
    from turning into structure the parser would read back as a different entity.
    """
    if not segment:
        raise IdentifierError(f"a {kind} identifier has an empty local-id segment")
    if segment in TRAVERSAL_SEGMENTS:
        raise IdentifierError(
            f"a {kind} identifier has the local-id segment {segment!r}, which a path "
            f"resolver would collapse rather than read"
        )
    return quote(segment, safe="")


def mint_source(provider: str, instance: str, *, fixture: bool = False) -> str:
    """Return the IRI of the source that observations from ``provider`` are scoped by."""
    return f"{BASE}{_observed_segment(fixture)}{_scope(provider, instance)}"


def mint_observed(
    provider: str, instance: str, kind: str, *local_id: str, fixture: bool = False
) -> str:
    """Return the IRI of an observed entity of ``kind``, scoped by its source."""
    if kind not in OBSERVED_KINDS:
        raise IdentifierError(
            f"unknown observed entity kind {kind!r}; expected one of {sorted(OBSERVED_KINDS)}"
        )
    arity = OBSERVED_KIND_ARITY[kind]
    if len(local_id) != arity:
        raise IdentifierError(
            f"a {kind} identifier takes {arity} local-id segment(s), given {len(local_id)}"
        )
    encoded = "/".join(_encode(segment, kind) for segment in local_id)
    return f"{mint_source(provider, instance, fixture=fixture)}/{kind}/{encoded}"


def _observed_rest(iri: str) -> tuple[str, bool]:
    if not iri.startswith(BASE):
        raise IdentifierError(f"{iri!r} is not under the semantic layer base {BASE!r}")
    rest = iri[len(BASE) :]
    fixture = rest.startswith(FIXTURE_OBSERVED_SEGMENT)
    segment = _observed_segment(fixture)
    if not rest.startswith(segment):
        raise IdentifierError(f"{iri!r} names no observed content segment")
    return rest[len(segment) :], fixture


def parse_source(iri: str) -> SourceIdentifier:
    """Take a source IRI apart, rejecting anything ``mint_source`` would not produce."""
    rest, fixture = _observed_rest(iri)
    parts = rest.split("/")
    if len(parts) != 2:
        raise IdentifierError(f"{iri!r} is not of the form <base><segment><provider>/<instance>")
    provider, instance = parts
    if mint_source(provider, instance, fixture=fixture) != iri:
        raise IdentifierError(f"{iri!r} is not the source identifier minting would produce")
    return SourceIdentifier(provider=provider, instance=instance, fixture=fixture)


def parse_observed(iri: str) -> ObservedIdentifier:
    """Take an observed IRI apart, rejecting anything ``mint_observed`` would not produce."""
    rest, fixture = _observed_rest(iri)
    parts = rest.split("/")
    if len(parts) < 4:
        raise IdentifierError(
            f"{iri!r} is not of the form <base><segment><provider>/<instance>/<kind>/<local id>"
        )
    provider, instance, kind, *encoded = parts
    if kind not in OBSERVED_KINDS:
        raise IdentifierError(f"{iri!r} names the unknown observed entity kind {kind!r}")
    local_id = tuple(unquote(segment) for segment in encoded)
    if mint_observed(provider, instance, kind, *local_id, fixture=fixture) != iri:
        raise IdentifierError(f"{iri!r} is not the identifier minting would produce")
    return ObservedIdentifier(
        provider=provider, instance=instance, kind=kind, local_id=local_id, fixture=fixture
    )
