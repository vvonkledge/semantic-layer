"""What a run may be written down as, and what it may never be.

Every record here is a frozen dataclass with a closed set of fields, and that is a
policy decision rather than a style one. The obvious shape for a trace writer is an
attribute bag - a dict of whatever the runtime happened to have - and it is exactly the
shape the captain's data policy forbids, because the day somebody wants the prompt they
put it under a key nobody reviewed and it is in an append-only history for good. So
there is no bag. A field that does not exist here cannot be recorded, an unknown
keyword is a ``TypeError`` from the dataclass before any of this runs, and the fields
that do exist are narrowed to shapes a payload does not fit in:

* the identifiers are hex of a fixed width;
* the instants are UTC, spelled the one way this repository spells them;
* the operation, the metric name and the finding code are slugs, bounded in length,
  from the writer's own vocabulary - not free text, because a name is the one field on
  a span a completion could plausibly arrive in;
* the kinds, statuses, severities and units are closed sets;
* every reference to another layer is an identifier ``semantic_layer.ids`` mints, so
  the edge cannot become somewhere to write a URL, a path or a sentence.

There is no field for a prompt, a completion, a tool argument, a tool result, a request
or response body, an environment, or an opaque blob, and there is no free-form
attribute one could arrive under instead. Adding one later is reversible; removing
sensitive data from an append-only history is not. See docs/l3-execution-trace.md.

Validation is the other half. ``validate`` holds a whole run before anything is
written, so a refusal names what is wrong while the caller still has the run in their
hand, and the store never has to decide what to do with half of one.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, fields
from datetime import UTC, datetime

from semantic_layer import ids
from semantic_layer.github import INSTANT_FORMAT, INSTANT_PATTERN

#: The OpenTelemetry identifiers, carried verbatim. Lower case, so two spellings of one
#: id cannot become two entities.
TRACE_ID_PATTERN = re.compile(r"[0-9a-f]{32}")
SPAN_ID_PATTERN = re.compile(r"[0-9a-f]{16}")

#: What a name may be: the slug rule the rest of this repository uses, bounded. The
#: pattern alone already refuses prose, and the bound refuses the other way of writing
#: prose - a very long hyphenated one.
NAME_PATTERN = ids.SLUG_PATTERN
NAME_MAX_LENGTH = 64

#: The longest a reference to another layer may be. It is the bound the store's IRI
#: columns carry, stated here because this is the layer that has to enforce it: an L2
#: identifier percent-encodes whatever a source named a thing, so a legal branch name
#: of a couple of hundred characters - or a much shorter accented one, where every
#: character costs six once encoded - mints an identifier past the column's CHECK. A
#: rule that lived only in SQL would surface as an integrity error from inside a
#: transaction, which is neither a ``TraceError`` nor a sentence naming what to fix.
IRI_MAX_LENGTH = 300

#: The OpenTelemetry span kinds, and its status set.
SPAN_KINDS = ("internal", "server", "client", "producer", "consumer")
SPAN_STATUSES = ("unset", "ok", "error")

#: How a run ended, how much a finding matters, and what a metric counts. Closed, so
#: counting across a fleet is arithmetic, and so none of them becomes somewhere to
#: write a sentence.
OUTCOME_STATUSES = ("succeeded", "failed", "blocked")
FINDING_SEVERITIES = ("info", "warning", "error")
METRIC_UNITS = ("count", "millisecond", "byte")

#: The widest a measurement may be, which is what the store's INTEGER column holds:
#: SQLite's signed sixty-four bits. It is bounded here for the same reason
#: ``IRI_MAX_LENGTH`` is - Python's integers have no width at all, so a value past this
#: is refused by sqlite3 as an ``OverflowError`` raised from inside the transaction,
#: which is neither a ``TraceError`` nor a sentence naming what to fix. No measurement
#: a run makes comes near it; a number that does is a counter that wrapped or a value
#: that was never a count.
METRIC_VALUE_MIN = -(2**63)
METRIC_VALUE_MAX = 2**63 - 1


class TraceError(ValueError):
    """A run could not be recorded as it stands."""


def _settle(record, names: tuple[str, ...]) -> None:
    """Settle a caller's lists into tuples, so a run equals the run it was read back as.

    A caller writes ``spans=[...]`` and the store reads back tuples, and a frozen
    dataclass compares its fields with ``==``. Without this, a run and the record of
    that same run are unequal for no reason a reader would ever guess, and every
    "is this replay the same run" question would have to be asked field by field.
    """
    for name in names:
        value = getattr(record, name)
        if isinstance(value, list):
            object.__setattr__(record, name, tuple(value))


@dataclass(frozen=True)
class Span:
    """One timed operation, shaped like an OpenTelemetry span and nothing more."""

    span_id: str
    operation: str
    kind: str
    status: str
    started_at: str
    ended_at: str
    parent_span_id: str | None = None
    touched: Sequence[str] = ()

    def __post_init__(self) -> None:
        _settle(self, ("touched",))


@dataclass(frozen=True)
class Metric:
    """One measurement a run rolled up. Whole numbers only: see trc:metricValue."""

    name: str
    value: int
    unit: str


@dataclass(frozen=True)
class Finding:
    """Something a run noticed, as a code and a severity, and never as a description."""

    code: str
    severity: str
    about: str | None = None


@dataclass(frozen=True)
class Run:
    """One execution, whole. A run is recorded once, complete, or not at all."""

    trace_id: str
    started_at: str
    ended_at: str
    outcome: str
    spans: Sequence[Span]
    metrics: Sequence[Metric] = ()
    findings: Sequence[Finding] = ()
    agent: str | None = None

    def __post_init__(self) -> None:
        _settle(self, ("spans", "metrics", "findings"))


def _text(value, what: str) -> str:
    """One field, refused unless it is text before any rule that assumes so runs.

    Every rule below does something a type assumption is built into - matching a
    pattern, comparing an instant, measuring a length - and handing it a value of
    another type raises out of a library rather than refusing here. Bytes in
    particular: they are how a payload would arrive if one arrived at all, and a
    ``bytes`` reaching a SQLite TEXT column is a blob in an append-only history.
    """
    if not isinstance(value, str):
        raise TraceError(
            f"{what} is {type(value).__name__}, and this reads text there. Every field of a "
            f"trace is held to its type before any rule reads it, so a payload cannot arrive "
            f"as one field of the wrong shape."
        )
    return value


def _named(value, what: str) -> str:
    """A slug from the writer's own vocabulary, bounded."""
    text = _text(value, what)
    if not NAME_PATTERN.fullmatch(text) or len(text) > NAME_MAX_LENGTH:
        raise TraceError(
            f"{what} is {text!r}, and this reads a name there: lowercase letters and digits "
            f"joined by single hyphens, at most {NAME_MAX_LENGTH} characters. Names are "
            f"narrowed to a shape a prompt, a completion or a tool result does not fit in, "
            f"because a name is the one field on a span a payload could plausibly arrive in."
        )
    return text


