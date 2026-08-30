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
pack that is stale, tampered with, or about something else entirely. It holds every
field the manifest carries and refuses a manifest carrying a field it has no rule for,
because a manifest is read instead of the graph and so is believed field by field.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from rdflib import Graph, URIRef
from rdflib.exceptions import ParserError
from rdflib.namespace import RDF

from semantic_layer import graph as layer
from semantic_layer.github import INSTANT_FORMAT, INSTANT_PATTERN, digest_of
from semantic_layer.serialize import ntriples

TECH = layer.TECH

PACK_VERSION = 1

CONTENT_MEDIA_TYPE = "application/n-triples"

CONTENT_NAME = "content.nt"
MANIFEST_NAME = "manifest.json"

#: The field naming the layout, held first: a pack written in another one is refused
#: rather than reinterpreted, and its other fields are not this reader's to read.
VERSION_FIELD = "pack_version"

#: Fields that restate a triple in the content, as (field, subject, predicate). The
#: subject is named rather than searched for, because the two nodes a pack carries say
#: different kinds of thing - the observation is one reading, the source is the system
#: that was read - and holding a field against the wrong one compares it to a value
#: nothing minted it from.
CONTENT_FIELDS = (
    ("source", "observation", TECH.observedFrom),
    ("target", "observation", TECH.observationTarget),
    ("observed_at", "observation", TECH.observedAt),
    ("fresh_until", "observation", TECH.freshUntil),
    ("snapshot_digest", "observation", TECH.snapshotDigest),
    ("provider", "source", TECH.provider),
    ("api_root", "source", TECH.apiRoot),
    ("trust_basis", "source", TECH.trustBasis),
)

#: Which of those are instants, and so are compared after being spelled the one way
#: this repository writes them rather than as whatever rdflib parsed them back as.
INSTANT_FIELDS = frozenset({"observed_at", "fresh_until"})

#: Fields the content does not restate but does determine: which observation it
#: names, what it hashes to, how long it is, and how many artifacts it holds. Each
#: is recounted or recomputed from the content rather than believed.
DERIVED_FIELDS = ("observation", "content_digest", "content_bytes", "artifact_count")

#: Fields that describe the pack rather than the system it is about - which named
#: graph it was built from, which vocabulary a consumer compiles against, and how the
#: content is encoded. No triple carries them, so they are held against the constants
#: this reader itself carries: a manifest declaring another graph, another vocabulary
#: version or another encoding is describing something this code cannot check and
#: must not pretend to have checked.
CONSTANT_FIELDS = ("graph", "vocabulary_version", "content_media_type")

#: Every field a manifest carries. ``build`` writes exactly these and ``verify``
#: refuses a manifest whose fields are not exactly these, so a field added to one
#: without a rule in the other is a failure rather than a field nothing checks.
MANIFEST_FIELDS = frozenset(
    {VERSION_FIELD, *CONSTANT_FIELDS, *DERIVED_FIELDS, *(field for field, _, _ in CONTENT_FIELDS)}
)

#: The fields a manifest states as a number. Every other field of ``MANIFEST_FIELDS``
#: is text, so the shape of each one is decided by this set rather than by a second
#: list that could fall behind the first.
COUNTED_FIELDS = frozenset({VERSION_FIELD, "content_bytes", "artifact_count"})


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
        VERSION_FIELD: PACK_VERSION,
        **_constants(),
        "observation": str(observation),
        "content_digest": digest_of(body),
        "content_bytes": len(body),
        "artifact_count": len(artifacts),
    }
    # Written from the same enumeration ``verify`` reads back, so a field cannot be
    # added to the manifest without a rule that holds it.
    nodes = {"observation": observation, "source": source}
    for field, node, predicate in CONTENT_FIELDS:
        manifest[field] = _claimed(observed, nodes[node], predicate, field)
    return Pack(content=body, manifest=render(manifest))


def _claimed(subgraph: Graph, subject: URIRef, predicate: URIRef, field: str) -> str:
    """One manifest field, read off the node that carries it, spelled as it is written."""
    what = f"tech:{predicate.removeprefix(str(TECH))}"
    if field in INSTANT_FIELDS:
        return _instant(subgraph, subject, predicate, what)
    return str(_one(subgraph, subject, predicate, what))


