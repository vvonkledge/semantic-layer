"""Append-only, and the one narrow way anything ever leaves.

Two claims, and they pull against each other, which is why both are tested here rather
than in separate files. Recorded evidence is never edited or selectively removed - not
by this library, and not by whoever opens the file with a SQLite shell. And full span
detail is removed after ninety days, because keeping the detail of every run a fleet
ever made is a liability nobody signed up for.

The boundary between them is where the mistakes live, so it is tested at the instant
itself and on both sides of it. Every instant here is supplied rather than read from the
clock: a retention policy that consults the wall clock answers a different question
every time it runs, and its boundary can be argued about but never demonstrated.
"""

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from trace_runs import AS_OF, TRACE_ID, run, span

from semantic_layer.github import INSTANT_FORMAT
from semantic_layer.trace import RETENTION_DAYS, TraceError, TraceStore, retention_horizon

#: The run under test ends here, and every instant below is measured from it.
ENDED_AT = run().ended_at


def _plus(instant: str, **delta) -> str:
    stamped = datetime.strptime(instant, INSTANT_FORMAT).replace(tzinfo=UTC)
    return (stamped + timedelta(**delta)).strftime(INSTANT_FORMAT)


#: The instant at which this run is exactly the retention age. A pass at this instant
#: keeps the detail; a pass one second later removes it.
BOUNDARY = _plus(ENDED_AT, days=RETENTION_DAYS)


@pytest.fixture
def recorded(store, accepted_pack):
    store.record(run(), pack=accepted_pack, as_of=AS_OF)
    return store


def _spans(store) -> int:
    return store._connection.execute("SELECT count(*) FROM span").fetchone()[0]


## The horizon.


def test_the_horizon_is_a_function_of_the_instant_it_is_given(store):
    """And of nothing else. No clock is read anywhere in the policy."""
    assert retention_horizon("2026-11-28T09:00:12Z") == "2026-08-30T09:00:12Z"
    assert retention_horizon(BOUNDARY) == ENDED_AT


def test_an_instant_retention_cannot_read_is_refused(store):
    for bad in ("2026-11-28", "yesterday", "2026-11-28T09:00:12+00:00"):
        with pytest.raises(TraceError, match="as_of"):
            retention_horizon(bad)


## The boundary.


@pytest.mark.parametrize(
    ("what", "as_of", "expired"),
    [
        ("a day inside the window", _plus(BOUNDARY, days=-1), False),
        ("one second inside the window", _plus(BOUNDARY, seconds=-1), False),
        ("exactly the retention age", BOUNDARY, False),
        ("one second past it", _plus(BOUNDARY, seconds=1), True),
        ("a day past it", _plus(BOUNDARY, days=1), True),
    ],
)
def test_retention_removes_span_detail_older_than_the_window_and_nothing_younger(
    recorded, what, as_of, expired
):
    """The boundary belongs to the data: a run of exactly the retention age is kept.

    Both sides of the comparison are defended, and the equality with them. A test
    sitting a week either side would leave "older than" and "at least as old as"
    indistinguishable, which is the one difference this policy turns on.
    """
    removed = recorded.expire_spans(as_of=as_of)

    assert bool(removed) is expired, what
    assert (_spans(recorded) == 0) is expired, what
    assert (recorded.read(TRACE_ID).span_detail_expired_at is not None) is expired, what


def test_what_a_run_is_judged_by_outlives_the_detail_it_was_computed_from(recorded):
    """Which is the whole reason the rollups exist as entities of their own."""
    before = recorded.read(TRACE_ID)

    recorded.expire_spans(as_of=_plus(BOUNDARY, seconds=1))
    after = recorded.read(TRACE_ID)

    assert after.run.spans == ()
    assert after.run.outcome == before.run.outcome
    assert after.run.metrics == before.run.metrics
    assert after.run.findings == before.run.findings
    assert after.pack == before.pack
    assert after.run.agent == before.run.agent
    assert after.span_detail_expired_at == retention_horizon(_plus(BOUNDARY, seconds=1))


def test_running_retention_again_is_safe_and_removes_nothing_further(recorded):
    """Which is what makes it safe to put on a timer and forget about."""
    first = recorded.expire_spans(as_of=_plus(BOUNDARY, seconds=1))
    assert first == (TRACE_ID,)
    expired_at = recorded.read(TRACE_ID).span_detail_expired_at

    for again in (_plus(BOUNDARY, seconds=1), _plus(BOUNDARY, days=400)):
        assert recorded.expire_spans(as_of=again) == ()
        assert recorded.read(TRACE_ID).span_detail_expired_at == expired_at


def test_a_pass_inside_the_window_leaves_the_run_expirable_later(recorded):
    """A no-op pass records nothing, so it cannot make a later pass believe it is done."""
    assert recorded.expire_spans(as_of=BOUNDARY) == ()
    assert recorded.read(TRACE_ID).span_detail_expired_at is None
    assert recorded.expire_spans(as_of=_plus(BOUNDARY, seconds=1)) == (TRACE_ID,)


