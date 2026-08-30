# The command: one process boundary, and what a consumer pins

Everything else in this repository is files and a library. This is the one thing another
project runs.

The consumer it exists for is SIANA: it verifies a context pack before it dispatches
work, and records what came of the run afterwards. Neither of those needs to know that a
manifest is JSON, that a summary is N-Triples, or that spans are rows in SQLite - and
every one of those becomes a thing that cannot change here the moment it is coupled
through an import. So the seam is a command, its response names its own layout, and the
internals are none of the caller's business.

```sh
uv tool install semantic-layer      # or pip install, into whatever runs the consumer
semantic-layer --help
```

Two versions matter and they are not the same number. The package version
(`pyproject.toml`) is the implementation. The **response version** below is the
contract, and it is what a consumer pins: it changes when the shape of what this
command says changes, and not when the code behind it does.

## The response

Every invocation that is not `--help` writes exactly one JSON document to standard
output and **nothing at all to standard error**, on success and on refusal alike.

```json
{
  "schema": "https://semantic-layer.19h09.co/cli/response",
  "version": 1,
  "command": "pack verify",
  "status": "ok",
  "result": { }
}
```

```json
{
  "schema": "https://semantic-layer.19h09.co/cli/response",
  "version": 1,
  "command": "trace get",
  "status": "error",
  "error": { "kind": "path", "message": "there is no store at /tmp/nowhere.sqlite3. ..." }
}
```

Check `schema` and `version` before reading anything else. A consumer written against
version 1 must refuse a version 2 document rather than reading the fields it recognizes
out of it and guessing about the rest - the same rule a context pack manifest follows,
for the same reason: a layout that is unstated is one a reader believes field by field.

`command` is the two words that were run, or `null` when the arguments did not resolve
to a command at all. `status` is `ok` or `error`. Exactly one of `result` and `error` is
present.

The document is deterministic: sorted keys, two-space indent, one trailing newline, and
ASCII with every other character JSON-escaped. Two invocations that answer the same
question write the same bytes, so a response can be hashed, diffed, or committed as a
fixture. It is escaped rather than written as UTF-8 because standard output is encoded
by the caller's locale, and a consumer running from a container, a daemon or a cron
entry commonly has none: a repository name with an accent in it would otherwise raise on
the way out, having verified everything and answered nothing. Every JSON reader
unescapes it, so nothing is lost.

### Exit codes

| code | meaning |
|---|---|
| `0` | a complete answer; `result` is present |
| `1` | the call was understood and the answer is no |
| `2` | the call is not one this contract defines |

The line between `1` and `2` is where the fault is, not how serious it is. **Exit 2 says
the caller's own code is wrong** and no input would have helped: the grammar did not
parse, an option's value is not the shape stated for it, or the input document's layout
is not one this reader understands. **Exit 1 says the call was right and the data or the
state refused it.**

Neither exit-2 kind writes anything, and they differ in what they had to read to get
there. A `usage` refusal happens before anything at all is opened, because the
arguments are held to their stated shapes before any command runs. An `input` refusal
happens after the document was opened and read - reading it is how its layout is known -
but before any store is opened, so a refused `trace record` leaves no store file where
there was none.

`error.kind` is closed, and each kind carries exactly one exit code:

| kind | exit | what it means |
|---|---|---|
| `usage` | 2 | the arguments, or an option's value, are not what the grammar defines |
| `input` | 2 | the run document's layout is not the one published below |
| `pack` | 1 | a pack is stale, tampered with, unreadable, or about something else |
| `trace` | 1 | this layer will not record, or does not hold, that run |
| `path` | 1 | a file is missing, is not a regular file, or cannot be read |
| `store` | 1 | the store is locked, corrupt, or written by another schema version |

`trace` and `store` are the pair worth telling apart. `trace` is this store declining to
answer one question - no such run, a replay that differs, a run it will not record - and
the file is fine to go on using. `store` is the file itself: locked, not a database, or
written by a schema version this does not read, and it must not be used again.

Branch on `kind` or on the exit code; they cannot disagree.

`--help` is the one documented exception to all of this. It writes a usage message - to
standard output - and exits `0`, because its reader is a person.

