"""The span store: a local SQLite file, append-only, with one narrow way out.

Spans do not belong in the RDF files. They are time-shaped, they are the volatile half
of a trace, and they are the half a retention policy has to be able to remove; putting
them in git would make every one of those a merge conflict and make "delete the detail
after ninety days" impossible without rewriting history. So the detail lives here, and
only a bounded PROV summary is ever projected into a graph (see ``project``).

Three properties are structural rather than promised:

**Nothing is written until everything can be.** A run is validated whole, its pack is
verified against the real verifier, and only then does one transaction write the run,
its spans, its references and its rollups. A write that fails at the ninth span leaves
no trace of the first eight.

**Nothing is changed through the supported API, and ordinary SQL is refused too.**
There is no update and no selective delete on this class, and every table also refuses
UPDATE and DELETE by trigger, so a caller reaching past this module with an
``UPDATE run`` or a ``DELETE FROM span`` is refused rather than trusted. The one
opening is span detail under a retention pass: ``expire_spans`` declares the horizon it
selected, and the trigger holds the delete loop to it, refusing a span whose run ended
at or after the horizon that was declared.

Read that guard for what it is. It is defence in depth against this module's own
delete loop reaching further than the horizon it computed, and against direct edits by
anything that is not driving a pass. It is **not** a check on the ninety-day policy -
the arithmetic lives in ``retention_horizon`` and the trigger never sees ``as_of`` - and
it is not security against whoever owns the file. Somebody at a SQLite shell can insert
a horizon of their choosing into ``retention_pass``, or drop the triggers, or delete the
file; a local database cannot defend itself from its owner, and nothing here pretends
otherwise. What is guaranteed is stated in ``expire_spans`` and in
docs/l3-execution-trace.md, with the boundary drawn in the same place.

**Nothing here can hold a payload.** Every table is STRICT, so a column typed TEXT
refuses a blob rather than storing one; every text column carries a CHECK that bounds
its length and its alphabet or names the closed set it comes from; and there is no
column for a prompt, a completion, a tool argument, a tool result, a body, an
environment or arbitrary attributes. The representation is the policy - see
``semantic_layer.trace.model`` for the other half of it, and
docs/l3-execution-trace.md for why it is drawn here rather than in a review checklist.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from rdflib import Graph

from semantic_layer import ids
from semantic_layer import pack as packs
from semantic_layer.github import INSTANT_FORMAT, digest_of
from semantic_layer.trace import model, project
from semantic_layer.trace.model import (
    FINDING_SEVERITIES,
    METRIC_UNITS,
    OUTCOME_STATUSES,
    SPAN_KINDS,
    SPAN_STATUSES,
    Run,
    TraceError,
    Validated,
)

#: How long full span detail is kept. The rollups a run is judged by afterwards - its
#: outcome, its metrics, its findings and the pack it used - are kept indefinitely.
RETENTION_DAYS = 90

#: The layout this module reads and writes. A store written in another one is refused
#: rather than reinterpreted: L3 is never migrated in place, because old spans are
#: historical fact and a new span schema is a new table and a dual-write window.
SCHEMA_VERSION = 1

#: How long an instant is, spelled the one way this repository spells one. Every
#: comparison below is textual, which is only sound because the spelling is fixed
#: width and always UTC.
INSTANT_LENGTH = 20

#: How long a 'sha256:' digest is.
DIGEST_LENGTH = 71

#: The prefix every identifier this layer records starts with, and the bound on how
#: long one may be. Both are bounds on what a reference column can hold: an IRI is the
#: only kind of text that reaches one, and this is what stops it being any other. The
#: length is ``model``'s, so the column and the validation that runs before it cannot
#: drift apart and leave a value the writer accepts and the schema refuses.
IRI_MAX_LENGTH = model.IRI_MAX_LENGTH
IRI_PREFIX = ids.BASE


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


_HEX = "NOT GLOB '*[^0-9a-f]*'"
_SLUG = "NOT GLOB '*[^a-z0-9-]*'"
_IRI = f"length({{column}}) <= {IRI_MAX_LENGTH} AND {{column}} GLOB '{IRI_PREFIX}*'"

SCHEMA = f"""
CREATE TABLE run (
    trace_id             TEXT NOT NULL PRIMARY KEY
        CHECK (length(trace_id) = 32 AND trace_id {_HEX}),
    started_at           TEXT NOT NULL CHECK (length(started_at) = {INSTANT_LENGTH}),
    ended_at             TEXT NOT NULL CHECK (length(ended_at) = {INSTANT_LENGTH}),
    outcome_status       TEXT NOT NULL CHECK (outcome_status IN ({_quoted(OUTCOME_STATUSES)})),
    agent                TEXT CHECK (agent IS NULL OR ({_IRI.format(column="agent")})),
    pack_identity        TEXT NOT NULL
        CHECK (length(pack_identity) = 64 AND pack_identity {_HEX}),
    pack_content_digest  TEXT NOT NULL
        CHECK (length(pack_content_digest) = {DIGEST_LENGTH}),
    pack_manifest_digest TEXT NOT NULL
        CHECK (length(pack_manifest_digest) = {DIGEST_LENGTH}),
    pack_observation     TEXT NOT NULL CHECK ({_IRI.format(column="pack_observation")}),
    pack_source          TEXT NOT NULL CHECK ({_IRI.format(column="pack_source")}),
    pack_target          TEXT NOT NULL CHECK (length(pack_target) <= 200)
) STRICT;

