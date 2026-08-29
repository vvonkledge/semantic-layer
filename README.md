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
3. Every competency question returns its committed answer, so a vocabulary change that
   stops the model answering a business question fails the build.
4. Every committed entity carries exactly the identifier minting would give it, so a
   fixture cannot leak into curated content.

The whole suite is deterministic and runs in under a second.

## Scope

This is phase 0. There is no technical layer, no execution trace, no freshness, no
context packs and no runtime. `ontology/instances/business/` is deliberately empty:
the model and its guardrails come first, and the organization's own content is a human
decision to be made against a model that has already been proven to hold.
