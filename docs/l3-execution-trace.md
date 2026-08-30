# L3: the execution trace

L1 says what the organization declared. L2 says what a system was observed to hold. L3
says what happened.

That is a third epistemic status, not a weaker version of either. A business fact is
true because the organization said so and stays true until it says otherwise. A
technical fact is true as of the last time somebody looked and starts decaying at once.
A trace is true because it happened, and it never stops being true - but it is
*evidence*, and evidence does not get to change what it is evidence about.

So the rule that shapes everything below is a single sentence: **a trace records what
happened and never states what is true.** It is the rule most likely to be broken in a
hurry, by a run that notices the default branch has moved and helpfully patches the
observed graph, and it is enforced rather than asked for.

This is one vertical slice of L3, end to end: a span store, a writer, a retention
boundary, and a PROV-O summary. It is not a runtime, an OpenTelemetry collector, or a
place production traces are shipped to.

## There is no service

L3 is a library. A caller opens a local SQLite file, records whole runs into it, expires
old span detail against an instant it supplies, and asks for the PROV summary of a run.
Nothing listens on a port, nothing runs in the background, and `just test` starts
nothing:

```python
from semantic_layer import pack as packs
from semantic_layer.trace import Finding, Metric, Run, Span, TraceStore

with TraceStore.open("trace.sqlite3") as store:
    run_iri = store.record(
        Run(
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
            started_at="2026-08-30T09:00:00Z",
            ended_at="2026-08-30T09:00:12Z",
            outcome="succeeded",
            spans=[
                Span(
                    "00f067aa0ba902b7",
                    "verify-pack",
                    "internal",
                    "ok",
                    "2026-08-30T09:00:00Z",
                    "2026-08-30T09:00:02Z",
                )
            ],
            metrics=[Metric("branches-read", 2, "count")],
            findings=[Finding("branch-moved", "warning")],
        ),
        pack=packs.read(packs.pack_dir()),
        as_of="2026-08-30T09:00:12Z",
        expect_target="vvonkledge/siana",
    )
    summary = store.summary("4bf92f3577b34da6a3ce929d0e0e4736")
    expired = store.expire_spans(as_of="2026-12-01T00:00:00Z")
```

That is the whole public surface, and the list is deliberately short:

| | what it does |
|---|---|
| `TraceStore.open(path)` | open or create a store; `:memory:` works, which is what the suite uses |
| `store.record(run, pack=, as_of=, ...)` | verify the pack, validate the run, write it whole, return its IRI |
| `store.read(trace_id)` | the run as the store holds it now |
| `store.summary(trace_id)` | the PROV-O summary, as an rdflib graph |
| `store.expire_spans(as_of=)` | remove span detail older than ninety days; return what it removed |
| `store.trace_ids()` | every run recorded here |