CREATE TABLE span (
    trace_id       TEXT NOT NULL REFERENCES run(trace_id),
    span_id        TEXT NOT NULL CHECK (length(span_id) = 16 AND span_id {_HEX}),
    parent_span_id TEXT
        CHECK (parent_span_id IS NULL
               OR (length(parent_span_id) = 16 AND parent_span_id {_HEX})),
    operation      TEXT NOT NULL
        CHECK (length(operation) BETWEEN 1 AND {model.NAME_MAX_LENGTH} AND operation {_SLUG}),
    kind           TEXT NOT NULL CHECK (kind IN ({_quoted(SPAN_KINDS)})),
    status         TEXT NOT NULL CHECK (status IN ({_quoted(SPAN_STATUSES)})),
    started_at     TEXT NOT NULL CHECK (length(started_at) = {INSTANT_LENGTH}),
    ended_at       TEXT NOT NULL CHECK (length(ended_at) = {INSTANT_LENGTH}),
    PRIMARY KEY (trace_id, span_id)
) STRICT;

CREATE TABLE span_reference (
    trace_id TEXT NOT NULL,
    span_id  TEXT NOT NULL,
    iri      TEXT NOT NULL CHECK ({_IRI.format(column="iri")}),
    PRIMARY KEY (trace_id, span_id, iri),
    FOREIGN KEY (trace_id, span_id) REFERENCES span(trace_id, span_id)
) STRICT;

CREATE TABLE metric (
    trace_id TEXT NOT NULL REFERENCES run(trace_id),
    name     TEXT NOT NULL
        CHECK (length(name) BETWEEN 1 AND {model.NAME_MAX_LENGTH} AND name {_SLUG}),
    value    INTEGER NOT NULL,
    unit     TEXT NOT NULL CHECK (unit IN ({_quoted(METRIC_UNITS)})),
    PRIMARY KEY (trace_id, name)
) STRICT;

CREATE TABLE finding (
    trace_id TEXT NOT NULL REFERENCES run(trace_id),
    ordinal  INTEGER NOT NULL CHECK (ordinal >= 1),
    code     TEXT NOT NULL
        CHECK (length(code) BETWEEN 1 AND {model.NAME_MAX_LENGTH} AND code {_SLUG}),
    severity TEXT NOT NULL CHECK (severity IN ({_quoted(FINDING_SEVERITIES)})),
    about    TEXT CHECK (about IS NULL OR ({_IRI.format(column="about")})),
    PRIMARY KEY (trace_id, ordinal)
) STRICT;

CREATE TABLE span_expiry (
    trace_id TEXT NOT NULL PRIMARY KEY REFERENCES run(trace_id),
    horizon  TEXT NOT NULL CHECK (length(horizon) = {INSTANT_LENGTH})
) STRICT;

