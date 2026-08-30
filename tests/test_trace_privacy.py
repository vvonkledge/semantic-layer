"""L3 stores structure and never payload, held against the representation itself.

The captain's decision is that a trace records what happened and never what was said:
no prompt, no completion, no tool argument, no tool result, no request or response body,
no environment dump, no opaque blob. Adding a payload field later is reversible;
removing sensitive data from an append-only history is not.

A policy of that shape is worth nothing written down. What is tested here is that the
representation cannot hold the thing the policy forbids - that there is no field, no
column and no unknown key a payload could arrive under - and that both halves say the
same thing, so a field added to one without the other is a failing build rather than a
quiet widening.
"""

import sqlite3

import pytest
from trace_runs import AS_OF, ROOT_SPAN, TRACE_ID, run, span, with_spans

from semantic_layer.trace import Finding, Metric, Run, Span, TraceError
from semantic_layer.trace import model as trace_model
from semantic_layer.trace import store as trace_store

#: Exactly what a caller may write down about a run, committed here so that adding a
#: field is a decision somebody makes on purpose and defends. A field that appears in
#: one of the dataclasses and not here fails this file, whatever it is called.
RECORD_FIELDS = {
    "Run": (
        "trace_id",
        "started_at",
        "ended_at",
        "outcome",
        "spans",
        "metrics",
        "findings",
        "agent",
    ),
    "Span": (
        "span_id",
        "operation",
        "kind",
        "status",
        "started_at",
        "ended_at",
        "parent_span_id",
        "touched",
    ),
    "Metric": ("name", "value", "unit"),
    "Finding": ("code", "severity", "about"),
}

#: And exactly what the store may hold. Same purpose, other half: a column is where a
#: payload would live if a field ever let one through, so the two lists are committed
#: apart and compared against the schema separately.
COLUMNS = {
    "run": (
        "trace_id",
        "started_at",
        "ended_at",
        "outcome_status",
        "agent",
        "pack_identity",
        "pack_content_digest",
        "pack_manifest_digest",
        "pack_observation",
        "pack_source",
        "pack_target",
    ),
    "span": (
        "trace_id",
        "span_id",
        "parent_span_id",
        "operation",
        "kind",
        "status",
        "started_at",
        "ended_at",
    ),
    "span_reference": ("trace_id", "span_id", "iri"),
    "metric": ("trace_id", "name", "value", "unit"),
    "finding": ("trace_id", "ordinal", "code", "severity", "about"),
    "span_expiry": ("trace_id", "horizon"),
    "retention_pass": ("horizon",),
}

#: The words a payload arrives under. None of them is a field or a column here, and a
#: schema that grows one has to answer to this list before anything else.
FORBIDDEN = (
    "prompt",
    "completion",
    "message",
    "content",
    "body",
    "request",
    "response",
    "argument",
    "arguments",
    "result",
    "output",
    "input",
    "payload",
    "blob",
    "data",
    "attributes",
    "attribute",
    "metadata",
    "extra",
    "env",
    "environment",
    "detail",
    "description",
    "text",
    "note",
    "log",
    "stack",
    "traceback",
    "exception",
)

#: What a payload looks like when somebody tries. Each is offered to every text field
#: below, so nothing is refused because one particular field happened to be narrow.
PAYLOADS = (
    "You are a helpful assistant. The customer's card ending 4242 was declined because",
    '{"tool": "bash", "arguments": {"command": "cat ~/.aws/credentials"}}',
    'HTTP/1.1 200 OK\nContent-Type: application/json\n\n{"token": "ghp_secret"}',
    "a" * 5000,
    b"\x00\x01\x02binary",
)


## The two halves, and the fact that they are closed.


def test_the_records_carry_exactly_the_fields_committed_here():
    assert trace_model.RECORD_FIELDS == RECORD_FIELDS