## The commands

```
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
```

`INSTANT` is always `YYYY-MM-DDTHH:MM:SSZ`. `HEX` is 32 lower-case hex characters, the
OpenTelemetry trace id. `DIR` for a pack is the directory holding `content.nt` and
`manifest.json`.

### `pack verify`

Reads both halves of the pack **once**, hands those bytes to
`semantic_layer.pack.verify` - the real verifier, the same one any consumer of a pack
would run - and reports what they bind to.

```json
"result": {
  "as_of": "2026-08-30T09:00:12Z",
  "pack": {
    "identity": "e830ad25f822b1cd37207ba0987d50506b2fe399059b2315bc056a5118d8992e",
    "content_digest": "sha256:69eeccc5...",
    "manifest_digest": "sha256:ea95446f...",
    "observation": "https://semantic-layer.19h09.co/l2/github/api-github-com/observation/8ff2a001...",
    "source": "https://semantic-layer.19h09.co/l2/github/api-github-com",
    "target": "vvonkledge/siana",
    "observed_at": "2026-08-30T06:07:15Z",
    "fresh_until": "2026-08-31T06:07:15Z",
    "artifact_count": 3,
    "content_bytes": 7911,
    "manifest_bytes": 1183,
    "content_media_type": "application/n-triples",
    "vocabulary_version": "0.1.0",
    "graph": "https://semantic-layer.19h09.co/graph/l2-observed"
  }
}
```

`identity` is the name of the pack as L3 records it: a digest over the digests of both
halves. Both are hashed on purpose. Tampering with either is already refused by the
verifier, but a manifest re-rendered with the same fields in a different spelling
verifies happily and is **not the bytes this run was handed** - so it is a different
pack, and it gets a different identity.

`content_bytes` and `manifest_bytes` are counted from the bytes that were read, not
taken from the manifest that describes them.

### `pack export`

The same verification, returning the exact bytes that verified:

```json
"result": {
  "as_of": "...",
  "pack": { },
  "content":  { "encoding": "utf-8", "text": "<https://...> <...> ...\n" },
  "manifest": { "encoding": "utf-8", "text": "{\n  \"api_root\": ...\n}\n" }
}
```

**The bytes returned are the bytes that were hashed and checked.** Each half is read
exactly once, and verification, the digest and the exported text are all that one value;
nothing reopens the path afterwards. Re-encoding `content.text` as UTF-8 reproduces the
file byte for byte and hashes to `pack.content_digest`. A pack that does not verify
exports nothing at all - there is no partial answer.

If a half verified but is not UTF-8, the export is refused (`pack`) rather than returned
lossily.

### `trace record`

Reads the run document, converts it into the model's own records, reads the pack, and
writes the run in the store's one transaction.

```json
"result": {
  "run": "https://semantic-layer.19h09.co/l3/run/4bf92f3577b34da6a3ce929d0e0e4736",
  "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
  "created": true,
  "outcome": "succeeded",
  "counts": { "spans": 2, "metrics": 1, "findings": 1 },
  "pack": {
    "identity": "...", "content_digest": "...", "manifest_digest": "...",
    "observation": "...", "source": "...", "target": "..."
  }
}
```

`created` is the half a caller cannot work out for itself. Recording the same run twice
is a no-op that returns the same identifier, so a writer that retried after a timeout
has no way to know whether the first attempt landed - and asking beforehand does not
answer it either, because another process can record the same run in between. `created`
comes from the write: `true` means these rows were written, `false` means an identical
run was already there.

Refused, with nothing recorded:

- a run the model will not accept - a duplicate span id, a parent outside the run, a
  cycle, a reversed interval, a span outside its own run, a reference this layer did not
  mint, a name that is not a slug (`trace`);
- a pack that does not verify against `--as-of` and the expectations (`pack`);
- the **same trace id with different content** - two runs under one identifier is a
  record nobody can read apart again (`trace`);
- a **replay of a run whose span detail has expired** - writing the spans back would
  undo the removal (`trace`).