-- Not evidence, and the only mutable table here: one row exists for the duration of a
-- retention pass and names the horizon that pass declared. The trigger below reads the
-- declared horizon rather than the loop's intent, so the pass cannot delete past what
-- it said it was deleting. It does not re-derive ninety days from anything - it has no
-- clock and never sees `as_of` - so a caller that declares a dishonest horizon gets the
-- horizon it declared. That is the trust boundary, and it is written down rather than
-- papered over: see this module's docstring.
CREATE TABLE retention_pass (
    horizon TEXT NOT NULL CHECK (length(horizon) = {INSTANT_LENGTH})
) STRICT;
"""

#: What the append-only guarantee is, written as triggers rather than as a rule this
#: module follows. Recorded evidence is not edited by this code, by a later version of
#: it, or by an ordinary UPDATE or DELETE from a SQLite shell - which is the reach a
#: trigger has. It is not a defence against whoever owns the file and can drop the
#: trigger; see this module's docstring for where that line is drawn.
_IMMUTABLE = ("run", "metric", "finding", "span_expiry")

_APPEND_ONLY = "".join(
    f"""
CREATE TRIGGER {table}_is_never_updated BEFORE UPDATE ON {table} BEGIN
    SELECT RAISE(ABORT, 'recorded evidence is never updated: {table} is append-only');
END;

CREATE TRIGGER {table}_is_never_deleted BEFORE DELETE ON {table} BEGIN
    SELECT RAISE(ABORT, 'recorded evidence is never deleted: {table} is append-only');
END;
"""
    for table in _IMMUTABLE
) + "".join(
    f"""
CREATE TRIGGER {table}_is_never_updated BEFORE UPDATE ON {table} BEGIN
    SELECT RAISE(ABORT, 'recorded evidence is never updated: {table} is append-only');
END;

CREATE TRIGGER {table}_expires_only_by_retention BEFORE DELETE ON {table}
WHEN NOT EXISTS (
    SELECT 1 FROM retention_pass, run
    WHERE run.trace_id = OLD.trace_id AND run.ended_at < retention_pass.horizon
)
BEGIN
    SELECT RAISE(ABORT, 'span detail is removed only by a retention pass, past its horizon');
