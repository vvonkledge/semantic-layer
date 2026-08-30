"""The process boundary: what a consumer of this layer runs, and never imports.

Everything else in this package is a library, and a library is the wrong shape for the
consumer this exists for. SIANA verifies a context pack before it dispatches work and
records what came of it afterwards, and it is a separate project with its own release
cadence, its own dependencies and no business knowing that a manifest is JSON, that a
summary is N-Triples, or that spans are rows in SQLite. Coupled through an import, every
one of those becomes something that cannot be changed here without breaking something
there. Coupled through a command, none of them is visible at all.

So this is the whole seam, and it is deliberately narrow:

    semantic-layer pack verify   --directory DIR --as-of INSTANT
                                 [--expect-source IRI] [--expect-target TARGET]
    semantic-layer pack export   --directory DIR --as-of INSTANT
                                 [--expect-source IRI] [--expect-target TARGET]
    semantic-layer trace record  --store FILE --pack DIR --as-of INSTANT
                                 [--expect-source IRI] [--expect-target TARGET]
                                 --input FILE|-
    semantic-layer trace get     --store FILE --trace-id HEX
    semantic-layer trace project --store FILE --trace-id HEX
    semantic-layer trace expire  --store FILE --as-of INSTANT

Four things hold across all six, and each is a promise a consumer builds on:

**One JSON document, and no prose.** Every invocation that is not ``--help`` writes one
document to stdout and nothing to stderr, on success and refusal alike, naming its own
layout first. See ``semantic_layer.cli.response`` for the document and the exit codes.

**Nothing is inferred.** The instant, the store, the pack and the expectations are all
the caller's, stated on the command line every time. No environment variable is read, no
configuration file is looked for, and no home directory is guessed at. A command that
found a store by itself would write evidence somewhere its caller never asked for; one
that read the clock would answer a different question every time it ran, which is the
rule ``pack.verify`` and ``expire_spans`` were built around and is not weakened here.

**Nothing is reimplemented.** The pack is checked by ``semantic_layer.pack.verify``, the
run is held by ``semantic_layer.trace.model``, the write is
``semantic_layer.trace.store``, and the summary is the real projection serialized by the
real serializer. This module converts, dispatches and renders. A second implementation
of any of those would be a second answer to a question that has one.

**There is still no service.** This starts nothing, listens on nothing, schedules
nothing and reaches the network from nowhere. It is a process that runs, answers, and
exits, against files its caller named.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections.abc import Sequence
from datetime import datetime

from semantic_layer import github, ids, serialize
from semantic_layer import pack as packs
from semantic_layer.cli import files, run_input
from semantic_layer.cli.response import OK, CommandError, answered, refused, render
from semantic_layer.trace import (
    RETENTION_DAYS,
    PackBinding,
    Run,
    TraceError,
    TraceStore,
    retention_horizon,
)
from semantic_layer.trace.model import TRACE_ID_PATTERN
from semantic_layer.trace.store import RunRecord, binding_of

#: How canonical N-Triples is named to a consumer that has been handed some. A context
#: pack's content and a projected trace summary are both written by
#: ``semantic_layer.serialize.ntriples``, so they are one encoding and are named by one
#: constant rather than by two that could come to disagree.
NTRIPLES = packs.CONTENT_MEDIA_TYPE

#: Which refusal kind each error this command can be handed is reported as, in the order
#: they are tried. The library raises what it already raises - a pack refusal, a trace
#: refusal, an operating system error, a database error - and this is the one place each
#: is turned into something a consumer can branch on. Nothing is caught more widely than
#: this: a failure that is not on this list is this code's own bug, and a traceback is
#: the honest report of one.
KIND_BY_ERROR = (
    (packs.PackError, "pack"),
    (TraceError, "trace"),
    (ids.IdentifierError, "trace"),
    (sqlite3.Error, "store"),
    (OSError, "path"),
)

_REFUSALS = tuple(error for error, _ in KIND_BY_ERROR)


class _Parser(argparse.ArgumentParser):
    """An argument parser that refuses into the response document rather than to stderr.

    argparse writes a usage message to stderr and exits, which is right for a command a
    person is typing and wrong for one a program is running: the caller would get an
    exit code, an empty stdout it was told always holds a document, and a sentence in a
    stream it does not read. ``--help`` keeps argparse's own behaviour, because that is
    the one invocation whose reader is a person.
    """

    def error(self, message: str):
        raise CommandError("usage", f"{message}. Run `{self.prog} --help` for what it takes.")


def _expectations(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--expect-source",
        metavar="IRI",
        default=None,
        help="refuse a pack that is not from this source; an identifier means nothing "
        "outside the source that issued it",
    )
    parser.add_argument(
        "--expect-target",
        metavar="TARGET",
        default=None,
        help="refuse a pack that is not about this target, in the source's own terms",
    )


def _as_of(parser: argparse.ArgumentParser, what: str) -> None:
    parser.add_argument(
        "--as-of",
        required=True,
        metavar="INSTANT",
        help=f"the caller's own instant, spelled YYYY-MM-DDTHH:MM:SSZ, {what}",
    )


def _store(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--store",
        required=True,
        metavar="FILE",
        help="the SQLite trace store to use; always stated, never inferred",
    )


def _trace_id(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--trace-id",
        required=True,
        metavar="HEX",
        help="the run's OpenTelemetry trace id: 32 lower-case hex characters",
    )


def _grammar() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="semantic-layer",
        description="Verify a context pack, and record what a run did with one.",
    )
    groups = parser.add_subparsers(dest="group", required=True, metavar="GROUP")

    pack = groups.add_parser("pack", help="context packs: verify one, or verify and export one")
    actions = pack.add_subparsers(dest="action", required=True, metavar="ACTION")
    for name, what in (
        ("verify", "report what a pack binds to, without returning it"),
        ("export", "verify a pack and return the exact bytes that verified"),
    ):
        command = actions.add_parser(name, help=what)
        command.add_argument(
            "--directory",
            required=True,
            metavar="DIR",
            help=f"the directory holding {packs.CONTENT_NAME} and {packs.MANIFEST_NAME}",
        )
        _as_of(command, "which the pack must still be fresh at")
        _expectations(command)

    trace = groups.add_parser("trace", help="recorded runs: record, read, project, expire")
    actions = trace.add_subparsers(dest="action", required=True, metavar="ACTION")

    record = actions.add_parser("record", help="record one whole run against a verified pack")
    _store(record)
    record.add_argument(
        "--pack",
        required=True,
        metavar="DIR",
        help="the pack the run was handed, verified here before anything is written",
    )
    _as_of(record, "which the pack must still be fresh at")
    _expectations(record)
    record.add_argument(
        "--input",
        required=True,
        metavar="FILE",
        help="the run as JSON, or - to read it from standard input; see docs/cli.md",
    )

    get = actions.add_parser("get", help="one recorded run, as the store holds it now")
    _store(get)
    _trace_id(get)

    project = actions.add_parser("project", help="the PROV-O summary of one recorded run")
    _store(project)
    _trace_id(project)

    expire = actions.add_parser("expire", help="remove span detail past the retention window")
    _store(expire)
    _as_of(expire, f"the window of {RETENTION_DAYS} days is measured back from")
    return parser


def _instant(value: str) -> str:
    """The caller's instant, held to the one spelling this repository writes."""
    if not github.INSTANT_PATTERN.fullmatch(value):
        raise CommandError(
            "usage",
            f"--as-of is {value!r}, which is not a UTC instant spelled YYYY-MM-DDTHH:MM:SSZ. "
            f"One spelling and one timezone, because every instant this layer compares is "
            f"compared as text.",
        )
    try:
        datetime.strptime(value, github.INSTANT_FORMAT)
    except ValueError as error:
        raise CommandError(
            "usage", f"--as-of is {value!r}, which is spelled like an instant but is not one."
        ) from error
    return value