`trace record` is the one command that creates the store file if it is not there. It
creates it on opening, so a refused record leaves an *empty* store where there was none.
What is guaranteed is that no run was recorded, not that no file exists.

### `trace get`

The complete record, as the store holds it **now**.

```json
"result": {
  "run": {
    "iri": "https://semantic-layer.19h09.co/l3/run/4bf9...",
    "trace_id": "4bf9...", "started_at": "...", "ended_at": "...",
    "outcome": "succeeded", "agent": "https://semantic-layer.19h09.co/biz/agent/siana",
    "spans": [
      { "span_id": "00f067aa0ba902b7", "parent_span_id": null,
        "operation": "verify-pack", "kind": "internal", "status": "ok",
        "started_at": "...", "ended_at": "...", "touched": [] }
    ],
    "metrics":  [ { "name": "branches-read", "value": 2, "unit": "count" } ],
    "findings": [ { "code": "branch-moved", "severity": "warning", "about": null } ]
  },
  "pack": { },
  "span_detail_expired_at": null
}
```

`spans` is empty **only** when retention removed the detail, and then
`span_detail_expired_at` says when. It is recorded rather than inferred from the
emptiness, because a run is never written with no spans at all. Everything a run is
judged by afterwards - outcome, metrics, findings and the pack - is still there.

### `trace project`

The PROV-O summary of one run, as canonical N-Triples inside the document.

```json
"result": {
  "trace_id": "4bf9...",
  "run": "https://semantic-layer.19h09.co/l3/run/4bf9...",
  "summary": {
    "media_type": "application/n-triples",
    "digest": "sha256:12d763d7...",
    "triples": 63,
    "text": "<https://...> <...> <...> .\n..."
  }
}
```

The projection is a function of the record and nothing else, so two calls for one record
write byte-identical documents, and `digest` is over exactly the `text` beside it. It
stays valid after the span detail expires: the activities are gone and the run says when
they were removed. A consumer that speaks only PROV-O can read it having never been told
this vocabulary exists.

### `trace expire`

The retention pass, against the caller's instant.

```json
"result": {
  "as_of": "2026-12-01T00:00:00Z",
  "horizon": "2026-09-02T00:00:00Z",
  "retention_days": 90,
  "expired": ["4bf92f3577b34da6a3ce929d0e0e4736"]
}
```

`horizon` is `as_of` minus `retention_days`, and a run expires when it ended **strictly
before** it - so a run of exactly the retention age is kept. `expired` is exactly the
runs this pass removed span detail for, so a caller can say what happened rather than
infer it. Running it again with the same or a later instant removes nothing further and
returns an empty list.

It never consults the clock, never schedules itself, and never touches a rollup. See
[l3-execution-trace.md](l3-execution-trace.md) for what the ninety days are and are not.

## The run document

`trace record --input` takes one JSON document, closed and versioned:

```json
{
  "schema": "https://semantic-layer.19h09.co/cli/run",
  "version": 1,
  "run": {
    "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
    "started_at": "2026-08-30T09:00:00Z",
    "ended_at": "2026-08-30T09:00:12Z",
    "outcome": "succeeded",
    "agent": "https://semantic-layer.19h09.co/biz/agent/siana",
    "spans": [
      {
        "span_id": "00f067aa0ba902b7",
        "operation": "verify-pack",
        "kind": "internal",
        "status": "ok",
        "started_at": "2026-08-30T09:00:00Z",
        "ended_at": "2026-08-30T09:00:02Z"
      },
      {
        "span_id": "a2fb4a1d1a96d312",
        "operation": "read-branches",
        "kind": "client",
        "status": "ok",
        "started_at": "2026-08-30T09:00:02Z",
        "ended_at": "2026-08-30T09:00:11Z",
        "parent_span_id": "00f067aa0ba902b7",
        "touched": [
          "https://semantic-layer.19h09.co/l2/github/api-github-com/repository/1347717349"
        ]
      }
    ],
    "metrics":  [ { "name": "branches-read", "value": 2, "unit": "count" } ],
    "findings": [ { "code": "branch-moved", "severity": "warning" } ]
  }
}
```

