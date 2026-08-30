"""Recording a run: what is written, what is refused, and what a refusal leaves behind.

The claim under test is narrow and is the whole of what makes a trace worth keeping: a
run is recorded whole, against a pack that was really verified, or it is not recorded at
all. Every refusal below is checked twice - that it was refused, and that the store is
untouched afterwards - because a validator that rejects a run after writing half of it
has produced exactly the evidence nobody can read.
"""

import json
import sqlite3

import pytest
from trace_runs import (
    AGENT,
    AS_OF,
    CHILD_SPAN,
    ROOT_SPAN,
    TARGET,
    TRACE_ID,
    run,
    span,
    with_spans,
)

from semantic_layer import ids
from semantic_layer import pack as packs
from semantic_layer.github import digest_of
from semantic_layer.trace import Finding, Metric, TraceError, TraceStore, model
from semantic_layer.trace import store as store_module


def record(store, a_run, pack, **over):
    return store.record(a_run, pack=pack, as_of=AS_OF, **over)


def _empty(store) -> bool:
    return store.trace_ids() == ()


## The run that works.


def test_a_valid_run_is_recorded_whole(store, accepted_pack):
    iri = record(store, run(), accepted_pack, expect_target=TARGET)
    assert iri == ids.mint_trace("run", TRACE_ID)

    record_back = store.read(TRACE_ID)
    assert record_back.run == run()
    assert record_back.span_detail_expired_at is None


def test_the_pack_binding_is_derived_from_the_bytes_and_not_from_a_claim(store, accepted_pack):
    """What "prove which pack it used" means: identity that moves when the bytes move.

    A caller cannot assert which pack they used, and cannot name one by a path. The
    binding is a digest of each half of what was verified, and the entity is named by a
    digest over the pair, so a run that used other bytes can never appear to have used
    these.
    """
    record(store, run(), accepted_pack)
    binding = store.read(TRACE_ID).pack

    assert binding.content_digest == digest_of(accepted_pack.content)
    assert binding.manifest_digest == digest_of(accepted_pack.manifest)
    assert json.loads(accepted_pack.manifest)["observation"] == binding.observation
    assert binding.target == TARGET


def test_a_manifest_respelled_without_changing_a_field_is_a_different_pack(store, accepted_pack):
    """Both halves are hashed, and this is the case that says why.

    Tampering with either half is already refused by the verifier. A manifest
    re-rendered with the same fields in another spelling is not tampering and verifies
    happily - and it is not the bytes this run was handed, so it is not this pack.
    """
    stated = json.loads(accepted_pack.manifest)
    respelled = packs.Pack(
        content=accepted_pack.content,
        manifest=(json.dumps(stated, indent=4, sort_keys=True) + "\n").encode(),
    )
    record(store, run(), accepted_pack)
    first = store.read(TRACE_ID).pack

    with TraceStore.open(":memory:") as second_store:
        record(second_store, run(), respelled)
        second = second_store.read(TRACE_ID).pack

    assert first.content_digest == second.content_digest
    assert first.manifest_digest != second.manifest_digest
    assert first.identity != second.identity


## The pack, held by the real verifier.


def _tampered_content(pack):
    return packs.Pack(content=pack.content + b"\n", manifest=pack.manifest)


def _tampered_manifest(pack):
    stated = json.loads(pack.manifest)
    stated["target"] = "someone-else/repository"
    return packs.Pack(content=pack.content, manifest=packs.render(stated))


def _malformed_manifest(pack):
    return packs.Pack(content=pack.content, manifest=b"{not json")


@pytest.mark.parametrize(
    ("what", "tamper"),
    [
        ("content changed after the manifest was written", _tampered_content),
        ("a manifest field that the content contradicts", _tampered_manifest),
        ("a manifest that is not JSON", _malformed_manifest),
    ],
)
def test_a_pack_that_does_not_verify_is_refused_before_any_row_is_written(
    store, accepted_pack, what, tamper
):
    with pytest.raises(packs.PackError):
        record(store, run(), tamper(accepted_pack))
    assert _empty(store), what


def test_a_stale_pack_is_refused(store, accepted_pack):
    """Against the instant the caller supplies, which is the only testable question."""
    with pytest.raises(packs.PackError, match="out of date"):
        store.record(run(), pack=accepted_pack, as_of="2027-01-01T00:00:00Z")
    assert _empty(store)