def test_a_replay_of_a_run_whose_detail_expired_is_refused(recorded, accepted_pack):
    """Rather than quietly writing the spans back and undoing the removal."""
    recorded.expire_spans(as_of=_plus(BOUNDARY, seconds=1))
    with pytest.raises(TraceError, match="span detail has expired"):
        recorded.record(run(), pack=accepted_pack, as_of=AS_OF)
    assert _spans(recorded) == 0


## Append-only, against somebody who is not using this library.


@pytest.mark.parametrize(
    ("table", "statement"),
    [
        ("run", "UPDATE run SET outcome_status = 'succeeded'"),
        ("run", "DELETE FROM run"),
        ("metric", "UPDATE metric SET value = 0"),
        ("metric", "DELETE FROM metric"),
        ("finding", "UPDATE finding SET severity = 'info'"),
        ("finding", "DELETE FROM finding"),
        ("span_expiry", "UPDATE span_expiry SET horizon = '2020-01-01T00:00:00Z'"),
    ],
)
def test_recorded_evidence_cannot_be_edited_even_with_raw_sql(recorded, table, statement):
    """The guarantee is a trigger and not a rule this library follows.

    A guarantee that only holds while everyone uses the front door is not a guarantee
    about an append-only history: the whole value of one is that a record written last
    year still says what it said. So the refusal is in the schema, where a SQLite shell
    meets it too.
    """
    recorded.expire_spans(as_of=_plus(BOUNDARY, seconds=1))
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        recorded._connection.execute(statement)


def test_a_recorded_span_cannot_be_edited_either(recorded):
    """Held before retention runs, because afterwards there is no span left to edit."""
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        recorded._connection.execute("UPDATE span SET status = 'ok'")


def test_span_detail_cannot_be_deleted_outside_a_retention_pass(recorded):
    with pytest.raises(sqlite3.IntegrityError, match="retention pass"):
        recorded._connection.execute("DELETE FROM span")
    assert _spans(recorded) == 2


def test_a_retention_pass_cannot_take_a_span_that_is_not_old_enough(recorded):
    """The trigger reads the horizon itself rather than trusting the code driving it.

    This is the failure the whole arrangement exists for: a pass with a horizon
    computed one unit wrong would otherwise remove a run that is still inside the
    window, and there would be nothing left to notice it with.
    """
    connection = recorded._connection
    connection.execute("INSERT INTO retention_pass (horizon) VALUES (?)", (ENDED_AT,))
    with pytest.raises(sqlite3.IntegrityError, match="retention pass"):
        connection.execute("DELETE FROM span")
    connection.execute("DELETE FROM retention_pass")
    assert _spans(recorded) == 2


def test_a_second_run_inside_the_window_is_untouched_by_a_pass_for_the_first(store, accepted_pack):
    """Retention is per run, so an old run expiring says nothing about a recent one."""
    old = run()
    recent = run(
        trace_id="8e0c63257de34c92bf5d0a1e6b4f2a90",
        started_at=_plus(ENDED_AT, days=80),
        ended_at=_plus(ENDED_AT, days=80, seconds=9),
        spans=[
            span(
                "b7ad6b7169203331",
                operation="reconcile",
                started_at=_plus(ENDED_AT, days=80),
                ended_at=_plus(ENDED_AT, days=80, seconds=9),
            )
        ],
    )
    store.record(old, pack=accepted_pack, as_of=AS_OF)
    store.record(recent, pack=accepted_pack, as_of=AS_OF)

    assert store.expire_spans(as_of=_plus(BOUNDARY, seconds=1)) == (old.trace_id,)
    assert store.read(old.trace_id).run.spans == ()
    assert len(store.read(recent.trace_id).run.spans) == 1


def test_a_store_that_has_recorded_nothing_expires_nothing(store):
    assert store.expire_spans(as_of="2030-01-01T00:00:00Z") == ()


def test_the_retention_window_is_the_ninety_days_the_captain_decided(store):
    """Named here so that changing it is a decision somebody makes on purpose.

    The number is a policy, not an implementation detail: full spans for ninety days,
    derived rollups indefinitely. A change to it is a change to what the fleet keeps
    about people's work, and it fails this line first.
    """
    assert RETENTION_DAYS == 90
    assert retention_horizon("2026-12-01T00:00:00Z") == "2026-09-02T00:00:00Z"


def test_reopening_a_store_sees_the_expiry_that_already_happened(tmp_path, accepted_pack):
    """The record of an expiry is durable, or a later pass would remove nothing twice."""
    path = tmp_path / "trace.sqlite3"
    with TraceStore.open(path) as opened:
        opened.record(run(), pack=accepted_pack, as_of=AS_OF)
        opened.expire_spans(as_of=_plus(BOUNDARY, seconds=1))

    with TraceStore.open(path) as reopened:
        assert reopened.read(TRACE_ID).span_detail_expired_at is not None
        assert reopened.expire_spans(as_of=_plus(BOUNDARY, days=1)) == ()