The fields are exactly the fields of `Run`, `Span`, `Metric` and `Finding` in
`semantic_layer.trace.model`, and nothing else. A field may be left out only where the
model gives it a default: `agent`, `metrics` and `findings` on a run, `parent_span_id`
and `touched` on a span, `about` on a finding. Everything else is required, and a record
missing one is refused as partial.

| where | closed set |
|---|---|
| `outcome` | `succeeded`, `failed`, `blocked` |
| `kind` | `internal`, `server`, `client`, `producer`, `consumer` |
| `status` | `unset`, `ok`, `error` |
| `unit` | `count`, `millisecond`, `byte` |
| `severity` | `info`, `warning`, `error` |

`operation`, `name` and `code` are slugs - lower-case letters and digits joined by
single hyphens, at most 64 characters. `touched`, `about` and `agent` must be
identifiers this layer mints (see [identifiers.md](identifiers.md)), each at most 300
characters. A metric `value` is a whole number the store's column can hold: between
-2^63 and 2^63-1. Nothing a run measures comes near that; a number that does is a
counter that wrapped, or was never a count.

### What is refused, and by which half

Two different things are checked, and the split is why they do not drift.

**Layout, refused as `input` at exit 2**, before a store is opened: the document is not
UTF-8, is not an object, declares another `schema` or `version`, carries a key nothing
defines at any level, writes a key twice in one object, uses a JSON type a field is not
written in, uses `NaN` or `Infinity`, gives `true` where a whole number belongs, or
leaves out a field that has no default. Anything a JSON parser will not return a value
for is refused the same way, whether it is malformed, nested past the parser's own
bound, or carrying an integer literal too long to convert. The message names the field
and the *shape* that arrived, never the value that was in it.

**Content, refused as `trace` at exit 1**: a trace id that is not 32 hex characters, a
value outside a closed set, an instant spelled another way, a span outside its run, a
cycle in the span tree, two root spans, a reference longer than the store can hold, a
measurement wider than the column that records it, or a name that is not a slug. None of
it is reimplemented here; the document is converted into the model's own records and
`semantic_layer.trace.model.validate` refuses it with the sentence it already writes.

There is no field for a prompt, a completion, a tool argument, a tool result, a request
or response body, an environment, a blob, or a free-form attribute - and there is no
"unknown keys are ignored" behaviour for one to arrive under. That is the whole of the
privacy guarantee at this boundary, and it is the representation rather than a rule:
`docs/l3-execution-trace.md` says why it was decided before a line was written.

An input document longer than 16 MiB is refused. Nothing this layer produces comes close
to it; the bound exists so a caller-supplied pipe cannot be an unbounded read.

## Rules that hold across every command

**Time is always the caller's.** `--as-of` is stated on every command that needs an
instant, and nothing here reads the clock. A pack verified against "now" answers a
different question every time it is run, and a retention policy that consulted the clock
could be argued about but never demonstrated.

**The store is always the caller's.** `--store` is a path, stated every time. No
environment variable is read, no configuration file is looked for, and no home directory
is guessed at: a command that found a store by itself would write evidence somewhere its
caller never asked for and read it back from somewhere else. `:memory:` is refused
(`usage`) - it lives as long as the process, so a run recorded into one from here is
gone before the answer describing it is read.

Only `trace record` may create a store. `get`, `project` and `expire` refuse a path that
names nothing, because SQLite would answer a mistyped path by creating an empty database
and every one of them would then report, truthfully and uselessly, that it holds no such
run. None of them creates the directories above the file.

**Files are read once, from the descriptor that was opened.** A path is checked after it
is opened and read from that same descriptor, so nothing can be substituted between the
check and the read, and what was verified and what is returned cannot come apart. A
directory, a device or a named pipe where a file belongs is refused (`path`) rather than
read.

**Concurrency is SQLite's, and nothing here adds a second opinion.** There is no lock
file, no cache and no coordination layer beside the database; two processes recording
into one store are two writers on one SQLite file. A write is one transaction that lands
whole or leaves nothing, and the trace id is the primary key - so two processes cannot
both create divergent content under one identifier. The one that loses the insert has
written nothing, and what it is holding is then held against the rows that did land:
identical is a replay (`created: false`), anything else is refused (`trace`). A store
another process holds a lock on fails closed as `store` once SQLite gives up waiting,
rather than as a traceback.