def test_a_pack_from_another_source_or_about_another_target_is_refused(store, accepted_pack):
    with pytest.raises(packs.PackError, match="was expected"):
        record(
            store,
            run(),
            accepted_pack,
            expect_source="https://semantic-layer.19h09.co/l2/gitlab/gitlab-com",
        )
    assert _empty(store)

    with pytest.raises(packs.PackError, match="was expected"):
        record(store, run(), accepted_pack, expect_target="someone-else/repository")
    assert _empty(store)


def test_the_pack_is_verified_here_rather_than_taken_on_the_callers_word(store, accepted_pack):
    """There is no way to hand this a pack it has already decided to believe.

    The signature takes the two halves and an instant; it takes no "already verified"
    flag, no path to look one up by, and no manifest object a caller could have built.
    A run whose evidence names an unverified pack proves nothing about what it knew, so
    there is deliberately no shortcut past this.
    """
    import inspect

    parameters = set(inspect.signature(TraceStore.record).parameters)
    assert parameters == {"self", "run", "pack", "as_of", "expect_source", "expect_target"}


## Everything about a run that is refused, and refused atomically.


REFUSALS = [
    ("a trace id that is not 32 hex", run(trace_id="4bf92f35"), "not 32 lower-case hex"),
    ("a re-cased trace id", run(trace_id=TRACE_ID.upper()), "not 32 lower-case hex"),
    ("a span id that is not 16 hex", with_spans(span("00f067aa")), "not 16 lower-case hex"),
    (
        "the same span id twice",
        with_spans(span(), span(ROOT_SPAN, operation="read-branches")),
        "twice",
    ),
    (
        "a parent this run does not record",
        with_spans(span(), span(CHILD_SPAN, parent_span_id="b7ad6b7169203331")),
        "which this run does not record",
    ),
    ("a span that is its own parent", with_spans(span(parent_span_id=ROOT_SPAN)), "names itself"),
    (
        "two spans naming each other",
        with_spans(
            span(parent_span_id=CHILD_SPAN),
            span(CHILD_SPAN, parent_span_id=ROOT_SPAN),
        ),
        "root spans",
    ),
    (
        "two trees recorded as one run",
        with_spans(span(), span(CHILD_SPAN)),
        "2 root spans",
    ),
    (
        "a run that ended before it started",
        run(ended_at="2026-08-30T08:59:00Z"),
        "which is earlier",
    ),
    (
        "a span that ended before it started",
        with_spans(span(ended_at="2026-08-30T08:59:00Z")),
        "which is earlier",
    ),
    ("an instant that is not one", run(started_at="2026-08-30 09:00:00"), "not a UTC instant"),
    ("an instant that no calendar has", run(started_at="2026-02-31T09:00:00Z"), "is not one"),
    ("a run with no spans at all", run(spans=[]), "records no spans"),
    ("an outcome outside the closed set", run(outcome="cancelled"), "reads one of"),
    ("a span kind outside the closed set", with_spans(span(kind="database")), "reads one of"),
    ("a span status outside the closed set", with_spans(span(status="degraded")), "reads one of"),
    ("an operation that is not a name", with_spans(span(operation="GET /repos")), "reads a name"),
    (
        "a metric unit outside the closed set",
        run(metrics=[Metric("branches-read", 2, "furlong")]),
        "reads one of",
    ),
    (
        "a measurement that is not a whole number",
        run(metrics=[Metric("branches-read", 2.5, "count")]),
        "whole number",
    ),
    (
        "the same metric measured twice",
        run(metrics=[Metric("branches-read", 2, "count"), Metric("branches-read", 3, "count")]),
        "twice",
    ),
    (
        "a finding severity outside the closed set",
        run(findings=[Finding("branch-moved", "critical")]),
        "reads one of",
    ),
    (
        "a finding about something this layer never minted",
        run(
            findings=[
                Finding("branch-moved", "warning", about="https://github.com/vvonkledge/siana")
            ]
        ),
        "not an identifier this layer mints",
    ),
    (
        "a span touching something this layer never minted",
        with_spans(span(touched=["/etc/passwd"])),
        "not an identifier this layer mints",
    ),
    ("an agent that is not an L1 identifier", run(agent="siana"), "not an L1 identifier"),
    (
        "an agent that is not an agent identity",
        run(agent="https://semantic-layer.19h09.co/biz/capability/orchestrate-fleet-delivery"),
        "rather than an agent identity",
    ),
]


