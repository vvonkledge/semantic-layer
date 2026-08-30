"""The process boundary, tested the way the only consumer of it will use it.

Every test here calls ``main`` with an argument list and reads what came back out of
stdout, because that is the whole of what SIANA will ever see. Nothing reaches into the
command's internals, and nothing asserts on a Python object it returned: a test that
did would go on passing after a change that broke every consumer, which is the failure
this file exists to catch.

``invoke`` holds the four promises that are true of every invocation - one document on
stdout, nothing on stderr, a stated layout, and an exit code that agrees with the
document's status - so each test below only has to say what is different about its own
case. That is deliberate: the promises are what a consumer builds on, and asserting them
once per test file rather than once per test is how they stay true of the invocations
nobody thought to check.
"""

import json
import os
import sqlite3
import sys
from dataclasses import asdict, replace
from pathlib import Path
from typing import NamedTuple

import pytest
import trace_runs

from semantic_layer import cli, ids
from semantic_layer import pack as packs
from semantic_layer.cli import files, response, run_input
from semantic_layer.trace import Metric, Run, TraceStore

TARGET = trace_runs.TARGET
SOURCE = "https://semantic-layer.19h09.co/l2/github/api-github-com"

#: An instant inside the committed pack's freshness window, and the one the trace suite
#: already verifies it against. Shared rather than restated: a second hard-coded instant
#: is a second thing to move whenever the observation is refreshed.
AS_OF = trace_runs.AS_OF

#: An instant after the retention window, so a pass expires the run the tests record.
LONG_AFTER = "2026-12-01T00:00:00Z"


class Answer(NamedTuple):
    status: int
    document: dict
    text: str

    @property
    def result(self) -> dict:
        assert self.document["status"] == "ok", self.document
        return self.document["result"]

    @property
    def error(self) -> dict:
        assert self.document["status"] == "error", self.document
        return self.document["error"]


@pytest.fixture
def invoke(capsys):
    """One invocation, held to everything that is true of all of them."""

    def call(*argv: str) -> Answer:
        status = cli.main(list(argv))
        captured = capsys.readouterr()
        assert captured.err == "", f"{argv} wrote to stderr: {captured.err!r}"
        document = json.loads(captured.out)
        assert document["schema"] == response.SCHEMA
        assert document["version"] == response.VERSION
        assert document["status"] in ("ok", "error")
        if document["status"] == "ok":
            assert status == response.OK
            assert "error" not in document
        else:
            assert status == response.EXIT_BY_KIND[document["error"]["kind"]]
            assert "result" not in document
        return Answer(status, document, captured.out)

    return call


@pytest.fixture
def pack_dir(tmp_path):
    """A copy of the committed pack, so a test can change one half of it."""
    directory = tmp_path / "pack"
    directory.mkdir()
    committed = packs.read(packs.pack_dir())
    (directory / packs.CONTENT_NAME).write_bytes(committed.content)
    (directory / packs.MANIFEST_NAME).write_bytes(committed.manifest)
    return directory


@pytest.fixture
def store_path(tmp_path):
    return tmp_path / "trace.sqlite3"


def document(run: Run) -> dict:
    """One run as the input document, built from the run the trace suite already uses.

    Derived rather than written out, so the document and the model cannot drift: a field
    added to a dataclass turns up here without anyone remembering to add it.
    """
    return {"schema": run_input.SCHEMA, "version": run_input.VERSION, "run": asdict(run)}


@pytest.fixture
def input_file(tmp_path):
    def write(payload, name: str = "run.json"):
        path = tmp_path / name
        path.write_bytes(payload if isinstance(payload, bytes) else json.dumps(payload).encode())
        return str(path)

    return write


def record(invoke, store_path, pack_dir, input_file, run=None, **over):
    return invoke(
        "trace",
        "record",
        "--store",
        str(store_path),
        "--pack",
        str(pack_dir),
        "--as-of",
        over.pop("as_of", AS_OF),
        "--expect-target",
        TARGET,
        "--input",
        input_file(document(trace_runs.run() if run is None else run)),
    )


## The contract every command keeps.


def test_help_is_the_one_invocation_that_writes_prose(capsys):
    """A person gets a usage message; a program never does. Both on stdout."""
    with pytest.raises(SystemExit) as exit:
        cli.main(["--help"])
    assert exit.value.code == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert "semantic-layer" in captured.out


