"""IRI minting for the semantic layer. The one place identity rules live.

An identifier is a URL because a URL is globally unique without a registry, not
because anything is expected to be served from it. See docs/identifiers.md.

Identifiers are never reused and never renamed. A rename mints a new IRI and points
it at the old one with ``core:supersedes``; the old one stays, deprecated.
"""

from __future__ import annotations

import re
from typing import NamedTuple

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