@pytest.mark.parametrize(
    ("what", "bad_run", "expected"), REFUSALS, ids=[what for what, _, _ in REFUSALS]
)
def test_a_run_that_cannot_be_read_is_refused_and_writes_nothing(
    store, accepted_pack, what, bad_run, expected
):
    with pytest.raises(TraceError, match=expected):
        record(store, bad_run, accepted_pack)
    assert _empty(store), what


def test_a_refusal_names_what_to_do_about_it(store, accepted_pack):
    """Not just that something is wrong: a caller holding the run is the only one who can fix it."""
    with pytest.raises(TraceError) as refusal:
        record(
            store,
            with_spans(span(), span(CHILD_SPAN, parent_span_id="b7ad6b7169203331")),
            accepted_pack,
        )
    message = str(refusal.value)
    assert "b7ad6b7169203331" in message and CHILD_SPAN in message
    assert "recorded whole or not at all" in message


def test_a_run_is_not_a_dict_of_whatever_the_runtime_had(store, accepted_pack):
    with pytest.raises(TraceError, match="records a Run"):
        record(store, {"trace_id": TRACE_ID}, accepted_pack)
    assert _empty(store)


## Exact bounds: how long a reference may be, and where a span may lie.


def _branch(name: str) -> str:
    """The identifier a branch of the observed repository mints, for whatever it is called."""
    return ids.mint_observed("github", "api-github-com", "branch", "1347717349", name)


#: How many characters of branch name an identifier still has room for. Derived rather
#: than written down, so the boundary stays exact if the base or the scope ever changes.
BRANCH_ROOM = model.IRI_MAX_LENGTH - len(_branch("x")) + 1
AGENT_ROOM = model.IRI_MAX_LENGTH - len(ids.mint("agent", "a")) + 1