def _one_of(value, allowed: tuple[str, ...], what: str) -> str:
    text = _text(value, what)
    if text not in allowed:
        raise TraceError(
            f"{what} is {text!r}, and this reads one of {list(allowed)} there. The set is "
            f"closed so a fleet can be counted and filtered by it, and so the field cannot "
            f"become somewhere to write a sentence."
        )
    return text


def _hex_id(value, pattern: re.Pattern, width: int, what: str) -> str:
    text = _text(value, what)
    if not pattern.fullmatch(text):
        raise TraceError(
            f"{what} is {text!r}, which is not {width} lower-case hex characters. An "
            f"abbreviated or re-cased identifier compares equal to nothing the tracer "
            f"emitted, so the evidence would join to no trace and no parent."
        )
    return text


def instant(value, what: str) -> str:
    text = _text(value, what)
    if not INSTANT_PATTERN.fullmatch(text):
        raise TraceError(
            f"{what} is {text!r}, which is not a UTC instant spelled YYYY-MM-DDTHH:MM:SSZ. "
            f"One spelling, fixed width, so retention compares two of them as text and gets "
            f"the same answer a calendar would."
        )
    try:
        datetime.strptime(text, INSTANT_FORMAT).replace(tzinfo=UTC)
    except ValueError as error:
        raise TraceError(
            f"{what} is {text!r}, which is spelled like an instant but is not one"
        ) from error
    return text