There is no update and no delete, and that is not an omission - see
[append-only](#append-only-and-the-one-way-out).

## The six things it describes

| | what it is | the question it answers |
|---|---|---|
| **Run** | one execution, named by its OpenTelemetry trace id | what ran? |
| **Span** | one timed operation inside it | what did it do, and when? |
| **ContextPack** | the exact verified pack it was handed | what did it know? |
| **Outcome** | the closed state it finished in | how did it end? |
| **Metric** | one named, typed measurement it rolled up | how much? |
| **Finding** | something it noticed, as a code and a severity | what did it see? |

And how they join up:

```
Run     usedPack     -> ContextPack   (exactly one; the most important cardinality here)
Run     hasOutcome   -> Outcome       (exactly one)
Span    ofRun        -> Run           (exactly one)
Metric  ofRun        -> Run           (exactly one)
Finding ofRun        -> Run           (exactly one)
Span    parentSpan   -> Span          (at most one, inside the same run)

Span    touched      -> any L1 or L2 node   (named, never asserted)
Finding findingAbout -> any L1 or L2 node   (named, never asserted)
Run     prov:wasAssociatedWith -> biz:AgentIdentity  (where one is supplied)
```

`trc:usedPack` is mandatory and is the cardinality the whole model turns on. Without the
pack there is no record of what the agent was told, so a failure cannot be attributed
between bad knowledge and bad reasoning, and the improvement loop the trace exists for
has nothing to act on.

## The pack binding, and what "proves" means

A run does not *say* which pack it used. It is recorded against two files, and
`semantic_layer.trace` hands them to the real verifier in `semantic_layer.pack` - the
same one a stranger receiving a pack would run, against the instant the caller supplies.
A pack that is stale, tampered with, internally inconsistent, from another source or
about another target is refused before a single row is written.

What is then recorded is derived from the bytes and never from a claim:

```
trc:contentDigest    sha256 of the pack content that verified
trc:manifestDigest   sha256 of the manifest that verified
trc:packObservation  the L2 observation the manifest named
trc:packSource       the source that observation was read from
trc:packTarget       what it was about, in the source's own terms
```

and the `ContextPack` entity is named by a digest over the pair of digests. Both halves
are hashed, and the second one is the interesting case: tampering with either is already
refused by the verifier, but a manifest re-rendered with the same fields in a different
spelling verifies happily and is *not the bytes this run was handed*. A binding that
named only the content would call those two runs the same run.

There is no way past this. `record` takes the two halves and an instant; it takes no
"already verified" flag, no path to look a pack up by, and no manifest object a caller
could have built themselves.

## Structure, never payload

The captain decided this before the first line was written, and it is why L3 was blocked
until it was decided: **L3 stores structure and never raw payload.** No prompt, no
completion, no tool argument, no tool result, no request or response body, no
environment dump, no opaque blob.

The reason is asymmetry. Adding a payload field later is a reversible decision. Removing
sensitive data from an append-only history is not - it is either a rewrite of evidence
or a promise nobody can keep.

A policy of that shape is worth nothing written down, so it is written into the
representation instead, in three places:

1. **There is no attribute bag.** Every record is a frozen dataclass with a closed set
   of fields. An unknown keyword is a `TypeError` before any of this repository's code
   runs, which is what stops a payload arriving under a key nobody reviewed - the way it
   always arrives.
2. **The fields that exist are narrow.** Identifiers are hex of a fixed width; instants
   are UTC spelled one way; the operation name, the metric name and the finding code are
   bounded slugs from the writer's own vocabulary, not free text; the kinds, statuses,
   severities and units are closed sets; and every reference to another layer must parse
   as an identifier this layer mints, so a reference cannot become a URL, a path or a
   sentence. There is no status *message* and no finding *description*, because those
   are where the exception text and the tool output would arrive.
3. **The store refuses one too.** Every table is `STRICT`, so a column typed `TEXT`
   rejects a blob rather than storing it, and every text column carries a `CHECK` that
   bounds its length and its alphabet or names the closed set it comes from. That second
   wall is for whoever reaches past this library with an ordinary SQLite connection - a
   migration script, a later version of this code, a person typing an `INSERT` at a
   shell. It is a wall against a mistake, not against the file's owner, who can drop the
   constraint as easily as write past it; see [the trust
   boundary](#what-holds-and-against-whom).

`tests/test_trace_privacy.py` offers a prompt, a tool call, an HTTP body, five kilobytes
of text and a blob to every field that takes text, and then writes each of them straight
at the database.

## Append-only, and the one way out

Recorded evidence is never edited. The supported API has no update and no delete, and
the refusal is also a trigger in the schema rather than only a rule this module follows,
because a guarantee that holds while everyone uses the front door and nowhere else is
not much of a guarantee about a history. An `UPDATE run`, a `DELETE FROM metric` or a
`DELETE FROM span` typed straight at the file is refused by SQLite.

A run is also written whole or not written. Validation and pack verification both
complete before the transaction opens, and the transaction writes the run, its spans,
its references and its rollups together, so a write that fails partway leaves nothing.

Recording the same run twice is a no-op that returns the same identifier - a writer that
retries has to be safe to retry - but only when the *complete* content agrees: the same
spans, the same references, the same rollups and the same pack. A trace id reused for
anything else is refused, because two different runs under one identifier is a record
nobody can read apart again.

### The ninety-day boundary

Span detail is the volatile half of a trace and the half nobody should keep forever. It
is removed once a run is older than ninety days. Everything a run is judged by
afterwards - its outcome, its metrics, its findings, the pack it used and its PROV
summary - is kept indefinitely, which is why those are entities of their own rather than
fields on a span.

Retention takes an explicit instant:

```python
store.expire_spans(as_of="2026-12-01T00:00:00Z")
```

It is supplied rather than read from the clock, and that is the whole reason the boundary
can be demonstrated instead of argued about. A policy that consults the wall clock
answers a different question every time it runs and cannot be tested at all. The horizon
is `as_of` minus ninety days, and a run expires when it ended **strictly before** it - so
a run of exactly the retention age is kept, and the suite tests the instant immediately
before the boundary, the boundary itself, and the instant immediately after.

Running retention again removes nothing further and says so, which is what makes it safe
to put on a timer. The expiry is recorded rather than inferred from the absence of spans:
a summary says `trc:spanDetailExpiredAt` instead of leaving a reader to reconstruct the
policy that produced it.

A run whose detail has expired cannot be replayed. Writing the spans back would undo the
removal, and accepting the replay unchecked would let a different run inherit a recorded
run's identifier.

## What holds, and against whom

Two mechanisms are doing different jobs here, and reading them as one produces a
guarantee nobody has.

**The ninety days are the API's.** `expire_spans(as_of=...)` computes the horizon as
`as_of` minus `RETENTION_DAYS`, selects the runs that ended strictly before it, and
deletes their span detail. That arithmetic lives in Python, in one function
(`retention_horizon`), and nothing downstream re-derives it or checks it. Change
`RETENTION_DAYS` and the policy changes, which is the point: it is a policy, and it is
meant to be changed on purpose and in one place.

**The triggers are narrower, and they are not the policy.** SQLite refuses `UPDATE` and
`DELETE` on `run`, `metric`, `finding` and `span_expiry` outright, and refuses `UPDATE`
on `span` and `span_reference`. Span detail may be deleted only while a retention pass
is open, and only for a run that ended before the horizon that pass *declared*. That
bounds the delete loop to what it said it was doing - a loop that selected one horizon
and then tried to delete past it is refused by the database - and it refuses a delete by
anything that is not driving a pass at all. It cannot check the ninety days: the trigger
is never told `as_of`, has no clock, and compares the run against the number it was
handed.

**So a caller that declares a dishonest horizon gets it.** Patch `RETENTION_DAYS` to one
day and a two-day-old run expires. Insert a horizon of 2099 into `retention_pass` from a
SQLite shell and every span in the file can be deleted. Both are demonstrated in
`tests/test_trace_retention.py`, committed as tests rather than left as surprises,
because a boundary that is written down is a boundary somebody can reason about and a
boundary that is only implied is one somebody trips over.

That is not a hole to be plugged. A store is a file on a disk, and its owner can drop a
trigger, rewrite the schema, or delete the file. **A local SQLite database cannot defend
itself against whoever owns it, and nothing here claims otherwise.** What the schema
buys is defence in depth against the ordinary failures - this library growing an edit
path, a later version of it deleting more than it meant to, a migration script, somebody
at a shell reaching for `UPDATE` - and that is worth having on its own terms.

## The PROV summary

The store holds the detail; the graph holds a bounded summary. Time-shaped access and
retention do not belong in RDF files, and lineage, interoperability and the join to L1
and L2 do not belong in a SQLite table.

PROV-O is reused rather than re-invented. A run and its spans are `prov:Activity`; the
pack it used and the rollups it produced are `prov:Entity`. Both vocabularies are
written out - `trc:Run` *and* `prov:Activity`, `trc:usedPack` *and* `prov:used` - because
this repository never runs a reasoner, so `rdfs:subClassOf` in the vocabulary is
documentation. Materializing both is what makes the interoperability real: a lineage,
audit or compliance tool that speaks only PROV reads a summary here with no integration
work, having never been told this vocabulary exists.

The projection is a function of the record and nothing else. No clock, no ordering, no
identifier minted from anything but the run's own content - so two projections of one run
are the same triples, and the same bytes once serialized. It stays valid after the span
detail expires, because everything it asserts about the run beyond the spans is a rollup
that does not.

Summaries are not committed to git. They are derived from the store, the way a context
pack is derived from the observed graph, and `ontology/instances/fixtures/trace/valid/`
holds one hand-authored example of exactly the shape the projector writes.

## The boundary, enforced three ways

**A trace may not state a business or technical fact.** `shpl:L3BoundaryShape` refuses
any L3 node that asserts a predicate the business or technical vocabulary defines. It
asks inside those vocabularies' own named graphs, so only a vocabulary can say what a
vocabulary defines, and no trace file can grant itself an allowance by declaring a term.

Naming is not asserting, and the difference is the whole rule. A trace names the agent
identity, the observation its pack carried and whatever its spans touched, and states
nothing about any of them - not a type, not a label, not a property. It does not even
type the agent `prov:Agent`, because that would be L3 saying something about an L1 node.

**Evidence is committed as evidence.** `ontology/instances/fixtures/trace/` loads into
the evidence graph and nothing else does. A trace node committed in the curated or
observed graph is refused, and a business or technical node committed as evidence is
refused, so a run can never author the facts it is then judged against.

**No trace path writes to the layers below.** `tests/test_trace_projection.py` hashes
every file under `ontology/`, `sources/` and `packs/`, records a run, expires it,
projects it twice, and holds the hashes again.

## The vocabulary and its shapes

`ontology/trace.ttl` is the vocabulary; `ontology/shapes/trace.ttl` is the contract for
the durable summary. Every constraint in that shapes file carries one message and one
negative fixture committing that exact message, audited by
`tests/test_shape_coverage.py` alongside the other two layers.

The shapes are deliberately narrower than what the writer checks, and the division is on
purpose. The writer validates a whole run before anything is written and refuses with a
sentence naming what to fix, because the caller is standing there with the run in their
hand and is the only one who can. The shapes state what a summary must carry to be
readable at all by somebody who has only the graph and no reason to trust whoever
produced it.

Two of the writer's rules are worth naming, because both are the kind of rule that only
shows up once something real is being recorded:

- **Every span lies inside its run.** A span records something that happened during the
  run, so the run's interval bounds it, inclusive at both ends: the first span shares the
  run's start and the last shares its end. Without the rule a twelve-second run in 2026
  could carry a span dated 2020, which is evidence that cannot be put on a timeline.
- **Every reference fits the column that records it.** An L2 identifier percent-encodes
  whatever a source called a thing, so a legal Git branch name of a couple of hundred
  characters - or a much shorter one written with accents, where each costs six
  characters once encoded - mints an identifier past the store's 300-character bound.
  That is refused by the writer, as a `TraceError` naming the length and what to do about
  it, rather than surfacing from inside the transaction as a SQLite integrity error
  naming a column. The same holds for the agent identity a run is associated with.

## Identifiers

An L3 identifier is machine-minted and scoped by nothing but the layer, which is unlike
both of the others (see [identifiers.md](identifiers.md)):

```
run       https://semantic-layer.19h09.co/l3/run/<trace id>
span      https://semantic-layer.19h09.co/l3/span/<trace id>/<span id>
pack      https://semantic-layer.19h09.co/l3/pack/<binding digest>
outcome   https://semantic-layer.19h09.co/l3/outcome/<trace id>
metric    https://semantic-layer.19h09.co/l3/metric/<trace id>/<name>
finding   https://semantic-layer.19h09.co/l3/finding/<trace id>/<ordinal>
```

The trace id and span id are the OpenTelemetry ones, carried verbatim so the evidence
joins to whatever tracing the fleet already runs rather than becoming a second,
divergent record of the same run. They are also what makes an identifier reproducible:
recording the same run twice mints the same IRIs, which is what lets a replay be
recognized as one.

## What is deliberately not here

- **No runtime and no collector.** Nothing integrates SIANA, Herdr or any live agent; no
  production trace is ingested; no OpenTelemetry exporter is wired up. This slice makes
  one run work end to end and establishes the contracts everything else compiles
  against.
- **No proposals and no write-back.** A finding is a report, not a correction. Turning
  one into a proposal against L1 or L2, and promoting a proposal into a reviewed change,
  is a later phase and is where the loop closes.
- **No `next_run` query and no accepted lessons.** Nothing here feeds pack construction
  yet.
- **No second store.** SQLite is the store because retention and time-shaped access do
  not belong in RDF files; swapping it is a phase-4 decision that has to be measured
  first. An L3 store is never migrated in place either - old spans are historical fact,
  so a new span schema is a new store and a dual-write window, and a store written by
  another schema version is refused rather than reinterpreted.
- **No confidence, and no inference from evidence.** A trace records what happened. What
  it means is somebody else's decision, made in L1, under review.