#: An accented character costs six characters once percent-encoded, which is how a
#: branch name far shorter than the ASCII limit still mints an identifier past it.
ACCENTED_FITS = "é" * (BRANCH_ROOM // 6)
ACCENTED_OVERFLOWS = "é" * (BRANCH_ROOM // 6 + 1)

TOO_LONG = [
    (
        "a branch name long enough to mint past the bound",
        with_spans(span(touched=[_branch("b" * (BRANCH_ROOM + 1))])),
    ),
    (
        "a branch name whose accents expand past it",
        with_spans(span(touched=[_branch(ACCENTED_OVERFLOWS)])),
    ),
    (
        "a finding about a branch with a name that long",
        run(findings=[Finding("branch-moved", "warning", about=_branch("b" * (BRANCH_ROOM + 1)))]),
    ),
    ("an agent identity that long", run(agent=ids.mint("agent", "a" * (AGENT_ROOM + 1)))),
]


@pytest.mark.parametrize(("what", "bad_run"), TOO_LONG, ids=[what for what, _ in TOO_LONG])
def test_a_reference_too_long_for_the_store_is_refused_before_the_store(
    store, accepted_pack, what, bad_run
):
    """As a TraceError, which is the type the documentation tells a caller to catch.

    The bound is the store's column, and until it was checked here it was *only* the
    store's column: the identifier parsed, the run validated, and the refusal arrived
    from inside the transaction as an sqlite3.IntegrityError naming a CHECK constraint.
    That is not a subclass of TraceError, so a caller catching what the documentation
    told them to catch did not catch it, and what they got named a column rather than
    the branch name that was too long.
    """
    with pytest.raises(TraceError) as refusal:
        record(store, bad_run, accepted_pack)

    assert not isinstance(refusal.value, sqlite3.IntegrityError)
    assert str(model.IRI_MAX_LENGTH) in str(refusal.value)
    assert _empty(store), what


ACCEPTED = [
    (
        "the longest branch name that still fits",
        with_spans(span(touched=[_branch("b" * BRANCH_ROOM)])),
        _branch("b" * BRANCH_ROOM),
    ),
    (
        "the longest accented one that still fits",
        with_spans(span(touched=[_branch(ACCENTED_FITS)])),
        _branch(ACCENTED_FITS),
    ),
    (
        "the longest agent identity that fits",
        run(agent=ids.mint("agent", "a" * AGENT_ROOM)),
        ids.mint("agent", "a" * AGENT_ROOM),
    ),
]


@pytest.mark.parametrize(
    ("what", "good_run", "expected"), ACCEPTED, ids=[what for what, _, _ in ACCEPTED]
)
def test_a_reference_at_the_greatest_length_the_store_holds_is_recorded(
    store, accepted_pack, what, good_run, expected
):
    """The other side of the boundary, which is what says the two bounds agree.

    A writer stricter than its column would refuse identifiers the store has room for,
    and nothing but recording one and reading it back distinguishes that from a bound
    that is exactly right. Two of these are exactly at it; the accented one is as close
    as six-character characters get, which is the shape a real overflow arrives in.
    """
    assert len(expected) <= model.IRI_MAX_LENGTH
    record(store, good_run, accepted_pack)

    recorded = store.read(TRACE_ID)
    written = {iri for a_span in recorded.run.spans for iri in a_span.touched}
    assert expected in written | {recorded.run.agent}, what


def test_the_writers_bound_is_the_stores_own(store, accepted_pack):
    """One number, or the writer refuses what the column holds and nobody notices."""
    assert store_module.IRI_MAX_LENGTH is model.IRI_MAX_LENGTH
    assert len(_branch("b" * BRANCH_ROOM)) == model.IRI_MAX_LENGTH
    assert len(ids.mint("agent", "a" * AGENT_ROOM)) == model.IRI_MAX_LENGTH


OUTSIDE_THE_RUN = [
    (
        "a span that began before the run did",
        with_spans(span(started_at="2026-08-30T08:59:59Z")),
    ),
    (
        "a span that ended after the run did",
        with_spans(span(ended_at="2026-08-30T09:00:13Z")),
    ),
    (
        "a span from another day entirely",
        with_spans(span(started_at="2020-01-01T00:00:00Z", ended_at="2020-01-01T00:00:02Z")),
    ),
]


@pytest.mark.parametrize(
    ("what", "bad_run"), OUTSIDE_THE_RUN, ids=[what for what, _ in OUTSIDE_THE_RUN]
)
def test_a_span_outside_its_run_is_refused_and_writes_nothing(store, accepted_pack, what, bad_run):
    """A run's interval bounds every span it records, and nothing checked that.

    The run this suite uses is twelve seconds long in 2026 and would happily have
    recorded a span dated 2020. Retention is keyed off the run rather than the span, so
    it was never a hole in the ninety days - it is evidence that cannot be put on a
    timeline, which is the thing a trace is for.
    """
    with pytest.raises(TraceError) as refusal:
        record(store, bad_run, accepted_pack)

    message = str(refusal.value)
    assert run().started_at in message and run().ended_at in message, "names the run's interval"
    assert bad_run.spans[0].started_at in message, "names the span's"
    assert _empty(store), what


def test_a_span_sharing_the_runs_exact_start_or_end_is_inside_it(store, accepted_pack):
    """The bound is inclusive, which is not a detail: it is the ordinary case.

    A run's first span begins when the run begins and its last ends when the run ends,
    so an exclusive bound would refuse almost every real run.
    """
    record(
        store,
        with_spans(span(started_at=run().started_at, ended_at=run().ended_at)),
        accepted_pack,
    )

    assert store.trace_ids() == (TRACE_ID,)


## Replay.


def test_recording_the_same_run_twice_is_a_no_op(store, accepted_pack):
    """Because a writer that retries has to be safe to retry, and a retry is not a second run."""
    first = record(store, run(), accepted_pack)
    before = store.read(TRACE_ID)

    second = record(store, run(), accepted_pack)

    assert first == second
    assert store.trace_ids() == (TRACE_ID,)
    assert store.read(TRACE_ID) == before


def test_a_replay_is_a_no_op_only_when_the_whole_content_agrees(store, accepted_pack):
    """Every part of a run is compared, not just the identifiers it is keyed by."""
    record(store, run(), accepted_pack)
    for what, differing in (
        ("a different outcome", run(outcome="failed")),
        ("a different span", with_spans(span(operation="reconcile"))),
        ("a different rollup", run(metrics=[Metric("branches-read", 3, "count")])),
        ("a rollup the first run recorded and this one does not", run(findings=[])),
    ):
        with pytest.raises(TraceError, match="already recorded and this one differs"):
            record(store, differing, accepted_pack)
        assert store.read(TRACE_ID).run == run(), what


def test_a_trace_id_reused_for_another_pack_is_refused(store, accepted_pack):
    """The pack is part of the run: the same work against different knowledge is a different run."""
    stated = json.loads(accepted_pack.manifest)
    respelled = packs.Pack(
        content=accepted_pack.content,
        manifest=(json.dumps(stated, indent=4, sort_keys=True) + "\n").encode(),
    )
    record(store, run(), accepted_pack)
    with pytest.raises(TraceError, match=r"differs in \['run'\]"):
        record(store, run(), respelled)


## Atomicity.


def test_a_write_that_fails_partway_leaves_no_partial_run(store, accepted_pack, monkeypatch):
    """The guarantee the whole store rests on, tested by making the write fail on purpose.

    Validation and pack verification both happen before anything is written, so the
    only way to reach a half-written run is an error from the database itself. That is
    injected here rather than argued about, because "one transaction" is a claim about
    the rollback path and the rollback path is the one nothing else exercises.
    """
    connection = store._connection

    class FailsOnTheRollups:
        def __getattr__(self, name):
            return getattr(connection, name)

        def executemany(self, statement, values):
            if "INSERT INTO metric" in statement:
                raise RuntimeError("the disk went away")
            return connection.executemany(statement, values)

    monkeypatch.setattr(store, "_connection", FailsOnTheRollups())

    with pytest.raises(RuntimeError, match="the disk went away"):
        record(store, run(), accepted_pack)

    monkeypatch.undo()
    assert _empty(store)
    assert connection.execute("SELECT count(*) FROM span").fetchone()[0] == 0


## The store itself.


def test_a_store_written_by_another_schema_is_refused(tmp_path):
    path = tmp_path / "trace.sqlite3"
    TraceStore.open(path).close()

    connection = sqlite3.connect(path, isolation_level=None)
    connection.execute(f"PRAGMA user_version = {store_module.SCHEMA_VERSION + 1}")
    connection.close()

    with pytest.raises(TraceError, match="never migrated in place"):
        TraceStore.open(path)


def test_a_store_is_a_file_and_not_a_service(tmp_path, accepted_pack):
    """No collector, no port, nothing to start: the whole of "open" is opening a file."""
    path = tmp_path / "trace.sqlite3"
    with TraceStore.open(path) as opened:
        record(opened, run(), accepted_pack)
    assert path.exists()

    with TraceStore.open(path) as reopened:
        assert reopened.trace_ids() == (TRACE_ID,)


def test_reading_a_run_that_is_not_there_says_so(store):
    with pytest.raises(TraceError, match="no run"):
        store.read(TRACE_ID)


def test_a_run_carries_no_agent_when_none_was_supplied(store, accepted_pack):
    """Association is recorded where it is known and never invented where it is not."""
    record(store, run(agent=None), accepted_pack)
    assert store.read(TRACE_ID).run.agent is None
    assert AGENT not in str(store.summary(TRACE_ID).serialize(format="nt"))


## The public surface.


def test_the_supported_api_offers_no_way_to_change_a_recorded_run():
    """Append-only is what the API is, not only what the triggers enforce.

    A caller looking for an update or a delete finds neither, and finds nothing that
    takes a run and a change either. The one thing that removes anything is retention,
    which takes an instant and decides for itself what is old enough.
    """
    import semantic_layer.trace as trace

    public = {name for name in dir(TraceStore) if not name.startswith("_")}
    assert public == {"open", "close", "record", "expire_spans", "read", "summary", "trace_ids"}
    assert set(trace.__all__) == {name for name in dir(trace) if not name.startswith("_")} - {
        "model",
        "project",
        "store",
    }
    for name in public | set(trace.__all__):
        assert not any(word in name for word in ("update", "delete", "edit", "amend", "remove"))


def test_the_documented_example_runs_end_to_end(tmp_path, accepted_pack, monkeypatch):
    """The snippet in semantic_layer.trace's docstring, executed rather than believed.

    A library whose documented first example does not run is a library nobody gets
    past, and this is the one piece of it a reader meets before anything else.
    """
    import semantic_layer.trace as trace

    example = (trace.__doc__ or "").split("    from semantic_layer import pack")[1]
    example = "from semantic_layer import pack" + example.split("Three rules hold")[0]
    source = "\n".join(
        line[4:] if line.startswith("    ") else line for line in example.splitlines()
    )

    monkeypatch.chdir(tmp_path)
    namespace = {}
    exec(compile(source, "<the documented example>", "exec"), namespace)  # noqa: S102

    assert (tmp_path / "trace.sqlite3").exists()
    assert namespace["run_iri"] == ids.mint_trace("run", TRACE_ID)
    assert len(namespace["summary"]) > 0
    assert namespace["expired"] == (TRACE_ID,)


def test_something_that_is_not_a_pack_is_refused_by_name(store):
    with pytest.raises(TraceError, match="semantic_layer.pack.Pack"):
        record(store, run(), b"not a pack")
    assert _empty(store)