def _held(arguments: argparse.Namespace) -> None:
    """Every option's value held to its stated shape, before anything at all is opened.

    These are the checks that belong to the grammar rather than to the data: a value
    argparse accepted as text but that this contract says is an instant or a trace id.
    Doing them here rather than where the value is first used is what makes exit 2 mean
    "nothing was read", so a caller that got one knows no store was touched.
    """
    if getattr(arguments, "as_of", None) is not None:
        arguments.as_of = _instant(arguments.as_of)
    trace_id = getattr(arguments, "trace_id", None)
    if trace_id is not None and not TRACE_ID_PATTERN.fullmatch(trace_id):
        raise CommandError(
            "usage",
            f"--trace-id is {trace_id!r}, which is not 32 lower-case hex characters. An "
            f"abbreviated or re-cased identifier names no run the tracer emitted.",
        )


## Reporting: the library's own records, as the document a consumer reads.


def _binding(binding: PackBinding) -> dict:
    """The pack a run was recorded against, exactly as the store holds it."""
    return {
        "identity": binding.identity,
        "content_digest": binding.content_digest,
        "manifest_digest": binding.manifest_digest,
        "observation": binding.observation,
        "source": binding.source,
        "target": binding.target,
    }


def _verified(pack: packs.Pack, manifest) -> dict:
    """What verification found: the binding, plus the manifest fields it held.

    The byte counts are counted here rather than read off the manifest, even though
    verification has already held the manifest's own count against the content. A
    consumer reading this document is being told what these bytes are, and every number
    in it that can be derived from them is.
    """
    return {
        **_binding(binding_of(pack, manifest)),
        "observed_at": manifest["observed_at"],
        "fresh_until": manifest["fresh_until"],
        "artifact_count": manifest["artifact_count"],
        "content_bytes": len(pack.content),
        "manifest_bytes": len(pack.manifest),
        "content_media_type": manifest["content_media_type"],
        "vocabulary_version": manifest["vocabulary_version"],
        "graph": manifest["graph"],
    }


