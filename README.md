# semantic-layer

Three layers. Two are files in git, validated by SHACL and queried by SPARQL; the third
is recorded evidence in a local SQLite file, summarized back into the same vocabulary.

**L1, the business layer:** what this organization does, who answers for it, what agents
may be asked to do, and under which policy. True because the organization declared it,
and true until it declares otherwise.

**L2, the technical layer:** what a system was observed to hold, when it was observed,
and how long that is worth believing. True as of the last time somebody looked.

**L3, the execution trace:** what a run was told, what it did, and what came of it. True
because it happened - and evidence, never truth: a trace changes neither of the layers
below it, and stores structure and never raw payload.

There is no server, no database and nothing to start. The files are the layers, and L3
is a library over one local file.

## Start here

- **[docs/l1-business-layer.md](docs/l1-business-layer.md)** - what the business model
  says, in business language.
- **[docs/l2-technical-layer.md](docs/l2-technical-layer.md)** - the source contract,
  identity, freshness, the refresh workflow, context packs, and what to do when a
  capture fails.
- **[docs/l3-execution-trace.md](docs/l3-execution-trace.md)** - the trace API, the span
  store, the privacy boundary, the ninety-day retention rule, and the PROV projection.
- **[docs/identifiers.md](docs/identifiers.md)** - how an L1 entity is named, why the
  name is a URL that nothing serves, and why a name is never reused.
- **[docs/evolution.md](docs/evolution.md)** - how a fact changes, how the vocabulary
  grows, and two ways to break this quietly.

## Run it

```sh
just test     # validate everything, and prove the guardrails still hold
just check    # lint too; this is what CI runs
```