@pytest.mark.parametrize(
    "argv",
    [
        (),
        ("pack",),
        ("trace",),
        ("pack", "polish"),
        ("pack", "verify"),
        ("pack", "verify", "--directory", "somewhere"),
        ("pack", "verify", "--directory", "somewhere", "--as-of", AS_OF, "--nonsense", "1"),
        ("trace", "get", "--store", "somewhere"),
    ],
    ids=[
        "nothing at all",
        "a group with no action",
        "a trace group with no action",
        "an action that does not exist",
        "an action with none of its options",
        "an action missing its instant",
        "an option nothing defines",
        "a read with no trace id",
    ],
)
def test_a_call_the_grammar_does_not_define_is_refused_as_usage(invoke, argv):
    """argparse's own refusals arrive as the document, never as a sentence on stderr."""
    answer = invoke(*argv)
    assert answer.status == 2
    assert answer.error["kind"] == "usage"


def test_a_response_is_ascii_whatever_is_in_it(invoke, pack_dir):
    """Standard output is encoded by the caller's locale, and a consumer may have none.

    A container, a daemon or a cron entry commonly runs with no locale set, where Python
    encodes stdout as ASCII. A pack naming a repository with an accent in it would then
    raise on the way out, having verified everything and answered nothing - so the
    document is escaped instead, which every JSON reader undoes.
    """
    answer = invoke("pack", "verify", "--directory", str(pack_dir), "--as-of", AS_OF)
    answer.text.encode("ascii")

    written = response.render({"name": "vvonkledge/sïana", "note": "\u2014 and an em dash"})
    written.encode("ascii")
    assert json.loads(written)["name"] == "vvonkledge/sïana"


def test_the_command_is_named_once_it_is_known(invoke, pack_dir):
    answer = invoke("pack", "verify", "--directory", str(pack_dir), "--as-of", AS_OF)
    assert answer.document["command"] == "pack verify"


def test_a_call_that_never_resolved_a_command_names_none(invoke):
    """A usage refusal before the grammar settled says so rather than guessing."""
    assert invoke("pack", "polish").document["command"] is None


def test_every_command_the_grammar_offers_is_dispatched():
    """A command in the grammar with nothing behind it would be a KeyError at runtime.

    argparse has no public way to ask a parser what its subcommands are, so this reads
    them off the action that holds them. That is private, and the trade is deliberate: a
    grammar and a dispatch table that disagree is a traceback for whoever ran the
    command, and this failing on a future argparse is a fix in one place here.
    """
    grammar = cli._grammar()
    groups = grammar._subparsers._group_actions[0].choices
    named = {f"{group} {action}" for group, parser in groups.items() for action in _actions(parser)}
    assert named == set(cli.COMMANDS)


def _actions(parser):
    return parser._subparsers._group_actions[0].choices


def test_no_command_reads_the_environment_or_the_clock_to_find_anything():
    """Nothing is inferred, and the cheapest way to hold that is to look.

    Every path, instant and expectation this command uses is stated on the command line.
    A lookup in the environment or a glance at the clock would be invisible in every test
    that passes one, and would only show up as a consumer on another machine, or the same
    one an hour later, getting a different answer.
    """
    for module in (cli, files, run_input, response):
        source = Path(module.__file__).read_text(encoding="utf-8")
        for reached in (
            "os.environ",
            "getenv",
            "expanduser",
            "Path.home",
            "Path.cwd",
            "datetime.now",
            "utcnow",
            "time.time",
        ):
            assert reached not in source, f"{module.__name__} reaches for {reached}"


## Verifying a pack.


def test_verify_reports_what_the_bytes_bind_to(invoke, pack_dir):
    committed = packs.read(packs.pack_dir())
    manifest = json.loads(committed.manifest)
    answer = invoke("pack", "verify", "--directory", str(pack_dir), "--as-of", AS_OF)
    pack = answer.result["pack"]
    assert answer.result["as_of"] == AS_OF
    assert pack["content_digest"] == manifest["content_digest"]
    assert pack["content_bytes"] == len(committed.content)
    assert pack["manifest_bytes"] == len(committed.manifest)
    assert pack["observation"] == manifest["observation"]
    assert pack["source"] == manifest["source"] == SOURCE
    assert pack["target"] == manifest["target"] == TARGET
    assert pack["observed_at"] == manifest["observed_at"]
    assert pack["fresh_until"] == manifest["fresh_until"]
    assert pack["artifact_count"] == manifest["artifact_count"]
    assert pack["content_media_type"] == manifest["content_media_type"]
    assert pack["vocabulary_version"] == manifest["vocabulary_version"]
    assert pack["graph"] == manifest["graph"]


def test_the_identity_is_the_one_the_store_would_record(invoke, pack_dir):
    """One pack has one identity, whoever asks. A second derivation would be a second."""
    from semantic_layer.trace.store import binding_of

    committed = packs.read(packs.pack_dir())
    binding = binding_of(committed, json.loads(committed.manifest))
    answer = invoke("pack", "verify", "--directory", str(pack_dir), "--as-of", AS_OF)
    assert answer.result["pack"]["identity"] == binding.identity