def _run(run: Run) -> dict:
    return {
        "iri": ids.mint_trace("run", run.trace_id),
        "trace_id": run.trace_id,
        "started_at": run.started_at,
        "ended_at": run.ended_at,
        "outcome": run.outcome,
        "agent": run.agent,
        "spans": [
            {
                "span_id": span.span_id,
                "parent_span_id": span.parent_span_id,
                "operation": span.operation,
                "kind": span.kind,
                "status": span.status,
                "started_at": span.started_at,
                "ended_at": span.ended_at,
                "touched": list(span.touched),
            }
            for span in run.spans
        ],
        "metrics": [
            {"name": metric.name, "value": metric.value, "unit": metric.unit}
            for metric in run.metrics
        ],
        "findings": [
            {"code": finding.code, "severity": finding.severity, "about": finding.about}
            for finding in run.findings
        ],
    }


def _record(record: RunRecord) -> dict:
    return {
        "run": _run(record.run),
        "pack": _binding(record.pack),
        "span_detail_expired_at": record.span_detail_expired_at,
    }


## The commands.


def _verify(pack: packs.Pack, arguments: argparse.Namespace):
    return packs.verify(
        pack.content,
        pack.manifest,
        as_of=arguments.as_of,
        expect_source=arguments.expect_source,
        expect_target=arguments.expect_target,
    )


def pack_verify(arguments: argparse.Namespace) -> dict:
    """Read both halves once, and report what the real verifier made of them."""
    pack = files.read_pack(arguments.directory)
    return {"as_of": arguments.as_of, "pack": _verified(pack, _verify(pack, arguments))}


def pack_export(arguments: argparse.Namespace) -> dict:
    """The same, returning the exact bytes that verified.

    The bytes handed back are the ones that were hashed, held against the manifest and
    parsed - the same values, never the path read a second time. That is the whole point
    of exporting through this command rather than telling a consumer to open the files
    itself: what it is given and what was checked cannot come apart.
    """
    pack = files.read_pack(arguments.directory)
    manifest = _verify(pack, arguments)
    return {
        "as_of": arguments.as_of,
        "pack": _verified(pack, manifest),
        "content": _exported(pack.content, "content"),
        "manifest": _exported(pack.manifest, "manifest"),
    }


