# semantic-layer

The business layer, L1: what this organization does, who answers for it, what agents
may be asked to do, and under which policy.

It is a set of RDF/Turtle files in git, validated by SHACL, queried by SPARQL. There is
no server and no database. The files are the layer.

## Start here

- **[docs/l1-business-layer.md](docs/l1-business-layer.md)** - what the model says, in
  business language, and where the line with the technical layer will fall.
- **[docs/identifiers.md](docs/identifiers.md)** - how an entity is named, why the name
  is a URL that nothing serves, and why a name is never reused.
- **[docs/evolution.md](docs/evolution.md)** - how a business fact changes, how the
  vocabulary grows, and two ways to break this quietly.

## Run it

```sh
just test     # validate everything, and prove the guardrails still hold
just check    # lint too; this is what CI runs
```

Requires [`uv`](https://docs.astral.sh/uv/) and [`just`](https://just.systems/). No
credentials, no network access at test time, no services to start.

## Layout

```
ontology/
  core.ttl                    lifecycle terms shared by every layer
  biz.ttl                     the L1 business vocabulary
  shapes/biz.ttl              SHACL: what a valid business graph looks like
  instances/business/         curated L1 content (empty until authored)
  instances/fixtures/valid/   test data that must validate
  instances/fixtures/invalid/ test data that must be rejected, each with the
                              exact message it must be rejected with
queries/                      competency questions, with committed answers
src/semantic_layer/
  ids.py                      IRI minting; the one place identity rules live
  graph.py                    loading, validating and querying
tests/
```

## What `just test` proves

1. Every committed graph validates against every shape.
2. Every negative fixture is rejected, **and rejected for its intended reason** - the
   exact message is committed beside the fixture, so a shape cannot silently stop
   enforcing while something else keeps failing in its place.
3. Every constraint in `ontology/shapes/biz.ttl` has such a fixture - wherever in a
   shape it is written, nested inside another shape included, and whichever SHACL
   parameter states it, one the test file has never heard of included. The parameters
   it has heard of are held against the list pyshacl enforces, so the classification
   cannot fall behind the validator. That pairing is itself checked rather than
   believed, so no constraint can be removed, loosened or added without a fixture that
   says what it was for.
4. Two groups of SHACL terms are refused rather than covered, and the refusal is what
   is guaranteed about them. The qualified family - `sh:qualifiedValueShape`,
   `sh:qualifiedMinCount`, `sh:qualifiedMaxCount`, `sh:qualifiedValueShapesDisjoint` -
   states how many values *and* which values count, and a fixture can only be written
   against the count. The modifiers `sh:flags` and `sh:ignoredProperties` decide where
   the parameter beside them draws its line, and a fixture is written against the
   parameter. Either way the rule can be widened while every fixture goes on failing for
   exactly its committed reason. Rather than claim a coverage guarantee that would not
   hold for them, phase 0 prohibits both groups in the shapes file, by name and by term.
   The parameters the modifiers move - `sh:pattern`, `sh:closed` - are supported and
   audited like any other. Nothing in the shapes file uses any of it.
5. Every competency question returns its committed answer, so a vocabulary change that
   stops the model answering a business question fails the build.
6. Every committed entity carries exactly the identifier minting would give it, so a
   fixture cannot leak into curated content - and an entity written with no identifier
   at all is rejected rather than skipped.

The whole suite is deterministic and runs in under two seconds.

## Scope

This is phase 0. There is no technical layer, no execution trace, no freshness, no
context packs and no runtime. `ontology/instances/business/` is deliberately empty:
the model and its guardrails come first, and the organization's own content is a human
decision to be made against a model that has already been proven to hold.