def test_two_verifications_of_one_pack_are_the_same_bytes(invoke, pack_dir):
    first = invoke("pack", "verify", "--directory", str(pack_dir), "--as-of", AS_OF)
    second = invoke("pack", "verify", "--directory", str(pack_dir), "--as-of", AS_OF)
    assert first.text == second.text


def test_export_returns_exactly_the_bytes_it_verified(invoke, pack_dir):
    """The round trip is the whole promise: what a consumer gets is what was checked."""
    from semantic_layer.github import digest_of

    answer = invoke("pack", "export", "--directory", str(pack_dir), "--as-of", AS_OF)
    content = answer.result["content"]["text"].encode("utf-8")
    manifest = answer.result["manifest"]["text"].encode("utf-8")
    assert content == (pack_dir / packs.CONTENT_NAME).read_bytes()
    assert manifest == (pack_dir / packs.MANIFEST_NAME).read_bytes()
    assert answer.result["content"]["encoding"] == answer.result["manifest"]["encoding"] == "utf-8"
    assert digest_of(content) == answer.result["pack"]["content_digest"]
    assert digest_of(manifest) == answer.result["pack"]["manifest_digest"]


def test_export_returns_what_it_verified_even_if_the_files_change_underneath(
    invoke, pack_dir, monkeypatch
):
    """Read once: what a consumer is handed and what was checked cannot come apart.

    The halves are rewritten after they were read and before they were verified, which is
    the window a race, a repointed symlink or somebody editing the file would land in.
    The export is the values that were read, so the substitution reaches nothing - and
    the digests reported are digests of what came back.
    """
    from semantic_layer.github import digest_of

    original = packs.verify

    def swap_then_verify(content, manifest, **named):
        (pack_dir / packs.CONTENT_NAME).write_bytes(b"something else entirely\n")
        (pack_dir / packs.MANIFEST_NAME).write_bytes(b"{}")
        return original(content, manifest, **named)

    monkeypatch.setattr(packs, "verify", swap_then_verify)
    answer = invoke("pack", "export", "--directory", str(pack_dir), "--as-of", AS_OF)
    committed = packs.read(packs.pack_dir())
    assert answer.result["content"]["text"].encode("utf-8") == committed.content
    assert answer.result["manifest"]["text"].encode("utf-8") == committed.manifest
    assert answer.result["pack"]["content_digest"] == digest_of(committed.content)
    assert answer.result["pack"]["manifest_digest"] == digest_of(committed.manifest)


def test_a_symlink_to_something_that_is_not_a_file_is_refused(invoke, pack_dir, tmp_path):
    """A name is not a file, and what is checked is the descriptor that was opened."""
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    content = pack_dir / packs.CONTENT_NAME
    content.unlink()
    content.symlink_to(fifo)
    answer = invoke("pack", "verify", "--directory", str(pack_dir), "--as-of", AS_OF)
    assert answer.status == 1
    assert answer.error["kind"] == "path"
    assert "regular file" in answer.error["message"]


def test_a_symlink_to_nothing_at_all_is_refused(invoke, pack_dir, tmp_path):
    content = pack_dir / packs.CONTENT_NAME
    content.unlink()
    content.symlink_to(tmp_path / "was-here-a-moment-ago")
    answer = invoke("pack", "verify", "--directory", str(pack_dir), "--as-of", AS_OF)
    assert answer.status == 1
    assert answer.error["kind"] == "path"


def test_a_manifest_respelled_is_a_different_pack(invoke, pack_dir):
    """L3 names a pack by both halves, so an equivalent manifest is not the same one.

    Nothing about the observation changed and verification is happy either way. What
    changed is the bytes a run would have been handed, and a binding that ignored them
    would call two runs that were told different things the same run.
    """
    before = invoke("pack", "verify", "--directory", str(pack_dir), "--as-of", AS_OF)
    manifest = json.loads((pack_dir / packs.MANIFEST_NAME).read_bytes())
    (pack_dir / packs.MANIFEST_NAME).write_bytes(
        (json.dumps(manifest, indent=4, sort_keys=True) + "\n").encode()
    )
    after = invoke("pack", "verify", "--directory", str(pack_dir), "--as-of", AS_OF)
    assert after.result["pack"]["content_digest"] == before.result["pack"]["content_digest"]
    assert after.result["pack"]["identity"] != before.result["pack"]["identity"]