**There is still no service.** This starts nothing, listens on nothing, schedules
nothing, and reaches the network from nowhere. It is a process that runs, answers, and
exits, against files its caller named. Retention is a command somebody runs, not a timer
this owns.

## What the wheel carries

An installed consumer has no checkout, so the vocabularies and the shapes travel with
the code: `pyproject.toml` puts `ontology/*.ttl` and `ontology/shapes/*.ttl` into the
wheel under `semantic_layer/_ontology/`, and `semantic_layer.graph` reads the packaged
copy when there is one and the checkout otherwise. Verification needs it: a manifest
states the `vocabulary_version` a consumer compiles against, and this reader holds that
against the version the vocabulary itself declares.

Nothing else is packaged. `ontology/instances/`, `sources/`, `packs/` and `queries/` are
this installation's own content and the suite's fixtures, and a wheel is something
anybody can install: shipping one site's captured responses or accepted observations to
everybody who installs the library is a different mistake each time and the same rule.

`tests/test_packaging.py` builds the wheel with the same backend that builds it for
release, reads what is inside it, installs it into a virtual environment of its own, and
runs every command from a working directory outside this repository with an environment
that carries nothing from it. That is there because a green suite in a checkout says
nothing about an installation: an editable install *is* the checkout, so a missing
resource is invisible in one by construction.

## Examples

All of these run offline against what this repository already commits.

```sh
# Is the pack still worth acting on, and what is it about?
semantic-layer pack verify \
    --directory packs/github/vvonkledge-siana \
    --as-of 2026-08-30T09:00:12Z \
    --expect-source https://semantic-layer.19h09.co/l2/github/api-github-com \
    --expect-target vvonkledge/siana
```

```sh
# Hand the verified bytes to something that will read the graph.
semantic-layer pack export \
    --directory packs/github/vvonkledge-siana \
    --as-of 2026-08-30T09:00:12Z | jq -r .result.content.text > context.nt
```

```sh
# Record what the run did, piping the document in.
semantic-layer trace record \
    --store ~/runs/trace.sqlite3 \
    --pack packs/github/vvonkledge-siana \
    --as-of 2026-08-30T09:00:12Z \
    --expect-target vvonkledge/siana \
    --input - < run.json
```

```sh
# Read it back, and hand its PROV summary to something that speaks only PROV-O.
semantic-layer trace get     --store ~/runs/trace.sqlite3 --trace-id 4bf92f35...
semantic-layer trace project --store ~/runs/trace.sqlite3 --trace-id 4bf92f35... \
    | jq -r .result.summary.text
```

```sh
# Retention, on an instant somebody chose.
semantic-layer trace expire --store ~/runs/trace.sqlite3 --as-of 2026-12-01T00:00:00Z
```

A consumer in Python, which is the shape SIANA will use:

```python
import json, subprocess

RESPONSE = "https://semantic-layer.19h09.co/cli/response"


def call(*argv, stdin=None):
    done = subprocess.run(["semantic-layer", *argv], input=stdin, capture_output=True, text=True)
    answer = json.loads(done.stdout)
    if answer["schema"] != RESPONSE or answer["version"] != 1:
        raise RuntimeError(f"a response layout this consumer does not know: {answer['schema']}")
    if done.returncode != 0:
        raise RuntimeError(f"{answer['error']['kind']}: {answer['error']['message']}")
    return answer["result"]
```

Check the layout before the exit code: a document written for a later contract may not
mean what its `error` field looks like it means.

## What is deliberately not here

No command builds a pack, refreshes an observation, reconciles a capture, or writes
anything under `ontology/`, `sources/` or `packs/`. Those are this repository's own
workflow, they are reviewed as a diff, and `just refresh` is how a person runs them.

No command reads raw SQL, updates a record, deletes one selectively, or promotes a
finding into a proposal against L1 or L2. The first three do not exist anywhere in this
layer; the last is a later phase, and it lands as a reviewed change rather than as
something a run can do to itself.
