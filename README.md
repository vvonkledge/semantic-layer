# semantic-layer

Two layers, in git, validated by SHACL and queried by SPARQL.

**L1, the business layer:** what this organization does, who answers for it, what agents
may be asked to do, and under which policy. True because the organization declared it,
and true until it declares otherwise.

**L2, the technical layer:** what a system was observed to hold, when it was observed,
and how long that is worth believing. True as of the last time somebody looked.

There is no server and no database. The files are the layer.

## Start here

- **[docs/l1-business-layer.md](docs/l1-business-layer.md)** - what the business model
  says, in business language.
- **[docs/l2-technical-layer.md](docs/l2-technical-layer.md)** - the source contract,
  identity, freshness, the refresh workflow, context packs, and what to do when a
  capture fails.
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
credentials, no network access at test time, no services to start. The suite is offline
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
  shapes/biz.ttl              SHACL: what a valid business graph looks like
  shapes/tech.ttl             SHACL: what a valid observed graph looks like
  instances/business/         curated L1 content (empty until authored)
  instances/technical/        accepted L2 truth, reconciled from a capture
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
tests/
```

## The line between the layers

L1 never names a service, a repository, an environment or an endpoint. L2 never states
who is accountable for anything. Exactly one term crosses, and it points **upward**: a
technical artifact `tech:realizes` a business capability, never the reverse, because a
capability has to survive the deletion of every system that ever delivered it.

That edge is authored by a human under review. No import writes one: a source knows what
it contains, not what the organization answers for.

The boundary is enforced three ways, and each has a negative fixture that commits the
message it is rejected with. Two ask what a node may *say*, by asking each vocabulary -
inside its own named graph - which properties it defines. The third asks where a node may
be *said*: the loader puts a file in the curated or the observed graph based on the
directory it sits in, and Turtle has no syntax for naming a graph, so a file cannot claim
to be the other layer.

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
5. Every competency question returns its committed answer, so a vocabulary change that
   stops the model answering a question fails the build.
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
9. A context pack that is stale, tampered with, internally inconsistent, from another
   source or about another target is refused, against an instant the caller supplies
   rather than the clock. Every field the manifest carries is held - against the content,
   against a recount of it, or against a constant this reader is built for - and a
   manifest carrying a field nothing holds is refused rather than partly checked.

The whole suite is deterministic and runs in a few seconds.

## Scope

This is phase 1: L1 as phase 0 left it, plus one complete L2 vertical slice against one
real source - the public GitHub metadata for `vvonkledge/siana`.

There is no execution trace, no runtime, no server, no write-back, and no second source.
`ontology/instances/business/` is deliberately still empty: authoring the organization's
own business content is a human decision, and no amount of technical evidence is a reason
to make it.