def _refuse_pack(invoke, pack_dir, *, as_of=AS_OF, expectations=()):
    for command in ("verify", "export"):
        answer = invoke(
            "pack", command, "--directory", str(pack_dir), "--as-of", as_of, *expectations
        )
        assert answer.status == 1, answer.document
        assert answer.error["kind"] in ("pack", "path")
        # Nothing partial: a refusal carries no half of the pack it refused.
        assert "result" not in answer.document
    return answer


def test_a_stale_pack_is_refused_by_both_commands(invoke, pack_dir):
    _refuse_pack(invoke, pack_dir, as_of="2027-01-01T00:00:00Z")


def test_tampered_content_is_refused(invoke, pack_dir):
    path = pack_dir / packs.CONTENT_NAME
    path.write_bytes(path.read_bytes().replace(b"vvonkledge", b"someoneelse"))
    _refuse_pack(invoke, pack_dir)


def test_content_that_is_not_a_graph_is_refused(invoke, pack_dir):
    """The digest agrees, so nothing was changed in transit - what was sent is not RDF."""
    body = b"this is not n-triples\n"
    (pack_dir / packs.CONTENT_NAME).write_bytes(body)
    manifest = json.loads((pack_dir / packs.MANIFEST_NAME).read_bytes())
    from semantic_layer.github import digest_of

    manifest["content_digest"] = digest_of(body)
    manifest["content_bytes"] = len(body)
    (pack_dir / packs.MANIFEST_NAME).write_bytes(packs.render(manifest))
    _refuse_pack(invoke, pack_dir)


def test_content_that_is_not_utf8_is_refused(invoke, pack_dir):
    from semantic_layer.github import digest_of

    body = b"\xff\xfe not text at all\n"
    (pack_dir / packs.CONTENT_NAME).write_bytes(body)
    manifest = json.loads((pack_dir / packs.MANIFEST_NAME).read_bytes())
    manifest["content_digest"] = digest_of(body)
    manifest["content_bytes"] = len(body)
    (pack_dir / packs.MANIFEST_NAME).write_bytes(packs.render(manifest))
    _refuse_pack(invoke, pack_dir)


def test_a_manifest_that_is_not_json_is_refused(invoke, pack_dir):
    (pack_dir / packs.MANIFEST_NAME).write_bytes(b"{not json")
    _refuse_pack(invoke, pack_dir)


def test_a_manifest_that_is_not_utf8_is_refused(invoke, pack_dir):
    """The other half of the pair: content that is not UTF-8 is covered above."""
    (pack_dir / packs.MANIFEST_NAME).write_bytes(b"\xff\xfe not text at all")
    _refuse_pack(invoke, pack_dir)


@pytest.mark.parametrize("command", ["verify", "export"])
def test_a_manifest_nested_past_the_parser_is_refused_as_a_document(invoke, pack_dir, command):
    """A traceback is not a document, and this is the way one got out.

    Deeply nested JSON is valid JSON that the parser gives up on rather than rejects, so
    it raised a `RecursionError` - which is neither a `PackError` nor anything the
    boundary catches. The command exited with a stack trace on the stream it promises to
    leave empty and nothing at all on stdout, so a consumer parsing the answer could not
    tell a refusal from a crash. `invoke` holds both promises for every case in this
    file, which is what makes this a one-line assertion.
    """
    (pack_dir / packs.MANIFEST_NAME).write_bytes(_nested())
    answer = invoke("pack", command, "--directory", str(pack_dir), "--as-of", AS_OF)
    assert answer.status == 1
    assert answer.error["kind"] == "pack"


def test_a_run_nested_past_the_parser_is_refused_as_a_document(
    invoke, store_path, pack_dir, input_file
):
    answer = invoke(
        "trace",
        "record",
        "--store",
        str(store_path),
        "--pack",
        str(pack_dir),
        "--as-of",
        AS_OF,
        "--input",
        input_file(_nested()),
    )
    assert answer.status == 2
    assert answer.error["kind"] == "input"
    assert _recorded(store_path) == ()


def _nested() -> bytes:
    """A document deep enough that the JSON parser gives up on it."""
    depth = sys.getrecursionlimit() * 20
    return ("[" * depth + "]" * depth).encode("utf-8")


def test_a_manifest_carrying_a_field_nothing_holds_is_refused(invoke, pack_dir):
    manifest = json.loads((pack_dir / packs.MANIFEST_NAME).read_bytes())
    manifest["trust_me"] = "yes"
    (pack_dir / packs.MANIFEST_NAME).write_bytes(packs.render(manifest))
    _refuse_pack(invoke, pack_dir)


def test_a_pack_from_another_source_is_refused(invoke, pack_dir):
    _refuse_pack(
        invoke,
        pack_dir,
        expectations=("--expect-source", "https://semantic-layer.19h09.co/l2/gitlab/example"),
    )