def test_the_store_carries_exactly_the_columns_committed_here(store):
    tables = {
        row[0]
        for row in store._connection.execute(
            "SELECT name FROM sqlite_schema WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    assert tables == set(COLUMNS)
    for table, expected in COLUMNS.items():
        found = tuple(row[1] for row in store._connection.execute(f"PRAGMA table_info({table})"))
        assert found == expected, table


@pytest.mark.parametrize("word", FORBIDDEN)
def test_no_field_or_column_is_named_after_a_payload(word):
    """A blunt check, and the one that would catch the field somebody adds in a hurry.

    Naming is not the guarantee - the guarantee is the two closed lists above and the
    types under them - but the day a payload arrives it arrives under one of these
    words, and this is the test that says so in the diff rather than in review.
    """
    fields = {name for record in RECORD_FIELDS.values() for name in record}
    columns = {name for table in COLUMNS.values() for name in table}
    assert word not in fields and word not in columns


def test_every_stored_column_is_typed_and_bounded(store):
    """STRICT tables, so a TEXT column refuses a blob rather than storing one.

    Without STRICT, SQLite would take whatever it was handed in any column - which is
    exactly how a payload would end up in an append-only history despite every check
    above it. Each text column then carries a CHECK bounding what it may hold, so the
    only text that fits is the shape the field was declared for.
    """
    schema = "\n".join(
        row[0]
        for row in store._connection.execute(
            "SELECT sql FROM sqlite_schema WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    )
    assert "BLOB" not in schema
    assert schema.count("STRICT") == len(COLUMNS)
    for table, columns in COLUMNS.items():
        statement = next(
            row[0]
            for row in store._connection.execute(
                "SELECT sql FROM sqlite_schema WHERE type = 'table' AND name = ?", (table,)
            )
        )
        for column, declared in (
            (row[1], row[2]) for row in store._connection.execute(f"PRAGMA table_info({table})")
        ):
            assert declared in {"TEXT", "INTEGER"}, f"{table}.{column} is {declared}"
            if declared == "TEXT":
                assert "CHECK" in statement and column in statement, f"{table}.{column}"
        assert columns


## A payload offered to every field that takes text.


TEXT_FIELDS = [
    ("the trace id", lambda value: run(trace_id=value)),
    ("the run's start", lambda value: run(started_at=value)),
    ("the run's outcome", lambda value: run(outcome=value)),
    ("the agent", lambda value: run(agent=value)),
    ("a span id", lambda value: with_spans(span(value))),
    ("a span operation", lambda value: with_spans(span(operation=value))),
    ("a span kind", lambda value: with_spans(span(kind=value))),
    ("a span status", lambda value: with_spans(span(status=value))),
    (
        "a parent span id",
        lambda value: with_spans(span(), span("a2fb4a1d1a96d312", parent_span_id=value)),
    ),
    ("a node a span touched", lambda value: with_spans(span(touched=[value]))),
    ("a metric name", lambda value: run(metrics=[Metric(value, 2, "count")])),
    ("a metric unit", lambda value: run(metrics=[Metric("branches-read", 2, value)])),
    ("a finding code", lambda value: run(findings=[Finding(value, "warning")])),
    ("a finding severity", lambda value: run(findings=[Finding("branch-moved", value)])),
    (
        "what a finding is about",
        lambda value: run(findings=[Finding("branch-moved", "warning", about=value)]),
    ),
]


@pytest.mark.parametrize(("what", "build"), TEXT_FIELDS, ids=[what for what, _ in TEXT_FIELDS])
@pytest.mark.parametrize(
    "payload", PAYLOADS, ids=["prompt", "tool-call", "http-body", "long", "bytes"]
)
def test_a_payload_offered_to_any_field_is_refused(store, accepted_pack, what, build, payload):
    with pytest.raises(TraceError):
        store.record(build(payload), pack=accepted_pack, as_of=AS_OF)
    assert store.trace_ids() == (), what


#: Each record, complete and valid, so the only thing wrong with it below is the extra
#: key. Passing an incomplete record would raise for the missing arguments instead and
#: prove nothing about the unknown one.
COMPLETE = {
    "Run": (Run, {f: getattr(run(), f) for f in RECORD_FIELDS["Run"]}),
    "Span": (Span, {f: getattr(span(), f) for f in RECORD_FIELDS["Span"]}),
    "Metric": (Metric, {"name": "branches-read", "value": 2, "unit": "count"}),
    "Finding": (Finding, {"code": "branch-moved", "severity": "warning", "about": None}),
}


@pytest.mark.parametrize(
    ("what", "keyword"),
    [("Run", "prompt"), ("Span", "attributes"), ("Metric", "detail"), ("Finding", "description")],
)
def test_a_payload_cannot_arrive_under_a_key_nobody_reviewed(what, keyword):
    """The failure mode the closed schema exists for.

    An attribute bag is the obvious shape for a trace writer and is the one the policy
    forbids, because the day somebody wants the prompt they put it under a key nobody
    reviewed and it is in an append-only history for good. There is no bag, so an
    unknown key is a TypeError before any of this repository's code runs - and the
    record is otherwise complete here, so that is the only thing it can be raising for.
    """
    record, arguments = COMPLETE[what]
    assert record(**arguments) is not None
    with pytest.raises(TypeError, match=keyword):
        record(**arguments, **{keyword: "You are a helpful assistant"})


## And a payload offered to the store directly, past every check above.


@pytest.mark.parametrize(
    ("what", "statement", "values"),
    [
        (
            "a blob in a text column",
            "INSERT INTO span (trace_id, span_id, operation, kind, status, started_at, ended_at) "
            "VALUES (?, ?, ?, 'internal', 'ok', '2026-08-30T09:00:00Z', '2026-08-30T09:00:02Z')",
            (TRACE_ID, "b7ad6b7169203331", b"\x00binary"),
        ),
        (
            "prose in an operation name",
            "INSERT INTO span (trace_id, span_id, operation, kind, status, started_at, ended_at) "
            "VALUES (?, ?, ?, 'internal', 'ok', '2026-08-30T09:00:00Z', '2026-08-30T09:00:02Z')",
            (TRACE_ID, "b7ad6b7169203331", "You are a helpful assistant"),
        ),
        (
            "a URL where a minted reference belongs",
            "INSERT INTO span_reference (trace_id, span_id, iri) VALUES (?, ?, ?)",
            (TRACE_ID, ROOT_SPAN, "https://github.com/vvonkledge/siana"),
        ),
        (
            "a sentence where a minted reference belongs",
            "INSERT INTO finding (trace_id, ordinal, code, severity, about) "
            "VALUES (?, 9, 'x', 'info', ?)",
            (TRACE_ID, "the customer's card was declined"),
        ),
    ],
)
def test_the_store_refuses_a_payload_written_past_this_library(
    store, accepted_pack, what, statement, values
):
    """Because a guarantee that only holds through the front door is not one.

    The model refuses all of this before the store is reached. This is the second wall:
    somebody with a SQLite connection - a later version of this code, a migration
    script, a person at a shell - meets the same refusal, because the shape a column
    may hold is written into the schema rather than enforced on the way in.
    """
    store.record(run(), pack=accepted_pack, as_of=AS_OF)
    with pytest.raises(sqlite3.IntegrityError):
        store._connection.execute(statement, values)


def test_the_privacy_boundary_is_the_same_one_the_documentation_states():
    """The forbidden list is the captain's, and it is here so it cannot drift quietly."""
    documented = (trace_store.__doc__ or "") + (trace_model.__doc__ or "")
    for phrase in ("prompt", "completion", "tool argument", "tool result", "blob"):
        assert phrase in documented