def _exported(half: bytes, name: str) -> dict:
    """One verified half, as text a JSON document can carry without losing a byte.

    JSON has no bytes, so the encoding is stated rather than assumed. Both halves are
    UTF-8 by the time they get here in every case this reader accepts one - the content
    parsed as N-Triples and the manifest parsed as JSON - but "in every case that
    verified" is a claim about rdflib and the json module rather than about these bytes,
    so it is checked here and refused rather than exported lossily.
    """
    try:
        return {"encoding": "utf-8", "text": half.decode("utf-8")}
    except UnicodeDecodeError as error:
        raise CommandError(
            "pack",
            f"the pack {name} verified but is not UTF-8: {error}. It cannot be returned as "
            f"text without changing it, and this command returns exactly what it verified.",
        ) from error


def _opened(arguments: argparse.Namespace, *, creating: bool = False) -> TraceStore:
    return TraceStore.open(files.store_file(arguments.store, creating=creating))


def trace_record(arguments: argparse.Namespace) -> dict:
    """One whole run, against a pack verified here, or nothing at all.

    The write is the store's one transaction: it lands whole or leaves nothing, and it
    says whether it was this call that wrote it. What is guaranteed on a refusal is that
    no run is recorded, not that no file exists - this is the one command that may create
    a store, and it creates it on opening, before the run is validated and the pack is
    verified. A refused record therefore leaves an empty store behind where there was
    none, holding no rows at all. Refusing later than that would mean checking the run
    and the pack twice, once out here and once where the write happens, and two places
    that decide whether a run may be recorded is the thing this boundary is built not to
    have.
    """
    path = files.store_file(arguments.store, creating=True)
    run = run_input.decode(files.read_input(arguments.input))
    pack = files.read_pack(arguments.pack)
    with TraceStore.open(path) as store:
        recorded = store.write(
            run,
            pack=pack,
            as_of=arguments.as_of,
            expect_source=arguments.expect_source,
            expect_target=arguments.expect_target,
        )
    return {
        "run": recorded.run,
        "trace_id": recorded.trace_id,
        "created": recorded.created,
        "outcome": run.outcome,
        "counts": {
            "spans": len(run.spans),
            "metrics": len(run.metrics),
            "findings": len(run.findings),
        },
        "pack": _binding(recorded.pack),
    }


def trace_get(arguments: argparse.Namespace) -> dict:
    """One recorded run as the store holds it now, spans included while they are there."""
    with _opened(arguments) as store:
        return _record(store.read(arguments.trace_id))


def trace_project(arguments: argparse.Namespace) -> dict:
    """The PROV-O summary, as the canonical N-Triples a consumer can hash and compare.

    The digest is over the same text this document carries, so a consumer that wants to
    store the summary and prove later that it stored this one has both halves without
    having to serialize anything itself.
    """
    with _opened(arguments) as store:
        summary = store.summary(arguments.trace_id)
    text = serialize.ntriples(summary)
    return {
        "trace_id": arguments.trace_id,
        "run": ids.mint_trace("run", arguments.trace_id),
        "summary": {
            "media_type": NTRIPLES,
            "digest": github.digest_of(text.encode("utf-8")),
            "triples": len(summary),
            "text": text,
        },
    }


def trace_expire(arguments: argparse.Namespace) -> dict:
    """The retention pass, against the caller's instant, saying exactly what it removed."""
    with _opened(arguments) as store:
        expired = store.expire_spans(as_of=arguments.as_of)
    return {
        "as_of": arguments.as_of,
        "horizon": retention_horizon(arguments.as_of),
        "retention_days": RETENTION_DAYS,
        "expired": list(expired),
    }


#: The six commands, by the name the response document reports them under.
COMMANDS = {
    "pack verify": pack_verify,
    "pack export": pack_export,
    "trace record": trace_record,
    "trace get": trace_get,
    "trace project": trace_project,
    "trace expire": trace_expire,
}


def main(argv: Sequence[str] | None = None) -> int:
    """Run one command, write one document, and return the code that says which."""
    command = None
    try:
        arguments = _grammar().parse_args(argv)
        command = f"{arguments.group} {arguments.action}"
        _held(arguments)
        document = answered(command, COMMANDS[command](arguments))
        status = OK
    except CommandError as error:
        document, status = refused(command, error), error.status
    except _REFUSALS as error:
        kind = next(kind for family, kind in KIND_BY_ERROR if isinstance(error, family))
        refusal = CommandError(kind, str(error))
        document, status = refused(command, refusal), refusal.status
    sys.stdout.write(render(document))
    return status