def test_a_pack_about_another_target_is_refused(invoke, pack_dir):
    _refuse_pack(invoke, pack_dir, expectations=("--expect-target", "someone/else"))


def test_a_half_that_is_not_there_is_refused_by_name(invoke, pack_dir):
    (pack_dir / packs.CONTENT_NAME).unlink()
    answer = invoke("pack", "verify", "--directory", str(pack_dir), "--as-of", AS_OF)
    assert answer.status == 1
    assert answer.error["kind"] == "path"
    assert packs.CONTENT_NAME in answer.error["message"]


def test_a_directory_where_a_half_belongs_is_refused(invoke, pack_dir):
    (pack_dir / packs.CONTENT_NAME).unlink()
    (pack_dir / packs.CONTENT_NAME).mkdir()
    answer = invoke("pack", "verify", "--directory", str(pack_dir), "--as-of", AS_OF)
    assert answer.status == 1
    assert answer.error["kind"] == "path"
    assert "regular file" in answer.error["message"]


@pytest.mark.parametrize(
    "as_of",
    ["2026-08-30", "2026-08-30T09:00:12+00:00", "2026-13-40T09:00:12Z", "now", ""],
    ids=["a date", "another offset", "not a calendar instant", "a word", "nothing"],
)
def test_an_instant_that_is_not_one_is_a_usage_refusal(invoke, pack_dir, as_of):
    """Held before anything is opened, so exit 2 means nothing was read."""
    answer = invoke("pack", "verify", "--directory", str(pack_dir), "--as-of", as_of)
    assert answer.status == 2
    assert answer.error["kind"] == "usage"


## Recording a run.


def test_record_writes_one_run_and_says_it_created_it(invoke, store_path, pack_dir, input_file):
    answer = record(invoke, store_path, pack_dir, input_file)
    result = answer.result
    assert result["created"] is True
    assert result["trace_id"] == trace_runs.TRACE_ID
    assert result["run"] == ids.mint_trace("run", trace_runs.TRACE_ID)
    assert result["outcome"] == "succeeded"
    assert result["counts"] == {"spans": 2, "metrics": 2, "findings": 2}
    with TraceStore.open(store_path) as store:
        assert store.trace_ids() == (trace_runs.TRACE_ID,)
        assert store.read(trace_runs.TRACE_ID).pack.identity == result["pack"]["identity"]


def test_the_same_run_again_is_a_replay_and_writes_nothing(
    invoke, store_path, pack_dir, input_file
):
    record(invoke, store_path, pack_dir, input_file)
    before = store_path.read_bytes()
    answer = record(invoke, store_path, pack_dir, input_file)
    assert answer.result["created"] is False
    assert answer.result["run"] == ids.mint_trace("run", trace_runs.TRACE_ID)
    assert store_path.read_bytes() == before


def test_a_different_run_under_a_recorded_id_is_refused(invoke, store_path, pack_dir, input_file):
    record(invoke, store_path, pack_dir, input_file)
    differing = replace(trace_runs.run(), metrics=[Metric("branches-read", 9, "count")])
    answer = record(invoke, store_path, pack_dir, input_file, run=differing)
    assert answer.status == 1
    assert answer.error["kind"] == "trace"
    with TraceStore.open(store_path) as store:
        assert store.read(trace_runs.TRACE_ID).run.metrics == trace_runs.run().metrics


def test_a_replay_of_an_expired_run_is_refused(invoke, store_path, pack_dir, input_file):
    record(invoke, store_path, pack_dir, input_file)
    invoke("trace", "expire", "--store", str(store_path), "--as-of", LONG_AFTER)
    answer = record(invoke, store_path, pack_dir, input_file)
    assert answer.status == 1
    assert answer.error["kind"] == "trace"


def test_a_run_the_model_refuses_records_nothing(invoke, store_path, pack_dir, input_file):
    """A refused run leaves an empty store rather than a partial one.

    Recording is the one command that may create a store, and it creates it on opening -
    before the run is validated. So what is guaranteed here is that nothing was recorded,
    which is the guarantee that matters: a caller reading this store back finds no run,
    not half of one.
    """
    cycle = trace_runs.with_spans(
        trace_runs.span(parent_span_id=trace_runs.CHILD_SPAN),
        trace_runs.span(trace_runs.CHILD_SPAN, parent_span_id=trace_runs.ROOT_SPAN),
    )
    answer = record(invoke, store_path, pack_dir, input_file, run=cycle)
    assert answer.status == 1
    assert answer.error["kind"] == "trace"
    assert _recorded(store_path) == ()