END;
"""
    for table in ("span", "span_reference")
)


def retention_horizon(as_of: str) -> str:
    """The instant span detail is kept back to, given the caller's own instant.

    ``as_of`` is supplied rather than read from the clock, and that is the whole reason
    retention is testable: a policy that consults the wall clock answers a different
    question every time it runs, so the boundary it draws can be argued about but never
    demonstrated. A span expires when its run ended strictly before this instant, so a
    run of exactly the retention age is kept and the boundary belongs to the data.

    This is the only place ``RETENTION_DAYS`` is applied. Nothing downstream re-derives
    it: the store records the answer this function gave and enforces deletion against
    that, so an error here is an error everywhere, which is why it is a function of one
    argument that can be called and compared on its own.
    """
    if not isinstance(as_of, str):
        raise TraceError(f"as_of is {type(as_of).__name__}, and this reads a UTC instant there")
    stamped = datetime.strptime(model.instant(as_of, "as_of"), INSTANT_FORMAT).replace(tzinfo=UTC)
    return (stamped - timedelta(days=RETENTION_DAYS)).strftime(INSTANT_FORMAT)


@dataclass(frozen=True)
class PackBinding:
    """Which exact pack a run was handed, by the identity of the bytes it verified."""

    identity: str
    content_digest: str
    manifest_digest: str
    observation: str
    source: str
    target: str


@dataclass(frozen=True)
class Recorded:
    """What one call to ``write`` did: the run it named, and whether it wrote anything.

    ``created`` is the half a caller cannot work out for itself. Recording is idempotent
    by design, so the same call twice returns the same identifier either way, and a
    writer that retried after a timeout has no way to know whether the first attempt
    landed. Asking the store beforehand does not answer it either: between that question
    and the write, another process can record the same run. So the answer is the write's
    own, taken from whether this call was the one that inserted the rows.
    """

    run: str
    trace_id: str
    created: bool
    pack: PackBinding


@dataclass(frozen=True)
class RunRecord:
    """One recorded run as the store holds it now, which is not always as it was written.

    ``run.spans`` is empty once retention has removed the detail, and
    ``span_detail_expired_at`` says so - which is why it is recorded rather than
    inferred from the emptiness, since a run is never written with no spans at all.
    """

    run: Run
    pack: PackBinding
    span_detail_expired_at: str | None


def binding_of(pack: packs.Pack, manifest: Mapping) -> PackBinding:
    """The identity of one verified pack, derived from its bytes and never from a claim.

    Both halves are hashed, and the entity is named by a digest over the pair, so a
    change to either one names a different pack. That matters in the direction nobody
    expects: tampering with either half is already refused by ``pack.verify``, but a
    manifest re-rendered with the same fields in another spelling would verify and is
    not the same bytes, and a run that used it did not use this pack.
    """
    content_digest = digest_of(pack.content)
    manifest_digest = digest_of(pack.manifest)
    identity = hashlib.sha256(f"{content_digest}\n{manifest_digest}".encode()).hexdigest()
    return PackBinding(
        identity=identity,
        content_digest=content_digest,
        manifest_digest=manifest_digest,
        observation=manifest["observation"],
        source=manifest["source"],
        target=manifest["target"],
    )


def _rows(validated: Validated, binding: PackBinding) -> dict[str, list[tuple]]:
    """Everything one run writes, as the rows it writes, in a settled order.

    The same shape is read back by ``_stored``, so "is this replay the same run" is one
    comparison of two of these rather than a field-by-field walk somebody has to keep
    in step with the schema.
    """
    trace_id = validated.trace_id
    return {
        "run": [
            (
                trace_id,
                validated.started_at,
                validated.ended_at,
                validated.outcome,
                validated.agent,
                binding.identity,
                binding.content_digest,
                binding.manifest_digest,
                binding.observation,
                binding.source,
                binding.target,
            )
        ],
        "span": sorted(
            (
                trace_id,
                span.span_id,
                span.parent_span_id,
                span.operation,
                span.kind,
                span.status,
                span.started_at,
                span.ended_at,
            )
            for span in validated.spans
        ),
        "span_reference": sorted(
            (trace_id, span.span_id, iri) for span in validated.spans for iri in span.touched
        ),
        "metric": sorted(
            (trace_id, metric.name, metric.value, metric.unit) for metric in validated.metrics
        ),
        "finding": sorted(
            (trace_id, ordinal, finding.code, finding.severity, finding.about)
            for ordinal, finding in enumerate(validated.findings, start=1)
        ),
    }


_COLUMNS = {
    "run": (
        "trace_id, started_at, ended_at, outcome_status, agent, pack_identity, "
        "pack_content_digest, pack_manifest_digest, pack_observation, pack_source, pack_target"
    ),
    "span": "trace_id, span_id, parent_span_id, operation, kind, status, started_at, ended_at",
    "span_reference": "trace_id, span_id, iri",
    "metric": "trace_id, name, value, unit",
    "finding": "trace_id, ordinal, code, severity, about",
}


class TraceStore:
    """One span store, opened on one file.

    A library and not a service: there is nothing to start, nothing listening, and no
    collector. A caller opens the file, records runs into it, and closes it.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    @classmethod
    def open(cls, path: Path | str) -> TraceStore:
        """Open ``path``, creating the schema if the file is new.

        ``:memory:`` opens a store that lives as long as the object, which is what the
        suite uses: the whole point of a local file is that a test needs no service.
        """
        connection = sqlite3.connect(path, isolation_level=None)
        connection.execute("PRAGMA foreign_keys = ON")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            connection.executescript(SCHEMA + _APPEND_ONLY)
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        elif version != SCHEMA_VERSION:
            connection.close()
            raise TraceError(
                f"{path} was written by schema version {version} and this reads "
                f"{SCHEMA_VERSION}. An L3 store is never migrated in place: recorded spans are "
                f"historical fact and stay exactly as they were written, so a new schema is a "
                f"new store."
            )
        return cls(connection)

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> TraceStore:
        return self

    def __exit__(self, *_exception) -> None:
        self.close()

    ## Writing.

    def record(
        self,
        run: Run,
        *,
        pack: packs.Pack,
        as_of: str,
        expect_source: str | None = None,
        expect_target: str | None = None,
    ) -> str:
        """Record one whole run, and return its identifier.

        The pack is verified here, by the real verifier, against the instant the caller
        supplies - not trusted, not looked up by a path, and not taken on the caller's
        word that it was checked earlier. A pack that is stale, tampered with,
        internally inconsistent, from another source or about another target is refused
        before any row is written, because a run whose evidence names an unverified
        pack proves nothing about what it knew.

        Recording the same run twice is a no-op and returns the same identifier, but
        only if the complete content agrees: same spans, same references, same rollups,
        same pack. A trace id reused for anything else is refused, because two
        different runs under one id is a record that cannot be read at all.

        ``write`` is the same call reporting what it did rather than only what it
        named, for a caller that has to answer for it.
        """
        return self.write(
            run,
            pack=pack,
            as_of=as_of,
            expect_source=expect_source,
            expect_target=expect_target,
        ).run

    def write(
        self,
        run: Run,
        *,
        pack: packs.Pack,
        as_of: str,
        expect_source: str | None = None,
        expect_target: str | None = None,
    ) -> Recorded:
        """Record one whole run, and say what recording it did.

        The same write ``record`` performs, reporting the pack binding it derived and
        whether this call was the one that wrote the rows. A caller that has to answer
        for what it did - a process boundary reporting to another program, rather than a
        library call inside one - needs both, and neither can be recovered afterwards:
        the binding is derived from bytes that are gone once the call returns, and a
        replay is indistinguishable from a first write once it has been written.
        """
        validated = model.validate(run)
        if not isinstance(pack, packs.Pack):
            raise TraceError(
                f"pack is a {type(pack).__name__}, and this verifies a semantic_layer.pack.Pack: "
                f"the two halves a consumer was handed. There is no way to record a run against "
                f"a pack that was checked somewhere else, because that check is the only thing "
                f"tying the evidence to what the run actually knew."
            )
        manifest = packs.verify(
            pack.content,
            pack.manifest,
            as_of=as_of,
            expect_source=expect_source,
            expect_target=expect_target,
        )
        binding = binding_of(pack, manifest)
        return Recorded(
            run=ids.mint_trace("run", validated.trace_id),
            trace_id=validated.trace_id,
            created=self._write_once(validated.trace_id, _rows(validated, binding)),
            pack=binding,
        )

    def _write_once(self, trace_id: str, rows: dict[str, list[tuple]]) -> bool:
        """Write the run if it is not recorded, hold it against what is there if it is.

        The reread after an integrity error is the concurrent case, and it is the only
        way to get the answer right. Two processes recording one run both see nothing
        recorded, both write, and one of them loses the trace id's primary key - having
        written nothing, because the transaction rolls back whole. What that process is
        holding is now a replay of rows another process committed, so it is held against
        them exactly as a replay arriving a second later would be: identical is a no-op,
        and anything else is two runs under one identifier and is refused.
        """
        stored = self._stored(trace_id)
        if stored is None:
            try:
                self._write(rows)
                return True
            except sqlite3.IntegrityError:
                stored = self._stored(trace_id)
                if stored is None:
                    raise
        self._same_or_refuse(trace_id, rows, stored)
        return False

    def _same_or_refuse(self, trace_id: str, rows: dict, stored: dict) -> None:
        if self._expired_at(trace_id) is not None:
            raise TraceError(
                f"run {trace_id} is already recorded and its span detail has expired, so this "
                f"replay cannot be held against what was written. Retention removed the "
                f"detail on purpose; writing it back would undo the removal, and accepting "
                f"the replay unchecked would let a different run inherit a recorded run's id."
            )
        if stored == rows:
            return
        differing = sorted(table for table in rows if rows[table] != stored[table])
        raise TraceError(
            f"run {trace_id} is already recorded and this one differs in {differing}. Recording "
            f"the same run twice is a no-op; recording something else under a recorded trace "
            f"id is two runs written down as one, and evidence nothing can read back apart. "
            f"Mint a new trace id for a new run."
        )

    def _write(self, rows: dict[str, list[tuple]]) -> None:
        """One transaction, or nothing. A run is whole evidence or it is not evidence."""
        connection = self._connection
        try:
            connection.execute("BEGIN IMMEDIATE")
            for table, values in rows.items():
                if not values:
                    continue
                columns = _COLUMNS[table]
                placeholders = ", ".join("?" * len(values[0]))
                connection.executemany(
                    f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", values
                )
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise

    ## Retention.

    def expire_spans(self, *, as_of: str) -> tuple[str, ...]:
        """Remove full span detail older than the retention window, and nothing else.

        This is the layer that owns the policy. The horizon is ``retention_horizon``'s
        answer - ``as_of`` minus ``RETENTION_DAYS`` - and the runs selected are the ones
        that ended strictly before it, so the ninety days are Python's arithmetic over
        the instant the caller supplied and nothing else re-derives or rechecks them.

        SQLite owns something narrower and separate: the pass writes the horizon into
        ``retention_pass``, and the trigger refuses any span delete that reaches past
        that declared horizon - which bounds this loop to what it said it was doing, and
        refuses a delete outside a pass entirely. The trigger cannot check the ninety
        days, because it is never told ``as_of`` and has no clock to compare one against.

        Returns the runs this pass removed detail for, so a caller can say what
        happened rather than infer it. Everything a run is judged by afterwards - its
        outcome, its metrics, its findings, and the pack it used - is untouched and
        kept indefinitely.

        Running this again with the same or a later instant removes nothing further and
        returns nothing: a run whose detail has already gone is not a run to expire
        again. That is what makes retention safe to put on a timer.
        """
        horizon = retention_horizon(as_of)
        expiring = tuple(
            row[0]
            for row in self._connection.execute(
                "SELECT trace_id FROM run "
                "WHERE ended_at < ? AND trace_id NOT IN (SELECT trace_id FROM span_expiry) "
                "ORDER BY trace_id",
                (horizon,),
            )
        )
        if not expiring:
            return ()
        connection = self._connection
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("INSERT INTO retention_pass (horizon) VALUES (?)", (horizon,))
            for trace_id in expiring:
                # References first: they point at the spans, and the store enforces its
                # own foreign keys rather than leaving them to be tidied later.
                connection.execute("DELETE FROM span_reference WHERE trace_id = ?", (trace_id,))
                connection.execute("DELETE FROM span WHERE trace_id = ?", (trace_id,))
                connection.execute(
                    "INSERT INTO span_expiry (trace_id, horizon) VALUES (?, ?)",
                    (trace_id, horizon),
                )
            connection.execute("DELETE FROM retention_pass")
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        return expiring

    ## Reading.

    def trace_ids(self) -> tuple[str, ...]:
        """Every run recorded here, oldest identifier first."""
        return tuple(
            row[0] for row in self._connection.execute("SELECT trace_id FROM run ORDER BY trace_id")
        )

    def read(self, trace_id: str) -> RunRecord:
        """One recorded run, as the store holds it now."""
        stored = self._stored(trace_id)
        if stored is None:
            raise TraceError(f"no run {trace_id!r} is recorded here")
        (
            _,
            started_at,
            ended_at,
            outcome,
            agent,
            identity,
            content_digest,
            manifest_digest,
            observation,
            source,
            target,
        ) = stored["run"][0]
        touched: dict[str, list[str]] = {}
        for _, span_id, iri in stored["span_reference"]:
            touched.setdefault(span_id, []).append(iri)
        spans = tuple(
            model.Span(
                span_id=span_id,
                operation=operation,
                kind=kind,
                status=status,
                started_at=span_started,
                ended_at=span_ended,
                parent_span_id=parent,
                touched=tuple(touched.get(span_id, ())),
            )
            for _, span_id, parent, operation, kind, status, span_started, span_ended in stored[
                "span"
            ]
        )
        return RunRecord(
            run=Run(
                trace_id=trace_id,
                started_at=started_at,
                ended_at=ended_at,
                outcome=outcome,
                spans=spans,
                metrics=tuple(
                    model.Metric(name=name, value=value, unit=unit)
                    for _, name, value, unit in stored["metric"]
                ),
                findings=tuple(
                    model.Finding(code=code, severity=severity, about=about)
                    for _, _ordinal, code, severity, about in stored["finding"]
                ),
                agent=agent,
            ),
            pack=PackBinding(
                identity=identity,
                content_digest=content_digest,
                manifest_digest=manifest_digest,
                observation=observation,
                source=source,
                target=target,
            ),
            span_detail_expired_at=self._expired_at(trace_id),
        )

    def summary(self, trace_id: str) -> Graph:
        """The PROV-O summary of one recorded run: see ``semantic_layer.trace.project``."""
        return project.summary(self.read(trace_id))

    def _expired_at(self, trace_id: str) -> str | None:
        row = self._connection.execute(
            "SELECT horizon FROM span_expiry WHERE trace_id = ?", (trace_id,)
        ).fetchone()
        return None if row is None else row[0]

    def _stored(self, trace_id: str) -> dict[str, list[tuple]] | None:
        run = self._connection.execute(
            f"SELECT {_COLUMNS['run']} FROM run WHERE trace_id = ?", (trace_id,)
        ).fetchall()
        if not run:
            return None
        stored = {"run": [tuple(run[0])]}
        for table in ("span", "span_reference", "metric", "finding"):
            stored[table] = sorted(
                tuple(row)
                for row in self._connection.execute(
                    f"SELECT {_COLUMNS[table]} FROM {table} WHERE trace_id = ?", (trace_id,)
                )
            )
        return stored
