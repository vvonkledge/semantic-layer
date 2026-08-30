"""Context packs: one observation, bounded, hashed, and checkable by whoever receives it.

A pack is what leaves this repository. Everything else here is for the people who
maintain the layer; this is for a consumer who has none of the context, cannot see the
git history, and has to decide whether to act on what they were handed.

So a pack is two files and no cleverness. The content is sorted N-Triples - canonical,
so two producers of the same observation emit the same bytes and a consumer can hash
it and compare. The manifest says which graph it came from, which source, which
observation, when that observation was made, when it stops being worth believing, why
it should be believed at all, and what the content hashes to.

``verify`` is the other half and is the reason the manifest is worth writing. It is not
a formality run once at build time: it is what a consumer runs, against an instant they
supply and a source they expected, and it is the only thing standing between them and a
pack that is stale, tampered with, or about something else entirely.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from rdflib import Graph, URIRef
from rdflib.namespace import RDF

from semantic_layer import graph as layer
from semantic_layer.github import INSTANT_FORMAT, INSTANT_PATTERN, digest_of
from semantic_layer.serialize import ntriples

TECH = layer.TECH

PACK_VERSION = 1

CONTENT_MEDIA_TYPE = "application/n-triples"

CONTENT_NAME = "content.nt"
MANIFEST_NAME = "manifest.json"


class PackError(ValueError):
    """A pack could not be built, or could not be believed."""


@dataclass(frozen=True)
class Pack:
    content: bytes
    manifest: bytes


def _one(subgraph: Graph, subject: URIRef, predicate: URIRef, what: str):
    values = list(subgraph.objects(subject, predicate))
    if len(values) != 1:
        raise PackError(
            f"{subject} has {len(values)} values for {what}, and a pack needs exactly one. "
            f"The shapes reject this; a graph that reached here without passing them is the "
            f"thing to fix."
        )
    return values[0]


def observed(instances: Iterable[Path]) -> Graph:
    """The observed half of the layer, on its own.

    A pack carries technical truth. Curated business truth is not withheld from a
    consumer out of caution - it is a different thing, with no observation behind it
    and no freshness to state, and putting the two in one artifact would give the
    business half an expiry date it has no way to honour.
    """
    return layer.data_graph(instances).graph(layer.OBSERVED_GRAPH)


def build(observed: Graph, observation: URIRef) -> Pack:
    """The pack for one observation: what it saw, and nothing that it did not.

    Takes the observed graph rather than the files it came from, so a candidate can be
    packed before it is committed anywhere - which is also the only way the whole path
    from a captured response to a verified pack can be exercised in one test.
    """
    if (observation, RDF.type, TECH.Observation) not in observed:
        raise PackError(
            f"{observation} is not an observation in the observed graph, so there is nothing "
            f"to pack. A pack is built for one reading of one source."
        )

    source = _one(observed, observation, TECH.observedFrom, "tech:observedFrom")
    artifacts = sorted(observed.subjects(TECH.observedIn, observation), key=str)

    content = Graph()
    for subject in [source, observation, *artifacts]:
        for predicate, obj in observed.predicate_objects(subject):
            content.add((subject, predicate, obj))

    body = ntriples(content).encode("utf-8")
    manifest = {
        "pack_version": PACK_VERSION,
        "graph": str(layer.OBSERVED_GRAPH),
        "vocabulary_version": _vocabulary_version(),
        "source": str(source),
        "provider": str(_one(observed, source, TECH.provider, "tech:provider")),
        "api_root": str(_one(observed, source, TECH.apiRoot, "tech:apiRoot")),
        "trust_basis": str(_one(observed, source, TECH.trustBasis, "tech:trustBasis")),
        "observation": str(observation),
        "target": str(
            _one(observed, observation, TECH.observationTarget, "tech:observationTarget")
        ),
        "observed_at": _instant(observed, observation, TECH.observedAt, "tech:observedAt"),
        "fresh_until": _instant(observed, observation, TECH.freshUntil, "tech:freshUntil"),
        "snapshot_digest": str(
            _one(observed, observation, TECH.snapshotDigest, "tech:snapshotDigest")
        ),
        "content_media_type": CONTENT_MEDIA_TYPE,
        "content_digest": digest_of(body),
        "content_bytes": len(body),
        "artifact_count": len(artifacts),
    }
    return Pack(content=body, manifest=render(manifest))


def render(manifest: Mapping) -> bytes:
    return (json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()


def _vocabulary_version() -> str:
    """What a consumer compiles against.

    Read from the vocabulary rather than repeated here, so bumping owl:versionInfo is
    the whole of what it takes and there is no second copy to fall behind.
    """
    from rdflib.namespace import OWL

    vocabulary = Graph().parse(layer.ONTOLOGY / "tech.ttl", format="turtle")
    iri = URIRef("https://semantic-layer.19h09.co/vocab/tech")
    version = vocabulary.value(iri, OWL.versionInfo)
    if version is None:
        raise PackError(f"{iri} declares no owl:versionInfo, so a consumer has nothing to pin to")
    return str(version)


def _instant(subgraph: Graph, subject: URIRef, predicate: URIRef, what: str) -> str:
    """One instant, in the one spelling this repository writes.

    rdflib normalizes an xsd:dateTime when it parses one, so the value read back from a
    Turtle file spells UTC as +00:00 where the file spelled it Z. The two are the same
    instant, but a manifest is compared against by string in places a consumer controls
    and this repository does not, so it commits to one spelling and writes it.
    """
    value = str(_one(subgraph, subject, predicate, what))
    try:
        stamped = datetime.fromisoformat(value)
    except ValueError as error:
        raise PackError(f"{subject} has {what} of {value!r}, which is not an instant") from error
    if stamped.tzinfo is None:
        raise PackError(
            f"{subject} has {what} of {value!r}, which names no timezone. An instant with no "
            f"offset means something different to every reader, and a pack is read by people "
            f"this repository never meets."
        )
    return stamped.astimezone(UTC).strftime(INSTANT_FORMAT)


def verify(
    content: bytes,
    manifest: bytes,
    *,
    as_of: str,
    expect_source: str | None = None,
    expect_target: str | None = None,
) -> Mapping:
    """Refuse a pack that has been tampered with, is about something else, or is stale.

    ``as_of`` is the consumer's own instant, supplied here rather than read from the
    clock, because a pack verified against "now" answers a different question every
    time it is run and cannot be tested at all.
    """
    try:
        stated = json.loads(manifest)
    except json.JSONDecodeError as error:
        raise PackError(f"the manifest is not valid JSON: {error}") from error
    if not isinstance(stated, dict):
        raise PackError("the manifest is not an object")

    version = stated.get("pack_version")
    if version != PACK_VERSION:
        raise PackError(
            f"the manifest declares pack_version {version!r} and this reader understands "
            f"{PACK_VERSION}. A pack written in another layout is refused rather than "
            f"reinterpreted."
        )

    digest = digest_of(content)
    if stated.get("content_digest") != digest:
        raise PackError(
            f"the content hashes to {digest} and the manifest claims "
            f"{stated.get('content_digest')!r}. The two halves of this pack do not belong to "
            f"each other: one of them was changed after the other was written."
        )
    if stated.get("content_bytes") != len(content):
        raise PackError(
            f"the content is {len(content)} bytes and the manifest claims "
            f"{stated.get('content_bytes')!r}."
        )

    graph = Graph().parse(data=content, format="nt")
    observation = URIRef(str(stated.get("observation")))
    if (observation, RDF.type, TECH.Observation) not in graph:
        raise PackError(
            f"the manifest names {observation} as its observation and the content does not "
            f"contain it. A manifest describing content it did not come from cannot be "
            f"checked against anything."
        )
    # Every field a consumer reads off the manifest without parsing the graph, held
    # against what the graph says. A manifest that disagrees with its own content is
    # worse than no manifest: it is read first and believed.
    for key, predicate, is_instant in (
        ("observed_at", TECH.observedAt, True),
        ("fresh_until", TECH.freshUntil, True),
        ("target", TECH.observationTarget, False),
        ("snapshot_digest", TECH.snapshotDigest, False),
    ):
        what = f"tech:{predicate.removeprefix(str(TECH))}"
        held = (
            _instant(graph, observation, predicate, what)
            if is_instant
            else str(_one(graph, observation, predicate, what))
        )
        if stated.get(key) != held:
            raise PackError(
                f"the manifest says {key} is {stated.get(key)!r} and the content says "
                f"{held!r}. The manifest is what a consumer reads without parsing the graph, "
                f"so the two disagreeing makes the manifest worse than absent."
            )

    source = str(_one(graph, observation, TECH.observedFrom, "tech:observedFrom"))
    if stated.get("source") != source:
        raise PackError(
            f"the manifest says the source is {stated.get('source')!r} and the content says "
            f"{source!r}."
        )

    if expect_source is not None and source != expect_source:
        raise PackError(
            f"this pack is from {source}, and {expect_source} was expected. An identifier "
            f"means nothing outside the source that issued it, so acting on a pack from "
            f"another source is acting on a different thing that happens to share a number."
        )
    if expect_target is not None and stated.get("target") != expect_target:
        raise PackError(
            f"this pack is about {stated.get('target')!r}, and {expect_target!r} was expected."
        )

    if not INSTANT_PATTERN.fullmatch(as_of):
        raise PackError(
            f"as_of is {as_of!r}, which is not a UTC instant spelled YYYY-MM-DDTHH:MM:SSZ"
        )
    if as_of >= stated["fresh_until"]:
        raise PackError(
            f"this pack was observed at {stated['observed_at']} and stops being worth "
            f"believing at {stated['fresh_until']}, which is not after {as_of}. Refresh the "
            f"observation rather than acting on a reading that has already said it is out "
            f"of date."
        )
    return stated


def pack_dir(instance: str = "vvonkledge-siana") -> Path:
    from semantic_layer.github import PROVIDER

    return layer.PACKS_DIR / PROVIDER / instance


def write(pack: Pack, directory: Path) -> None:
    from semantic_layer.acquire import write_atomically

    write_atomically(directory / CONTENT_NAME, pack.content)
    write_atomically(directory / MANIFEST_NAME, pack.manifest)


def read(directory: Path) -> Pack:
    return Pack(
        content=(directory / CONTENT_NAME).read_bytes(),
        manifest=(directory / MANIFEST_NAME).read_bytes(),
    )


def accepted() -> Graph:
    """The observed graph as it stands, accepted and committed."""
    return observed(layer.turtle_files(layer.TECHNICAL_DIR))


def accepted_observation() -> URIRef:
    """The one observation the accepted L2 graph holds."""
    observations = sorted(accepted().subjects(RDF.type, TECH.Observation), key=str)
    if len(observations) != 1:
        raise PackError(
            f"the accepted graph holds {len(observations)} observations, and this command "
            f"packs one. Name the observation to pack."
        )
    return observations[0]


def main() -> None:
    directory = pack_dir()
    observation = accepted_observation()
    write(build(accepted(), observation), directory)
    print(f"packed {observation}")
    print(f"  {directory / CONTENT_NAME}")
    print(f"  {directory / MANIFEST_NAME}")


if __name__ == "__main__":
    main()