def test_a_pack_that_does_not_verify_records_nothing(invoke, store_path, pack_dir, input_file):
    path = pack_dir / packs.CONTENT_NAME
    path.write_bytes(path.read_bytes().replace(b"vvonkledge", b"someoneelse"))
    answer = record(invoke, store_path, pack_dir, input_file)
    assert answer.status == 1
    assert answer.error["kind"] == "pack"
    assert _recorded(store_path) == ()


def _recorded(store_path) -> tuple:
    with TraceStore.open(store_path) as store:
        return store.trace_ids()


def test_a_run_read_from_standard_input(invoke, store_path, pack_dir, tmp_path, monkeypatch):
    """``-`` is how a caller pipes a run in without writing it to disk first."""
    piped = tmp_path / "piped.json"
    piped.write_bytes(json.dumps(document(trace_runs.run())).encode())
    with open(piped, "rb") as stream:
        monkeypatch.setattr(sys, "stdin", stream)
        answer = invoke(
            "trace",
            "record",
            "--store",
            str(store_path),
            "--pack",
            str(pack_dir),
            "--as-of",
            AS_OF,
            "--input",
            "-",
        )
    assert answer.result["created"] is True


def test_a_second_process_cannot_write_a_different_run_under_one_id(
    invoke, store_path, pack_dir, input_file
):
    """The primary key is what makes this safe, and losing it must not be a traceback.

    Two writers that both saw nothing recorded is the case a pre-check cannot answer.
    The one that loses the insert has written nothing - the transaction rolls back
    whole - and what it is holding is then held against the rows that did land.
    """
    differing = replace(trace_runs.run(), outcome="failed")
    with TraceStore.open(store_path) as store:
        store.record(
            trace_runs.run(),
            pack=packs.read(packs.pack_dir()),
            as_of=AS_OF,
            expect_target=TARGET,
        )
    answer = record(invoke, store_path, pack_dir, input_file, run=differing)
    assert answer.status == 1
    assert answer.error["kind"] == "trace"
    with TraceStore.open(store_path) as store:
        assert store.read(trace_runs.TRACE_ID).run.outcome == "succeeded"


def test_a_locked_store_is_refused_rather_than_raised(
    invoke, store_path, pack_dir, input_file, monkeypatch
):
    """A store another process is writing to fails closed, as a named refusal.

    The store waits out SQLite's default busy timeout before it gives up, which is five
    seconds this suite has no reason to spend: what is under test is what happens when
    the wait ends, not how long it is. So the connection this command opens waits for a
    moment instead. The lock, the failure and the refusal are all real.
    """
    record(invoke, store_path, pack_dir, input_file)
    holder = sqlite3.connect(store_path, isolation_level=None)
    connect = sqlite3.connect
    monkeypatch.setattr(
        sqlite3, "connect", lambda *args, **named: connect(*args, timeout=0.05, **named)
    )
    try:
        holder.execute("BEGIN EXCLUSIVE")
        holder.execute("PRAGMA user_version")
        answer = invoke("trace", "expire", "--store", str(store_path), "--as-of", LONG_AFTER)
    finally:
        holder.close()
    assert answer.status == 1
    assert answer.error["kind"] == "store"


def test_a_store_that_is_not_a_database_is_refused_rather_than_raised(invoke, store_path):
    """Malformed is refused as a named store failure, not as a traceback out of SQLite."""
    store_path.write_bytes(b"this was never a database\n")
    answer = invoke("trace", "get", "--store", str(store_path), "--trace-id", trace_runs.TRACE_ID)
    assert answer.status == 1
    assert answer.error["kind"] == "store"


## Reading, projecting and expiring.


def test_get_returns_the_run_as_it_was_recorded(invoke, store_path, pack_dir, input_file):
    record(invoke, store_path, pack_dir, input_file)
    answer = invoke("trace", "get", "--store", str(store_path), "--trace-id", trace_runs.TRACE_ID)
    run = answer.result["run"]
    original = trace_runs.run()
    assert run["trace_id"] == original.trace_id
    assert run["outcome"] == original.outcome
    assert run["agent"] == original.agent
    assert [span["span_id"] for span in run["spans"]] == [span.span_id for span in original.spans]
    assert run["spans"][1]["touched"] == [trace_runs.REPOSITORY]
    assert run["spans"][1]["parent_span_id"] == trace_runs.ROOT_SPAN
    assert {metric["name"]: metric["value"] for metric in run["metrics"]} == {
        "branches-read": 2,
        "pack-bytes": 7911,
    }
    assert [finding["code"] for finding in run["findings"]] == ["branch-moved", "pack-nearly-stale"]
    assert answer.result["span_detail_expired_at"] is None
    assert answer.result["pack"]["target"] == TARGET