def _interval(started_at: str, ended_at: str, what: str) -> None:
    if ended_at < started_at:
        raise TraceError(
            f"{what} started at {started_at} and ended at {ended_at}, which is earlier. An "
            f"activity that ended before it began cannot be ordered against anything, and "
            f"every duration rolled up from it is negative."
        )


def _inside(started_at: str, ended_at: str, run: tuple[str, str], what: str) -> None:
    """One span's interval, held inside its run's.

    A span is an operation that happened *during* the run, so the run's interval bounds
    every span it records. Without the rule a twelve-second run in 2026 records a span
    dated 2020 without complaint: evidence that contradicts itself and cannot be put on
    a timeline, which is most of what a trace is read for. The bound is inclusive at
    both ends, because that is the ordinary case rather than an edge one - a run's first
    span begins when the run begins and its last ends when the run ends.
    """
    run_started, run_ended = run
    if started_at < run_started or ended_at > run_ended:
        raise TraceError(
            f"{what} ran from {started_at} to {ended_at}, which is outside the run's own "
            f"{run_started} to {run_ended}. A span records something that happened inside "
            f"the run, so the run's interval bounds it; a span reaching outside belongs to "
            f"another run, or to a clock that disagrees with the one that timed this one. "
            f"The bound is inclusive: a span sharing the run's exact start or end is inside."
        )


def _bounded(text: str, what: str) -> str:
    """One minted identifier, refused unless the store has room to record it.

    The bound is the store's, and it is checked here because here is where a refusal is
    still useful. An L2 identifier carries whatever a source named a thing, percent-
    encoded: a legal Git branch name of a couple of hundred characters mints an IRI past
    the column's CHECK, and so does a much shorter one written in a language with
    accents, where each of them costs six characters once encoded. Left to SQL, that
    arrives as an ``sqlite3.IntegrityError`` naming a column, raised from inside the
    transaction, and a caller catching the documented ``TraceError`` never sees it.
    """
    if len(text) > IRI_MAX_LENGTH:
        raise TraceError(
            f"{what} is {len(text)} characters, and this records at most {IRI_MAX_LENGTH}: "
            f"{text[:80]}... The identifier is well formed; it is the name inside it that is "
            f"too long, which is what a very long branch name or a heavily percent-encoded "
            f"one produces. Shorten the name the source knows the thing by, or point the "
            f"trace at the entity that contains it."
        )
    return text


def reference(value, what: str) -> str:
    """One reference to another layer, refused unless this layer minted it.

    This is what "bounded reference" means, and it is the whole of the bound: a trace
    may point at an L1 or an L2 node and at nothing else. A value that does not parse
    as an identifier ``semantic_layer.ids`` would have produced is refused, so the edge
    cannot quietly become a place to write a URL, a file path, a commit message or a
    sentence about what the run saw.
    """
    text = _text(value, what)
    for parse in (ids.parse, ids.parse_observed, ids.parse_source):
        try:
            parse(text)
        except ids.IdentifierError:
            continue
        return _bounded(text, what)
    raise TraceError(
        f"{what} is {text!r}, which is not an identifier this layer mints. A trace points at "
        f"L1 and L2 nodes by their minted identifiers and at nothing else: anything that "
        f"parses as neither is either a reference to something that does not exist here, or "
        f"text arriving where a reference belongs."
    )


def _agent(value: str) -> str:
    text = _text(value, "the run's agent")
    try:
        identifier = ids.parse(text)
    except ids.IdentifierError as error:
        raise TraceError(
            f"the run's agent is {text!r}, which is not an L1 identifier. A run is associated "
            f"with the agent identity the organization declared, so that who acted is a "
            f"business fact the trace points at rather than a name the runtime invented."
        ) from error
    if identifier.kind != "agent":
        raise TraceError(
            f"the run's agent is {text!r}, which names a {identifier.kind} rather than an "
            f"agent identity. Only an agent identity can be associated with a run; who is "
            f"accountable for it is reached through that identity in L1, not asserted here."
        )
    return _bounded(text, "the run's agent")