def _shaped(field: str, value):
    """One manifest field, refused unless it is the shape its own rule reads.

    A manifest is JSON somebody else wrote, so every field can arrive as any JSON
    value. Each rule below this then does something a shape assumption is built into -
    minting an RDF term, comparing an instant, counting bytes - and handing it a value
    of another shape raises out of a library rather than refusing here. So the shape is
    held first, for every field, and a hostile manifest gets the same named refusal as
    a dishonest one.
    """
    counted = field in COUNTED_FIELDS
    # bool is an int in Python, and `true` is neither a count nor a layout version.
    held = (
        isinstance(value, int) and not isinstance(value, bool)
        if counted
        else isinstance(value, str)
    )
    if not held:
        raise PackError(
            f"the manifest says {field} is {value!r}, and this reader reads "
            f"{'a whole number' if counted else 'text'} there. A manifest is read before the "
            f"content and is written by whoever sent the pack, so every field is held to the "
            f"shape its rule reads before that rule runs."
        )
    return value


def render(manifest: Mapping) -> bytes:
    return (json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()


def _constants() -> dict[str, str]:
    """The fields no triple states, because they are about the pack and not the system.

    Which named graph the content was drawn from, which vocabulary a consumer compiles
    against, and how the content is encoded are facts about this producer, not readings
    of GitHub. Nothing in the content could restate them, so the only honest check is
    against what this code itself is built for - which is a real check, and is why they
    are listed here rather than excused in a comment.
    """
    return {
        "graph": str(layer.OBSERVED_GRAPH),
        "vocabulary_version": _vocabulary_version(),
        "content_media_type": CONTENT_MEDIA_TYPE,
    }


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

    Every field the manifest carries is held, and each is held one of three ways: read
    back off the node in the content that states it (``CONTENT_FIELDS``), recounted or
    recomputed from the content (``DERIVED_FIELDS``), or held against the constant this
    reader itself is built for (``CONSTANT_FIELDS`` and ``VERSION_FIELD``). A manifest whose
    fields are not exactly that set is refused rather than partly checked, because a
    field nothing holds is a field a consumer reads and believes on the strength of a
    verification that never looked at it.

    ``as_of`` is the consumer's own instant, supplied here rather than read from the
    clock, because a pack verified against "now" answers a different question every
    time it is run and cannot be tested at all.

    Both halves of a pack are input a stranger wrote, so every way this refuses is a
    ``PackError`` and there are no special cases that are not. A manifest field of the
    wrong shape is held before any rule reads it, content that is not a graph is named
    rather than raised out of rdflib, and a malformed ``as_of`` is refused the same way
    a malformed field is. A consumer catching the documented type catches all of it.
    """
    for name, value in (("content", content), ("manifest", manifest)):
        if not isinstance(value, bytes):
            raise PackError(f"{name} is {type(value).__name__}, and a pack half is the bytes")

    # Decoded here rather than left to ``json.loads``, which takes bytes and decides the
    # encoding for itself from a byte order mark - so a manifest beginning with two bytes
    # somebody chose would be read as UTF-16 and mean something else entirely, and one
    # that decodes as nothing at all would raise ``UnicodeDecodeError`` out of the json
    # module, which is not the refusal a consumer was told to catch. A manifest is JSON,
    # JSON here is UTF-8, and bytes that are not that are not a manifest.
    try:
        text = manifest.decode("utf-8")
    except UnicodeDecodeError as error:
        raise PackError(
            f"the manifest is not UTF-8: {error}. Both halves of a pack are UTF-8, which is "
            f"what the manifest's own content_media_type says of the other one."
        ) from error

    # The parse is guarded whole, by every family it can fail with, rather than failure
    # by failure. `json` raises a JSONDecodeError for input it can reject, and it also
    # raises a bare ValueError for an integer literal past CPython's digit limit and a
    # RecursionError for a document nested past the parser's own bound - neither of
    # which is malformed JSON, and the list is the interpreter's to extend rather than
    # this reader's to keep up with. Anything a parser will not return a value for is a
    # manifest that cannot be read, which is one refusal and not three. This mirrors how
    # the content is guarded below; only the parse is inside the try, so a fault in this
    # module's own code still surfaces.
    try:
        stated = json.loads(text)
    except (ValueError, RecursionError) as error:
        raise PackError(
            f"the manifest is not JSON this reader can parse: {error}. A manifest is a flat "
            f"object of named fields - so one that is malformed, nested past a parser's own "
            f"bound, or carrying a number too long to convert is not one."
        ) from error
    if not isinstance(stated, dict):
        raise PackError("the manifest is not an object")

    if VERSION_FIELD not in stated:
        raise PackError(
            f"the manifest declares no {VERSION_FIELD}, so nothing says which layout it is "
            f"written in. A pack whose layout is unstated is refused rather than read as "
            f"though it were this one."
        )
    version = _shaped(VERSION_FIELD, stated[VERSION_FIELD])
    if version != PACK_VERSION:
        raise PackError(
            f"the manifest declares pack_version {version!r} and this reader understands "
            f"{PACK_VERSION}. A pack written in another layout is refused rather than "
            f"reinterpreted."
        )

    fields = set(stated)
    if fields != MANIFEST_FIELDS:
        raise PackError(
            f"the manifest carries {sorted(fields - MANIFEST_FIELDS)} that this reader has no "
            f"rule for and lacks {sorted(MANIFEST_FIELDS - fields)}. Every field is checked or "
            f"the manifest is refused: a field nothing holds is one a consumer reads and "
            f"believes on the strength of a verification that never looked at it."
        )
    # Every remaining field held to its shape before any rule reads one, so a rule
    # never receives a value it was not written for. Sorted, so a manifest hostile in
    # more than one field is refused by the same field every time.
    for field in sorted(MANIFEST_FIELDS - {VERSION_FIELD}):
        _shaped(field, stated[field])

    for field, expected in _constants().items():
        if stated[field] != expected:
            raise PackError(
                f"the manifest says {field} is {stated[field]!r} and this reader is built for "
                f"{expected!r}. Nothing in the content states it, so the constant this reader "
                f"carries is the only thing that can hold it, and a pack that disagrees is "
                f"about a layer, a vocabulary or an encoding this code does not speak."
            )

    digest = digest_of(content)
    if stated["content_digest"] != digest:
        raise PackError(
            f"the content hashes to {digest} and the manifest claims "
            f"{stated['content_digest']!r}. The two halves of this pack do not belong to "
            f"each other: one of them was changed after the other was written."
        )
    if stated["content_bytes"] != len(content):
        raise PackError(
            f"the content is {len(content)} bytes and the manifest claims "
            f"{stated['content_bytes']!r}."
        )

    # The digests agree, so these are the bytes that were sent - and they still may not
    # be a graph. rdflib answers that with its own parser exception, which a consumer
    # written against the documented refusal does not catch, so it is translated here.
    # Only the parse is guarded: a fault in this module's own code still surfaces.
    try:
        graph = Graph().parse(data=content, format="nt")
    except (ParserError, UnicodeDecodeError) as error:
        raise PackError(
            f"the content is not N-Triples this reader can parse: {error}. The manifest "
            f"agrees with these bytes, so nothing was tampered with in transit - what was "
            f"sent is not a graph, and a manifest cannot be held against content that "
            f"cannot be read."
        ) from error
    observation = URIRef(stated["observation"])
    if (observation, RDF.type, TECH.Observation) not in graph:
        raise PackError(
            f"the manifest names {observation} as its observation and the content does not "
            f"contain it. A manifest describing content it did not come from cannot be "
            f"checked against anything."
        )
    # Every field a consumer reads off the manifest without parsing the graph, held
    # against what the graph says. A manifest that disagrees with its own content is
    # worse than no manifest: it is read first and believed. The source node is
    # reached through the content rather than through the manifest, so a manifest
    # cannot nominate the node its own claims are checked against.
    source = _one(graph, observation, TECH.observedFrom, "tech:observedFrom")
    nodes = {"observation": observation, "source": source}
    for field, node, predicate in CONTENT_FIELDS:
        held = _claimed(graph, nodes[node], predicate, field)
        if stated[field] != held:
            raise PackError(
                f"the manifest says {field} is {stated[field]!r} and the content says "
                f"{held!r}. The manifest is what a consumer reads without parsing the graph, "
                f"so the two disagreeing makes the manifest worse than absent."
            )

    artifacts = set(graph.subjects(TECH.observedIn, observation))
    if stated["artifact_count"] != len(artifacts):
        raise PackError(
            f"the manifest says artifact_count is {stated['artifact_count']!r} and the content "
            f"holds {len(artifacts)}. A count is how a consumer knows the reading was whole, "
            f"so one that does not match what is there is either a truncated pack or a padded "
            f"number."
        )

    if expect_source is not None and stated["source"] != expect_source:
        raise PackError(
            f"this pack is from {stated['source']}, and {expect_source} was expected. An "
            f"identifier means nothing outside the source that issued it, so acting on a pack "
            f"from another source is acting on a different thing that happens to share a "
            f"number."
        )
    if expect_target is not None and stated["target"] != expect_target:
        raise PackError(
            f"this pack is about {stated['target']!r}, and {expect_target!r} was expected."
        )

    if not isinstance(as_of, str) or not INSTANT_PATTERN.fullmatch(as_of):
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
    # The refusal a reader acts on, and not a stack of this repository's frames on
    # top of it. Every PackError raised under here already names what is wrong and
    # what to do next; a traceback over that sentence tells somebody following the
    # README that they hit a bug rather than a state they can fix.
    try:
        main()
    except PackError as error:
        raise SystemExit(f"error: {error}") from None