def test_get_after_expiry_says_the_detail_went(invoke, store_path, pack_dir, input_file):
    record(invoke, store_path, pack_dir, input_file)
    invoke("trace", "expire", "--store", str(store_path), "--as-of", LONG_AFTER)
    answer = invoke("trace", "get", "--store", str(store_path), "--trace-id", trace_runs.TRACE_ID)
    assert answer.result["run"]["spans"] == []
    assert answer.result["span_detail_expired_at"] == "2026-09-02T00:00:00Z"
    # Everything a run is judged by afterwards is still there.
    assert len(answer.result["run"]["metrics"]) == 2
    assert len(answer.result["run"]["findings"]) == 2
    assert answer.result["pack"]["identity"]


def test_get_refuses_a_run_that_is_not_recorded(invoke, store_path, pack_dir, input_file):
    record(invoke, store_path, pack_dir, input_file)
    answer = invoke("trace", "get", "--store", str(store_path), "--trace-id", "0" * 32)
    assert answer.status == 1
    assert answer.error["kind"] == "trace"


def test_project_is_deterministic_and_survives_expiry(invoke, store_path, pack_dir, input_file):
    record(invoke, store_path, pack_dir, input_file)
    argv = ("trace", "project", "--store", str(store_path), "--trace-id", trace_runs.TRACE_ID)
    first, second = invoke(*argv), invoke(*argv)
    assert first.text == second.text
    summary = first.result["summary"]
    assert summary["media_type"] == "application/n-triples"
    assert summary["triples"] == summary["text"].count("\n")
    from semantic_layer.github import digest_of

    assert summary["digest"] == digest_of(summary["text"].encode("utf-8"))
    assert first.result["run"] == ids.mint_trace("run", trace_runs.TRACE_ID)

    invoke("trace", "expire", "--store", str(store_path), "--as-of", LONG_AFTER)
    after = invoke(*argv)
    assert after.result["summary"]["text"] != summary["text"]
    assert "spanDetailExpiredAt" in after.result["summary"]["text"]
    assert after.text == invoke(*argv).text


def test_expire_holds_the_boundary_and_is_safe_to_run_again(
    invoke, store_path, pack_dir, input_file
):
    """Strictly before the horizon, from the caller's instant and never from the clock."""
    record(invoke, store_path, pack_dir, input_file)
    argv = ("trace", "expire", "--store", str(store_path), "--as-of")
    # The run ended at 2026-08-30T09:00:12Z, so ninety days on is the first instant that
    # puts the horizon past it.
    at_the_boundary = invoke(*argv, "2026-11-28T09:00:12Z")
    assert at_the_boundary.result["horizon"] == "2026-08-30T09:00:12Z"
    assert at_the_boundary.result["expired"] == []
    just_after = invoke(*argv, "2026-11-28T09:00:13Z")
    assert just_after.result["expired"] == [trace_runs.TRACE_ID]
    assert just_after.result["retention_days"] == 90
    assert invoke(*argv, LONG_AFTER).result["expired"] == []


def test_expire_leaves_the_rollups_alone(invoke, store_path, pack_dir, input_file):
    record(invoke, store_path, pack_dir, input_file)
    invoke("trace", "expire", "--store", str(store_path), "--as-of", LONG_AFTER)
    answer = invoke("trace", "get", "--store", str(store_path), "--trace-id", trace_runs.TRACE_ID)
    assert answer.result["run"]["outcome"] == "succeeded"
    assert answer.result["run"]["metrics"]
    assert answer.result["run"]["findings"]


## Where the store may be, and where it may not.


def test_an_in_memory_store_is_refused(invoke):
    """It is what the suite opens and exactly wrong here: the process outlives nothing."""
    answer = invoke("trace", "get", "--store", ":memory:", "--trace-id", trace_runs.TRACE_ID)
    assert answer.status == 2
    assert answer.error["kind"] == "usage"


@pytest.mark.parametrize("command", ["get", "project"])
def test_reading_refuses_a_store_that_is_not_there(invoke, tmp_path, command):
    """SQLite would create one, and the answer would be a truthful, useless no."""
    missing = tmp_path / "nowhere.sqlite3"
    answer = invoke("trace", command, "--store", str(missing), "--trace-id", trace_runs.TRACE_ID)
    assert answer.status == 1
    assert answer.error["kind"] == "path"
    assert not missing.exists()


def test_expiring_refuses_a_store_that_is_not_there(invoke, tmp_path):
    missing = tmp_path / "nowhere.sqlite3"
    answer = invoke("trace", "expire", "--store", str(missing), "--as-of", LONG_AFTER)
    assert answer.status == 1
    assert not missing.exists()