def _sequence(value, what: str) -> tuple:
    if isinstance(value, str | bytes) or not isinstance(value, Sequence):
        raise TraceError(f"{what} is {type(value).__name__}, and this reads a sequence there.")
    return tuple(value)


def _spans(run: Run, interval: tuple[str, str]) -> tuple[Span, ...]:
    spans = _sequence(run.spans, "the run's spans")
    if not spans:
        raise TraceError(
            "the run records no spans. A run with no spans is a run nothing is known about: "
            "the outcome says how it ended and the spans say what it did, and evidence "
            "without the second half cannot be learned from. A run whose span detail has "
            "since expired is a different thing, and the store records that it expired."
        )
    seen: dict[str, Span] = {}
    for span in spans:
        if not isinstance(span, Span):
            raise TraceError(f"the run's spans hold a {type(span).__name__}, and this reads a Span")
        span_id = _hex_id(span.span_id, SPAN_ID_PATTERN, 16, "a span id")
        if span_id in seen:
            raise TraceError(
                f"the run records the span id {span_id} twice. A span id identifies one "
                f"operation within one trace, so two of them is two records claiming to be "
                f"the same span and no way to say which parent means which."
            )
        seen[span_id] = span
        _named(span.operation, f"span {span_id}'s operation")
        _one_of(span.kind, SPAN_KINDS, f"span {span_id}'s kind")
        _one_of(span.status, SPAN_STATUSES, f"span {span_id}'s status")
        started = instant(span.started_at, f"span {span_id}'s start")
        ended = instant(span.ended_at, f"span {span_id}'s end")
        _interval(started, ended, f"span {span_id}")
        _inside(started, ended, interval, f"span {span_id}")
        for value in _sequence(span.touched, f"span {span_id}'s references"):
            reference(value, f"a node span {span_id} touched")

    _parentage(seen)
    return spans


def _parentage(spans: dict[str, Span]) -> None:
    """One tree, rooted once, with no span outside it.

    Three failures are the same failure seen from three sides: a parent that is not in
    this run, a cycle, and a second root. Each of them leaves a span that cannot be
    reached from the one operation the run began with, so all three are found by
    walking down from the root rather than by three separate scans.
    """
    for span_id, span in spans.items():
        if span.parent_span_id is None:
            continue
        parent = _hex_id(span.parent_span_id, SPAN_ID_PATTERN, 16, f"span {span_id}'s parent")
        if parent == span_id:
            raise TraceError(
                f"span {span_id} names itself as its parent. A span happened inside another "
                f"span, and nothing happened inside itself."
            )
        if parent not in spans:
            raise TraceError(
                f"span {span_id} names the parent {parent}, which this run does not record. A "
                f"parent outside the run cannot be resolved by anyone reading the evidence "
                f"later, so the tree is recorded whole or not at all."
            )

    roots = sorted(span_id for span_id, span in spans.items() if span.parent_span_id is None)
    if len(roots) != 1:
        raise TraceError(
            f"the run records {len(roots)} root spans ({roots or 'none'}), and a run has one: "
            f"the operation it began with. None means every span names a parent, which is a "
            f"cycle; more than one means two trees are being recorded as one run."
        )

    children: dict[str, list[str]] = {}
    for span_id, span in spans.items():
        if span.parent_span_id is not None:
            children.setdefault(span.parent_span_id, []).append(span_id)
    reached, frontier = set(), [roots[0]]
    while frontier:
        span_id = frontier.pop()
        if span_id in reached:
            continue
        reached.add(span_id)
        frontier.extend(children.get(span_id, ()))
    stranded = sorted(set(spans) - reached)
    if stranded:
        raise TraceError(
            f"the spans {stranded} cannot be reached from the run's root span {roots[0]}, so "
            f"they name each other in a cycle. A span tree that loops has no order, and "
            f"nothing reading it can say what happened inside what."
        )


