"""The GitHub source contract, and the one-way reconciler that turns it into L2 truth.

This is the first source, not a GitHub ingestion framework. It reads one captured
response about one repository and produces the same bytes every time, so promoting a
refreshed observation is a diff a human can read rather than a regeneration they have
to trust.

Three rules shape everything below.

**The payload is closed.** Every field the reconciler accepts is named here, and a
field that is not named is an error rather than something ignored. GitHub adds fields
constantly; a reconciler that ignores what it does not recognize cannot tell a new
field from a renamed one, and cannot tell either from a response that is not the
response it thinks it is. Closing the payload is also what keeps a credential out of
the graph: there is no field a token could arrive in and be written from.

**Absent is not empty.** A collection is only an authoritative answer if the capture
says it read all of it, so a paginated collection carries whether pagination completed
and a collection that does not say so is refused. An optional field is absent when the
source said null, and is refused when the source did not mention it: the first is an
answer and the second is a different response.

**Identity comes from the source's immutable id, never from a name.** A repository
renamed this morning is the same repository, so its identifier is minted from the
numeric id GitHub issued it and its path is an attribute that a refresh rewrites. The
one artifact GitHub issues no id for is a branch, and git issues none either - a branch
is its name within its repository - so its identifier carries both and a rename is
honestly a different branch. All of it goes through ``ids.mint_observed`` and none of
it is spelled out here.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, RDFS, XSD

from semantic_layer import ids
from semantic_layer.serialize import turtle

TECH = "https://semantic-layer.19h09.co/vocab/tech#"

#: The snapshot layout this reconciler reads. Bumped when a change would make an
#: older snapshot mean something different, so an old file is refused rather than
#: reinterpreted.
SNAPSHOT_VERSION = 1

PROVIDER = "github"

#: The one repository this source is allowed to be about. Acquisition is target-locked
#: to it and reconciliation refuses a snapshot about anything else, so widening the
#: scope is an edit to this line and a decision somebody makes on purpose.
TARGET = "vvonkledge/siana"

#: A GitHub commit as the REST API reports it.
SHA_PATTERN = re.compile(r"[0-9a-f]{40}")

#: The instants this contract accepts, which is the one spelling GitHub emits: UTC,
#: to the second, with a literal Z. Anything else is refused rather than normalized,
#: because normalizing is where two captures of the same moment stop matching.
INSTANT_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
INSTANT_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

#: Deliberately narrow. Each of these earns its place by answering a question about
#: the repository; everything else GitHub returns - topics, counts, permissions,
#: avatars, the forty URL templates - is left out. Topics and repository names in
#: particular are left out on purpose: they are the fields somebody would be tempted
#: to read a capability or an owner out of, and that inference is L1's to make.
REPOSITORY_FIELDS = {
    "id": "the immutable numeric id GitHub issued this repository",
    "name": "the repository's short name today",
    "full_name": "where the repository is reachable today, as owner/name",
    "default_branch": "the branch GitHub sends a reader who names none",
    "visibility": "who GitHub says may read it",
    "language": "the language GitHub reports most of it is written in, or null",
    "html_url": "where a person can go and look at it",
    "pushed_at": "when GitHub last saw a push",
    "archived": "whether GitHub has marked it read-only",
    "owner": "the account it sits under",
}

OWNER_FIELDS = {
    "id": "the immutable numeric id GitHub issued this account",
    "login": "the account's handle today",
    "html_url": "where a person can go and look at it",
}

BRANCH_FIELDS = {
    "name": "the branch's name, which is half of its identity",
    "commit": "what the branch pointed at when it was read",
    "protected": "whether GitHub enforces a rule before it may be written",
}

BRANCH_COMMIT_FIELDS = {"sha": "the commit the branch pointed at"}

COLLECTION_FIELDS = {
    "complete": "whether the capture followed pagination to the end",
    "pages": "how many pages it took",
    "items": "the collection itself",
}

SNAPSHOT_FIELDS = {
    "snapshot_version": "which layout this file is written in",
    "provider": "which kind of system was read",
    "instance": "which installation of it, as a slug",
    "api_root": "the endpoint that was read",
    "target": "what was asked for, in the source's own terms",
    "trust_basis": "why a consumer should believe this, and what it does not cover",
    "observed_at": "the instant the source was read",
    "freshness_seconds": "how long after that this observation is worth believing",
    "repository": "the repository response, projected onto REPOSITORY_FIELDS",
    "branches": "the branches response, projected onto BRANCH_FIELDS",
}


class ReconcileError(ValueError):
    """A snapshot could not be turned into L2 truth, and says which field is why."""


def _show(value) -> str:
    """A value, quoted for a message and short enough to read.

    Source text reaches these messages, so it is truncated rather than pasted: a
    hostile repository description is not going to be what a reader has to scroll past
    to find the field name they need.
    """
    text = repr(value)
    return text if len(text) <= 80 else text[:77] + "..."


def _object(payload, fields: Mapping[str, str], where: str) -> Mapping:
    """``payload`` as an object carrying exactly ``fields`` and nothing else."""
    if not isinstance(payload, dict):
        raise ReconcileError(
            f"{where} is {_show(payload)}, and this contract reads an object there"
        )
    missing = sorted(set(fields) - set(payload))
    unknown = sorted(set(payload) - set(fields))
    if missing:
        raise ReconcileError(
            f"{where} is missing {missing}. This contract requires every supported field to "
            f"be present: a field the source stopped sending is schema drift, not an empty "
            f"answer, and guessing which it is here is how a partial response becomes an "
            f"authoritative one."
        )
    if unknown:
        raise ReconcileError(
            f"{where} carries {unknown}, which this contract does not read. The supported "
            f"payload is closed on purpose - a field nobody chose is a field nobody has "
            f"decided the meaning of, and it is also the only way a credential could reach "
            f"the graph. Add it to the contract deliberately, or capture without it."
        )
    return payload


def _string(payload: Mapping, key: str, where: str) -> str:
    value = payload[key]
    if not isinstance(value, str) or not value:
        raise ReconcileError(
            f"{where}.{key} is {_show(value)}, and this contract reads a non-empty string there"
        )
    return value


def _boolean(payload: Mapping, key: str, where: str) -> bool:
    value = payload[key]
    if not isinstance(value, bool):
        raise ReconcileError(
            f"{where}.{key} is {_show(value)}, and this contract reads true or false there"
        )
    return value


def _positive_integer(payload: Mapping, key: str, where: str) -> int:
    value = payload[key]
    # bool is an int in Python, and `true` is not an id.
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ReconcileError(
            f"{where}.{key} is {_show(value)}, and this contract reads a positive integer "
            f"there. An artifact whose immutable id is missing, null or nonsensical gets no "
            f"identifier: minting one from its name instead is how a rename becomes a second "
            f"entity."
        )
    return value


def _instant(payload: Mapping, key: str, where: str) -> str:
    value = _string(payload, key, where)
    if not INSTANT_PATTERN.fullmatch(value):
        raise ReconcileError(
            f"{where}.{key} is {_show(value)}, and this contract reads a UTC instant spelled "
            f"YYYY-MM-DDTHH:MM:SSZ there"
        )
    return value


def _https(payload: Mapping, key: str, where: str) -> str:
    value = _string(payload, key, where)
    if not value.startswith("https://"):
        raise ReconcileError(
            f"{where}.{key} is {_show(value)}, and this contract reads an https URL there. A "
            f"URL is text the source chose, so it is checked rather than believed."
        )
    return value


def _optional_string(payload: Mapping, key: str, where: str) -> str | None:
    value = payload[key]
    if value is None:
        return None
    return _string(payload, key, where)


def _collection(payload: Mapping, key: str, where: str) -> list:
    """A paginated collection the capture says it read to the end.

    A collection that does not say so is refused, because the alternative is treating
    "the second page never arrived" as "there is no second page" - an answer that is
    both wrong and authoritative-looking.
    """
    block = _object(payload[key], COLLECTION_FIELDS, f"{where}.{key}")
    if _boolean(block, "complete", f"{where}.{key}") is not True:
        raise ReconcileError(
            f"{where}.{key}.complete is false: the capture did not follow pagination to the "
            f"end, so this collection is a prefix of the answer and not the answer. Recapture "
            f"rather than reconcile a partial collection into an authoritative one."
        )
    if _positive_integer(block, "pages", f"{where}.{key}") < 1:
        raise ReconcileError(f"{where}.{key}.pages is {_show(block['pages'])}")
    items = block["items"]
    if not isinstance(items, list):
        raise ReconcileError(
            f"{where}.{key}.items is {_show(items)}, and this contract reads a list there"
        )
    return items


def _fresh_until(observed_at: str, seconds: int) -> str:
    """The instant this observation stops being worth believing, materialized.

    Computed once, here, and written down. Nothing downstream adds a duration to a
    timestamp: SPARQL engines disagree about whether they can, and the ones that
    cannot leave the result unbound, which makes a freshness filter pass everything
    in silence (docs/evolution.md).
    """
    observed = datetime.strptime(observed_at, INSTANT_FORMAT).replace(tzinfo=UTC)
    return (observed + timedelta(seconds=seconds)).strftime(INSTANT_FORMAT)


def _instant_literal(value: str) -> Literal:
    """An xsd:dateTime keeping the exact spelling the source used.

    rdflib normalizes a typed literal on construction, which rewrites GitHub's trailing
    Z as +00:00. The two mean the same instant and compare the same, but the committed
    graph is read beside the committed capture, and a reviewer should not have to know
    which of the two rewrote the other. Comparisons are by value either way.
    """
    return Literal(value, datatype=XSD.dateTime, normalize=False)


def digest_of(payload: bytes) -> str:
    """The digest a snapshot is named and checked by."""
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def reconcile(snapshot: Mapping, *, digest: str, fixture: bool = False) -> str:
    """The Turtle for one observation: the same bytes for the same snapshot, always.

    ``digest`` is the SHA-256 of the snapshot bytes. It names the observation and is
    written into the graph, so a reader can hold the committed graph against the
    committed capture and tell whether one of them moved.
    """
    graph = Graph()
    builder = _Reconciliation(snapshot, digest=digest, fixture=fixture, graph=graph)
    builder.run()
    return turtle(
        graph,
        header=(
            "Accepted L2 truth: what one source was observed to hold at one instant.",
            "",
            "GENERATED. Do not edit. This file is `just reconcile` run over the captured",
            "snapshot committed beside it, and the suite fails if the two disagree. To",
            "change what is here, capture a new observation and promote it; see",
            "docs/l2-technical-layer.md.",
            "",
            f"source   {snapshot['provider']} at {snapshot['api_root']}",
            f"target   {snapshot['target']}",
            f"observed {snapshot['observed_at']}",
            f"snapshot {digest}",
        ),
    )


class _Reconciliation:
    """One pass over one snapshot. Holds the scope every identifier is minted under."""

    def __init__(self, snapshot: Mapping, *, digest: str, fixture: bool, graph: Graph):
        self.snapshot = _object(snapshot, SNAPSHOT_FIELDS, "snapshot")
        self.digest = digest
        self.fixture = fixture
        self.graph = graph

    def run(self) -> None:
        self._check_version()
        self.provider = _string(self.snapshot, "provider", "snapshot")
        self.instance = _string(self.snapshot, "instance", "snapshot")
        if self.provider != PROVIDER:
            raise ReconcileError(
                f"snapshot.provider is {_show(self.provider)}. This reconciler reads "
                f"{PROVIDER!r} and nothing else: another provider names its artifacts "
                f"differently and needs its own contract, not a wider reading of this one."
            )
        target = _string(self.snapshot, "target", "snapshot")
        if target != TARGET:
            raise ReconcileError(
                f"snapshot.target is {_show(target)}, and this source is locked to {TARGET!r}. "
                f"Observing a second repository is a decision, and it is made by adding a "
                f"source rather than by widening this one."
            )

        source = self._source()
        observation = self._observation(source)
        account = self._account(observation)
        repository = self._repository(observation, account)
        self._branches(observation, repository)

    def _check_version(self) -> None:
        version = self.snapshot["snapshot_version"]
        if version != SNAPSHOT_VERSION:
            raise ReconcileError(
                f"snapshot.snapshot_version is {_show(version)} and this reconciler reads "
                f"{SNAPSHOT_VERSION}. A snapshot written in another layout is refused rather "
                f"than reinterpreted, because the fields that moved are exactly the ones a "
                f"lenient reader would get wrong."
            )

    def _mint(self, kind: str, *local_id: str) -> URIRef:
        try:
            return URIRef(
                ids.mint_observed(
                    self.provider, self.instance, kind, *local_id, fixture=self.fixture
                )
            )
        except ids.IdentifierError as error:
            raise ReconcileError(f"no identifier could be minted for a {kind}: {error}") from error

    def _add(self, subject: URIRef, predicate: str, obj) -> None:
        self.graph.add((subject, URIRef(f"{TECH}{predicate}"), obj))

    def _source(self) -> URIRef:
        try:
            iri = URIRef(ids.mint_source(self.provider, self.instance, fixture=self.fixture))
        except ids.IdentifierError as error:
            raise ReconcileError(
                f"no identifier could be minted for the source: {error}"
            ) from error
        api_root = _https(self.snapshot, "api_root", "snapshot")
        self.graph.add((iri, RDF.type, URIRef(f"{TECH}Source")))
        self.graph.add((iri, RDFS.label, Literal(f"{self.provider} at {api_root}")))
        self._add(iri, "provider", Literal(self.provider))
        self._add(iri, "apiRoot", Literal(api_root, datatype=XSD.anyURI))
        self._add(iri, "trustBasis", Literal(_string(self.snapshot, "trust_basis", "snapshot")))
        return iri

    def _observation(self, source: URIRef) -> URIRef:
        observed_at = _instant(self.snapshot, "observed_at", "snapshot")
        seconds = _positive_integer(self.snapshot, "freshness_seconds", "snapshot")
        if not self.digest.startswith("sha256:"):
            raise ReconcileError(
                f"the snapshot digest {_show(self.digest)} is not a sha256: digest"
            )
        iri = self._mint("observation", self.digest.removeprefix("sha256:"))
        self.graph.add((iri, RDF.type, URIRef(f"{TECH}Observation")))
        self.graph.add(
            (iri, RDFS.label, Literal(f"{self.snapshot['target']} observed {observed_at}"))
        )
        self._add(iri, "observedFrom", source)
        self._add(iri, "observedAt", _instant_literal(observed_at))
        self._add(iri, "freshUntil", _instant_literal(_fresh_until(observed_at, seconds)))
        self._add(iri, "snapshotDigest", Literal(self.digest))
        self._add(iri, "observationTarget", Literal(self.snapshot["target"]))
        return iri

    def _account(self, observation: URIRef) -> URIRef:
        repository = _object(self.snapshot["repository"], REPOSITORY_FIELDS, "snapshot.repository")
        owner = _object(repository["owner"], OWNER_FIELDS, "snapshot.repository.owner")
        account_id = _positive_integer(owner, "id", "snapshot.repository.owner")
        login = _string(owner, "login", "snapshot.repository.owner")
        iri = self._mint("account", str(account_id))
        self.graph.add((iri, RDF.type, URIRef(f"{TECH}Account")))
        self.graph.add((iri, RDFS.label, Literal(login)))
        self._add(iri, "observedIn", observation)
        self._add(iri, "sourceLocalId", Literal(str(account_id)))
        self._add(iri, "accountLogin", Literal(login))
        self._add(
            iri,
            "webUrl",
            Literal(_https(owner, "html_url", "snapshot.repository.owner"), datatype=XSD.anyURI),
        )
        return iri

    def _repository(self, observation: URIRef, account: URIRef) -> URIRef:
        payload = self.snapshot["repository"]
        where = "snapshot.repository"
        self.repository_id = _positive_integer(payload, "id", where)
        self.default_branch = _string(payload, "default_branch", where)
        iri = self._mint("repository", str(self.repository_id))
        self.graph.add((iri, RDF.type, URIRef(f"{TECH}Repository")))
        self.graph.add((iri, RDFS.label, Literal(_string(payload, "name", where))))
        self._add(iri, "observedIn", observation)
        self._add(iri, "sourceLocalId", Literal(str(self.repository_id)))
        self._add(iri, "ownedByAccount", account)
        self._add(iri, "repositoryPath", Literal(_string(payload, "full_name", where)))
        self._add(iri, "visibility", Literal(_string(payload, "visibility", where)))
        self._add(iri, "archived", Literal(_boolean(payload, "archived", where)))
        self._add(iri, "pushedAt", _instant_literal(_instant(payload, "pushed_at", where)))
        self._add(iri, "webUrl", Literal(_https(payload, "html_url", where), datatype=XSD.anyURI))
        language = _optional_string(payload, "language", where)
        if language is not None:
            self._add(iri, "primaryLanguage", Literal(language))
        return iri

    def _branches(self, observation: URIRef, repository: URIRef) -> None:
        items = _collection(self.snapshot, "branches", "snapshot")
        names = self._branch_names(items)
        if self.default_branch not in names:
            raise ReconcileError(
                f"snapshot.repository.default_branch is {_show(self.default_branch)} and the "
                f"captured branches are {sorted(names)}, which do not include it. Either the "
                f"branch list is incomplete or the two responses were read either side of a "
                f"change; both are a recapture rather than a graph."
            )
        for index, item in enumerate(sorted(items, key=lambda branch: branch["name"])):
            where = f"snapshot.branches.items[{index}]"
            branch = _object(item, BRANCH_FIELDS, where)
            name = _string(branch, "name", where)
            commit = _object(branch["commit"], BRANCH_COMMIT_FIELDS, f"{where}.commit")
            sha = _string(commit, "sha", f"{where}.commit")
            if not SHA_PATTERN.fullmatch(sha):
                raise ReconcileError(
                    f"{where}.commit.sha is {_show(sha)}, and this contract reads a "
                    f"40-character lower-case SHA-1 there"
                )
            iri = self._mint("branch", str(self.repository_id), name)
            self.graph.add((iri, RDF.type, URIRef(f"{TECH}Branch")))
            self.graph.add((iri, RDFS.label, Literal(name)))
            self._add(iri, "observedIn", observation)
            self._add(iri, "sourceLocalId", Literal(name))
            self._add(iri, "branchOf", repository)
            self._add(iri, "branchName", Literal(name))
            self._add(iri, "headCommit", Literal(sha))
            self._add(iri, "protected", Literal(_boolean(branch, "protected", where)))
            if name == self.default_branch:
                self._add(repository, "defaultBranch", iri)

    def _branch_names(self, items: Sequence) -> set[str]:
        names: set[str] = set()
        for index, item in enumerate(items):
            where = f"snapshot.branches.items[{index}]"
            name = _string(_object(item, BRANCH_FIELDS, where), "name", where)
            if name in names:
                raise ReconcileError(
                    f"{where}.name is {_show(name)}, which an earlier branch in this capture "
                    f"already used. Two artifacts minting one identifier is a response that "
                    f"describes two different things as the same thing, and there is no "
                    f"reading of it that is safe to commit."
                )
            names.add(name)
        return names


def snapshot_path(instance: str = "vvonkledge-siana") -> Path:
    from semantic_layer import graph

    return graph.SOURCES_DIR / PROVIDER / instance / "snapshot.json"


def read_snapshot(path: Path) -> tuple[Mapping, str]:
    """A committed snapshot and its digest, with the committed digest checked first.

    The digest is committed beside the snapshot rather than inside it, because a file
    cannot carry its own hash. Checking it here is what makes the sidecar a promise
    rather than a note: a snapshot edited after capture no longer reconciles at all.
    """
    payload = path.read_bytes()
    digest = digest_of(payload)
    sidecar = path.with_name(path.name + ".sha256")
    if not sidecar.exists():
        raise ReconcileError(
            f"{path} has no committed digest at {sidecar.name}, so nothing says these bytes "
            f"are the bytes that were captured."
        )
    committed = sidecar.read_text(encoding="utf-8").strip()
    if committed != digest:
        raise ReconcileError(
            f"{path} hashes to {digest} and {sidecar.name} commits {committed}. The capture "
            f"and its digest disagree, so one of them was edited after the other was written. "
            f"Recapture rather than reconcile bytes nothing vouches for."
        )
    try:
        snapshot = json.loads(payload)
    except json.JSONDecodeError as error:
        raise ReconcileError(f"{path} is not valid JSON: {error}") from error
    return snapshot, digest


def accepted_path(instance: str = "vvonkledge-siana") -> Path:
    from semantic_layer import graph

    return graph.TECHNICAL_DIR / f"{PROVIDER}-{instance}.ttl"


def main() -> None:
    """Reconcile the committed snapshot into the committed graph, atomically.

    Deterministic, so a run that changes nothing writes the same bytes back and shows
    no diff. What a reviewer sees is exactly the difference between two observations.
    """
    from semantic_layer import graph
    from semantic_layer.acquire import write_atomically

    source = snapshot_path()
    target = accepted_path()
    snapshot, digest = read_snapshot(source)
    candidate = reconcile(snapshot, digest=digest)

    # Validated before it is written, not after. A candidate that fails the shapes is
    # not a graph with a problem in it, it is not L2 truth, and the last accepted
    # observation is a better answer than a broken new one.
    report = graph.validate(graph.observed_data_graph(candidate))
    if not report.conforms:
        raise ReconcileError(
            "the reconciled graph does not satisfy the L2 shapes, so nothing was written "
            "and the last accepted observation is untouched:\n  " + "\n  ".join(report.messages)
        )

    write_atomically(target, candidate.encode("utf-8"))
    print(f"reconciled {source} -> {target}")
    print(f"  {digest}")


if __name__ == "__main__":
    main()