Requires [`uv`](https://docs.astral.sh/uv/) and [`just`](https://just.systems/). No
credentials, no network access at test time, no services to start - including for L3,
which is a library over a local SQLite file and not a collector. The suite is offline
by construction: the socket is taken away for the whole session, so a test that reaches
for the network fails saying so rather than passing on a machine that happens to be
online.

To refresh the one observation this repository holds - the only command here that
touches the network:

```sh
just refresh  # capture, reconcile, pack
git diff      # this is the review
```

## Layout

```
ontology/
  core.ttl                    lifecycle terms shared by every layer
  biz.ttl                     the L1 business vocabulary
  tech.ttl                    the L2 technical vocabulary
  trace.ttl                   the L3 execution-trace vocabulary, over PROV-O
  shapes/biz.ttl              SHACL: what a valid business graph looks like
  shapes/tech.ttl             SHACL: what a valid observed graph looks like
  shapes/trace.ttl            SHACL: what a valid trace summary looks like
  instances/business/         curated L1 content the organization declared
  instances/technical/        accepted L2 truth, reconciled from a capture,
                              plus the one hand-authored edge that crosses up
  instances/fixtures/         test data, valid and invalid, one pair per layer;
                              each invalid fixture commits the exact message it
                              must be rejected with
sources/github/               the captured response, and its digest
packs/github/                 the context pack a consumer is handed
queries/                      competency questions, with committed answers
src/semantic_layer/
  ids.py                      IRI minting; the one place identity rules live
  graph.py                    loading into named graphs, validating, querying
  github.py                   the GitHub source contract and its reconciler
  acquire.py                  the one place that touches the network
  pack.py                     building a context pack, and verifying one
  serialize.py                deterministic Turtle and N-Triples
  trace/model.py              what a run may be written down as, and what it may not
  trace/store.py              the append-only SQLite span store, and retention
  trace/project.py            one recorded run -> its PROV-O summary
tests/
```

## The line between the layers

L1 never names a service, a repository, an environment or an endpoint. L2 never states
who is accountable for anything. L3 states nothing at all about either: it names their
nodes and asserts nothing about them, because a trace is evidence and evidence does not
get to change what it is evidence about.

Exactly one term crosses between L1 and L2, and it points **upward**: a technical
artifact `tech:realizes` a business capability, never the reverse, because a capability
has to survive the deletion of every system that ever delivered it.

That edge is authored by a human under review. No import writes one: a source knows what
it contains, not what the organization answers for. There is one of them committed -
`ontology/instances/technical/realizes-vvonkledge-siana.ttl`, saying that the repository
this layer observes delivers the capability `Orchestrate fleet delivery` - and it is in a
file of its own beside the generated graph, so the reviewed line and the imported ones
are never mistaken for each other.

The boundary is enforced by shapes, and each has a negative fixture that commits the
message it is rejected with. Some ask what a node may *say*, by asking each vocabulary -
inside its own named graph - which properties it defines: L1 and L2 each list the
vocabularies they may speak, and L3 is told instead what it may never assert, since it
legitimately speaks PROV-O, which this repository does not own. The rest ask where a node
may be *said*: the loader puts a file in the curated, observed or evidence graph based on
the directory it sits in, and Turtle has no syntax for naming a graph, so a file cannot
claim to be another layer.

## What `just test` proves

1. Every committed graph in both layers validates against every shape.
2. Every negative fixture is rejected, **and rejected for its intended reason** - the
   exact message is committed beside the fixture, so a shape cannot silently stop
   enforcing while something else keeps failing in its place.
3. Every constraint in `ontology/shapes/` has such a fixture - wherever in a shape it is
   written, nested inside another shape included, and whichever SHACL parameter states
   it, one the test file has never heard of included. The parameters it has heard of are
   held against the list pyshacl enforces, so the classification cannot fall behind the
   validator. That pairing is itself checked rather than believed, so no constraint can
   be removed, loosened or added without a fixture that says what it was for.
4. Two groups of SHACL terms are refused rather than covered, in both shapes files, and
   the refusal is what is guaranteed about them. The qualified family -
   `sh:qualifiedValueShape`, `sh:qualifiedMinCount`, `sh:qualifiedMaxCount`,
   `sh:qualifiedValueShapesDisjoint` - states how many values *and* which values count,
   and a fixture can only be written against the count. The modifiers `sh:flags` and
   `sh:ignoredProperties` decide where the parameter beside them draws its line, and a
   fixture is written against the parameter. Either way the rule can be widened while
   every fixture goes on failing for exactly its committed reason. Rather than claim a
   coverage guarantee that would not hold for them, both groups are prohibited by name
   and by term. The parameters the modifiers move - `sh:pattern`, `sh:closed` - are
   supported and audited like any other.
5. Every competency question returns its committed answer, asked of everything committed
   as valid - the real content and the fixtures together - so a vocabulary change that
   stops the model answering a question fails the build, and so does a change to what
   the organization declared that nobody meant to make.
6. Every committed entity carries exactly the identifier minting would give it, in both
   layers, so a fixture cannot leak into curated content or into an accepted
   observation - and an entity written with no identifier at all is rejected rather than
   skipped.
7. The committed L2 graph is exactly what the committed capture reconciles to, and the
   committed context pack is exactly what that graph packs. Reconciliation is
   byte-deterministic under a changed hash seed, timezone and locale, so a refresh that
   changes nothing shows no diff.
8. Every way a capture can fail leaves the last accepted observation untouched: rate
   limits, refusals, malformed JSON, schema drift, a pagination chain that breaks, and a
   process that dies mid-write. A capture writes two files and two renames are not one,
   so the guarantee across the pair is narrower and stated as such: an interruption
   between them is refused by name rather than reconciled, and cannot move the accepted
   graph or the pack. None of it needs a socket to test, and none of it can have one.
9. Recorded evidence never becomes truth and never changes it. An L3 node asserting a
   business or technical predicate is refused, a trace committed outside the evidence
   graph is refused, and a business or technical node committed as evidence is refused.
   Recording a run, expiring it and projecting it twice leaves every file under
   `ontology/`, `sources/` and `packs/` byte-identical.
10. A run is recorded whole or not at all, against a pack it verified with the real
   verifier and not on the caller's word. Duplicate or malformed identifiers, a parent
   outside the run, a cycle, a reversed interval, a span lying outside its own run, a
   reference too long for the store to hold, a malformed instant and a run with no spans
   are each refused with a sentence naming what to fix, and each leaves the store empty.
   Replaying an identical run is a no-op; a trace id reused for anything else is refused.
11. Recorded runs and spans cannot be updated or selectively deleted, by this library or
   by ordinary raw SQL. Retention removes full span detail strictly older than ninety
   days - tested at the instant before the boundary, at it, and after it - keeps every
   rollup indefinitely, and is safe to run again. The ninety days are the public API's
   arithmetic and the triggers hold a pass to the horizon it declared; a local SQLite
   file cannot defend itself against whoever owns it, and where that line falls is
   documented and tested rather than implied. The PROV summary is deterministic, readable
   by a consumer that speaks only PROV-O, and still valid once the spans are gone.
12. L3 cannot hold a payload. A prompt, a tool call, an HTTP body, five kilobytes of text
   and a blob are each offered to every field that takes text and to the database
   directly, and there is no free-form attribute or unknown key for one to arrive under.
13. A context pack that is stale, tampered with, internally inconsistent, from another
   source or about another target is refused, against an instant the caller supplies
   rather than the clock. Every field the manifest carries is held - against the content,
   against a recount of it, or against a constant this reader is built for - and a
   manifest carrying a field nothing holds is refused rather than partly checked.

The whole suite is deterministic and runs in a few seconds.

## Scope

This is phase 3: one complete L3 vertical slice on top of a complete L2 slice against one
real source - the public GitHub metadata for `vvonkledge/siana` - and, above both, the
first real slice of L1.

L1 now says one thing end to end: the outcome the organization wants, the capability it
exercises to reach it, who answers for that, the agent it is delegated to, what that
agent is permitted to do, and the policy the work is carried out under. It was authored
by a person from what the organization declared about itself, not inferred from what the
repository below it contains, because a source knows what it holds and never what the
organization answers for. One reviewed `tech:realizes` edge joins the two, and it points
upward.

L3 now records one run end to end: the exact pack it verified, its OpenTelemetry-shaped
spans, its outcome, metrics and findings, a ninety-day retention boundary that removes
only span detail, and a deterministic PROV-O summary that stays valid after they are
gone. It is a library over one local SQLite file.

There is no runtime, no server, no collector, no write-back, no proposal lifecycle, and
no second source.