def _metrics(run: Run) -> tuple[Metric, ...]:
    metrics = _sequence(run.metrics, "the run's metrics")
    seen = set()
    for metric in metrics:
        if not isinstance(metric, Metric):
            raise TraceError(
                f"the run's metrics hold a {type(metric).__name__}, and this reads a Metric"
            )
        name = _named(metric.name, "a metric name")
        if name in seen:
            raise TraceError(
                f"the run records the metric {name!r} twice. A run measures one thing once; "
                f"two values under one name is a rollup nothing can read back out."
            )
        seen.add(name)
        # bool is an int in Python, and `true` is not a measurement.
        if not isinstance(metric.value, int) or isinstance(metric.value, bool):
            raise TraceError(
                f"the metric {name!r} has the value {metric.value!r}, and a measurement is a "
                f"whole number. Integers only, so the same measurement serializes to the same "
                f"bytes on every machine and two summaries of one run can be compared by "
                f"hashing them."
            )
        if not METRIC_VALUE_MIN <= metric.value <= METRIC_VALUE_MAX:
            raise TraceError(
                f"the metric {name!r} has the value {metric.value}, and this records a "
                f"measurement between {METRIC_VALUE_MIN} and {METRIC_VALUE_MAX}. Python's "
                f"integers have no width and the column that records this one has sixty-four "
                f"bits, so a value past the bound is refused by SQLite from inside the "
                f"transaction rather than named here. Nothing a run measures comes near it: a "
                f"number that does is a counter that wrapped, or was never a count."
            )
        _one_of(metric.unit, METRIC_UNITS, f"the metric {name!r}'s unit")
    return metrics


def _findings(run: Run) -> tuple[Finding, ...]:
    findings = _sequence(run.findings, "the run's findings")
    for index, finding in enumerate(findings, start=1):
        if not isinstance(finding, Finding):
            raise TraceError(
                f"the run's findings hold a {type(finding).__name__}, and this reads a Finding"
            )
        _named(finding.code, f"finding {index}'s code")
        _one_of(finding.severity, FINDING_SEVERITIES, f"finding {index}'s severity")
        if finding.about is not None:
            reference(finding.about, f"what finding {index} is about")
    return findings


@dataclass(frozen=True)
class Validated:
    """One run, held to every rule, with its sequences settled into tuples."""

    trace_id: str
    started_at: str
    ended_at: str
    outcome: str
    spans: tuple[Span, ...]
    metrics: tuple[Metric, ...]
    findings: tuple[Finding, ...]
    agent: str | None


def validate(run: Run) -> Validated:
    """Hold a whole run to every rule, and return it settled.

    Every refusal is a ``TraceError`` naming what is wrong and what it would take to
    fix, because the caller is standing there with the run in their hand and is the
    only one who can. Nothing is written until this returns, so a run that is refused
    for its ninth span leaves no trace of its first eight.
    """
    if not isinstance(run, Run):
        raise TraceError(f"a {type(run).__name__} was handed here, and this records a Run")
    trace_id = _hex_id(run.trace_id, TRACE_ID_PATTERN, 32, "the trace id")
    started_at = instant(run.started_at, "the run's start")
    ended_at = instant(run.ended_at, "the run's end")
    _interval(started_at, ended_at, f"run {trace_id}")
    return Validated(
        trace_id=trace_id,
        started_at=started_at,
        ended_at=ended_at,
        outcome=_one_of(run.outcome, OUTCOME_STATUSES, "the run's outcome"),
        spans=_spans(run, (started_at, ended_at)),
        metrics=_metrics(run),
        findings=_findings(run),
        agent=None if run.agent is None else _agent(run.agent),
    )


#: Every field each record carries, so the closed schema is a thing the suite can hold
#: rather than a claim this docstring makes. A field added to one of the dataclasses
#: without a rule above it, a column beside it and a line in the documentation is a
#: failing build. See tests/test_trace_privacy.py.
RECORD_FIELDS = {
    record.__name__: tuple(field.name for field in fields(record))
    for record in (Run, Span, Metric, Finding)
}