def test_a_directory_named_as_a_store_is_refused(invoke, tmp_path):
    (tmp_path / "store").mkdir()
    answer = invoke(
        "trace", "get", "--store", str(tmp_path / "store"), "--trace-id", trace_runs.TRACE_ID
    )
    assert answer.status == 1
    assert answer.error["kind"] == "path"


def test_recording_into_a_tree_that_is_not_there_is_refused(invoke, tmp_path, pack_dir, input_file):
    """Recording creates the store file and never the directories above it."""
    answer = record(invoke, tmp_path / "absent" / "trace.sqlite3", pack_dir, input_file)
    assert answer.status == 1
    assert answer.error["kind"] == "path"


def test_a_store_at_another_schema_version_is_refused(invoke, store_path, pack_dir, input_file):
    record(invoke, store_path, pack_dir, input_file)
    connection = sqlite3.connect(store_path, isolation_level=None)
    connection.execute("PRAGMA user_version = 99")
    connection.close()
    answer = invoke("trace", "get", "--store", str(store_path), "--trace-id", trace_runs.TRACE_ID)
    assert answer.status == 1
    assert answer.error["kind"] == "trace"


def test_an_input_that_is_not_a_regular_file_is_refused(invoke, store_path, pack_dir, tmp_path):
    """A pipe read twice is two documents, and this command records what it read."""
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    answer = invoke(
        "trace",
        "record",
        "--store",
        str(store_path),
        "--pack",
        str(pack_dir),
        "--as-of",
        AS_OF,
        "--input",
        str(fifo),
    )
    assert answer.status == 1
    assert answer.error["kind"] == "path"
    assert "regular file" in answer.error["message"]


def test_an_input_longer_than_this_command_reads_is_refused(
    invoke, store_path, pack_dir, tmp_path, monkeypatch
):
    monkeypatch.setattr(files, "MAX_BYTES", 64)
    oversized = tmp_path / "big.json"
    oversized.write_bytes(json.dumps(document(trace_runs.run())).encode())
    answer = invoke(
        "trace",
        "record",
        "--store",
        str(store_path),
        "--pack",
        str(pack_dir),
        "--as-of",
        AS_OF,
        "--input",
        str(oversized),
    )
    assert answer.status == 1
    assert answer.error["kind"] == "path"
    assert _recorded(store_path) == ()


def test_a_measurement_wider_than_the_store_is_refused_as_a_document(
    invoke, store_path, pack_dir, input_file
):
    """A number with no width in Python and sixty-four bits in the column that records it.

    Left to SQLite it is an ``OverflowError`` raised from inside the write, which is in
    none of the families this boundary turns into a refusal - so the command exited with
    a stack trace on the stream it promises to leave empty and nothing on stdout. The
    bound lives with the model's other store bounds; here is what a consumer sees.
    """
    from semantic_layer.trace.model import METRIC_VALUE_MAX

    oversized = Metric("branches-read", METRIC_VALUE_MAX + 1, "count")
    wide = replace(trace_runs.run(), metrics=[oversized])
    answer = record(invoke, store_path, pack_dir, input_file, run=wide)
    assert answer.status == 1
    assert answer.error["kind"] == "trace"
    assert _recorded(store_path) == ()


def test_a_run_with_a_span_reference_the_layer_did_not_mint_is_refused(
    invoke, store_path, pack_dir, input_file
):
    """The model's bound on a reference, reached through the document rather than around it."""
    reaching = trace_runs.with_spans(
        trace_runs.span(touched=["https://example.com/whatever"]),
    )
    answer = record(invoke, store_path, pack_dir, input_file, run=reaching)
    assert answer.status == 1
    assert answer.error["kind"] == "trace"
    assert _recorded(store_path) == ()


def test_the_recorded_run_is_the_one_the_document_described(
    invoke, store_path, pack_dir, input_file
):
    """One run through the whole boundary and back, compared against the model's own."""
    original = replace(trace_runs.run(), spans=[trace_runs.span()], metrics=[], findings=[])
    record(invoke, store_path, pack_dir, input_file, run=original)
    answer = invoke("trace", "get", "--store", str(store_path), "--trace-id", trace_runs.TRACE_ID)
    read = answer.result["run"]
    assert read["spans"] == [
        {
            "span_id": trace_runs.ROOT_SPAN,
            "parent_span_id": None,
            "operation": "verify-pack",
            "kind": "internal",
            "status": "ok",
            "started_at": "2026-08-30T09:00:00Z",
            "ended_at": "2026-08-30T09:00:02Z",
            "touched": [],
        }
    ]
    assert read["metrics"] == [] and read["findings"] == []
