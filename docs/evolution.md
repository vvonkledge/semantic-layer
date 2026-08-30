# Changing the layer

## Git is the write authority

There is no admin UI, no API and no direct write path into L1. The Turtle files in
this repository *are* the business layer, and the only way a business fact changes is
a merge request against them.

This is a deliberate reuse rather than an economy. Review, attribution, history and
rollback are the four things a knowledge base needs and the four things a version
control system already does well. Approving a change to what the organization is
accountable for is then the same act, with the same audit trail, as approving a change
to code.

Two consequences worth stating:

- **A change is not true until it is merged.** A proposal is a branch. Nothing reads
  from a branch.
- **Where an upstream system already owns a fact, this repository reflects it and
  never writes back.** People and team membership almost always come from an HR system.
  Say so with `core:sourceOfTruth`, and keep the import one-way. A two-way sync between
  a graph and an HR system is a conflict-resolution problem nobody has asked for.

  L2 is that principle built out. A capture reads the public GitHub API and writes
  nothing back - there is no request in `src/semantic_layer/acquire.py` that is not a
  GET, and no credential that could authorize one. What it produces is a diff, and the
  diff becomes truth the same way a business fact does: reviewed and merged. See
  [l2-technical-layer.md](l2-technical-layer.md).

## Vocabulary changes are additive by default

Downstream consumers compile against the vocabulary and the shapes, so:

- **Adding** a class, a property or a shape is a minor version bump. Existing data
  stays valid; nothing that read the graph yesterday breaks today.
- **Removing** a class or a property, or **narrowing** a shape - a new `sh:minCount`,
  a tighter `sh:class` - is a breaking change. It needs a version bump on the
  vocabulary, and a deprecation window during which the old term still exists.
- Terms are retired with `owl:deprecated`, not deleted, for the same reason entities
  are (see [identifiers.md](identifiers.md)).

`owl:versionInfo` on each ontology in `ontology/` carries the version. Instances are
versioned by the git commit; `core:version` records a business-meaningful revision when
one exists. A context pack carries the technical vocabulary's version in its manifest,
because a consumer compiles against the vocabulary and has no other way to pin to it.

Adding a property to a vocabulary automatically widens what that layer's entities may
carry: each boundary shape asks the vocabulary which properties its layer defines, so
there is no second allowlist to keep in step. Adding a *technical* term to the business
vocabulary is therefore how the L1/L2 boundary would be breached, and it is a review
question, not a mechanical one. The same is true the other way: a business term added to
`ontology/tech.ttl` would let an import state who is accountable for something.

There is exactly one term that names the other layer, and it is `tech:realizes`, whose
`rdfs:range` is `biz:Capability`. `tests/test_layers.py` pins that: the technical
vocabulary may mention the business namespace in that one triple and nowhere else, and
the business vocabulary may not mention the technical namespace at all. A second crossing
is a red build rather than a paragraph somebody has to notice.

It is also the *only* route, which is worth stating because it was once not true. SHACL
judges one graph and cannot see where a triple came from, so while the vocabulary was
merged flat into the data under validation, an instance file could assert
`tech:productionEndpoint rdfs:isDefinedBy <.../vocab/biz>` and the boundary shape would
believe it - a breach needing no vocabulary edit at all, and so nothing for a reviewer
of `ontology/biz.ttl` to see. Each vocabulary now loads into a named graph of its own
and the shape asks inside it, and Turtle has no syntax for naming a graph, so only a
vocabulary can say what a vocabulary defines. The mechanism is in `graph.data_graph`;
the reason it is shaped that way is here.

The same mechanism carries a second job now. Instances load into one of two more named
graphs, curated or observed, chosen by the directory the file sits in - so a file cannot
claim to be the other layer either, and a technical fact filed as declared business truth
is rejected on where it is committed rather than on what it says. Four graphs, one rule:
what a file may assert about itself stops at its own triples.

## Adding a business entity

1. Mint the identifier with the rules in [identifiers.md](identifiers.md).
2. Add it to a Turtle file under `ontology/instances/business/`.
3. Give it an `rdfs:label` a person outside the team would recognize.
4. Run `just test`. A capability with no owner, an assignment with no policy or an
   agent assigned work no role permits will be rejected with a message saying which.

## Changing an observed fact

You do not. An L2 file under `ontology/instances/technical/` is generated, and editing
it is caught: the suite asserts that the committed graph is exactly what the committed
capture reconciles to.

What changes is the observation:

```sh
just refresh    # capture, reconcile, pack
git diff        # this is the review
```

Reconciliation is byte-deterministic, so a refresh that changes nothing shows no diff and
what a reviewer reads is exactly the difference between two readings of the source.
Everything else about the workflow - what the diff means, what a rename looks like, and
what to do when a capture fails - is in [l2-technical-layer.md](l2-technical-layer.md).

A `tech:realizes` edge is the exception, and the only thing under
`ontology/instances/technical/` a human writes: it is a decision about the organization,
so it is authored under review and lives in a file of its own beside the generated one.

## Two traps that fail quietly

**Never run a reasoner over this graph.** `sh:class` already follows
`rdfs:subClassOf*`, so a `Team` satisfies a constraint requiring an `Actor` with no
inference at all. The `rdfs:domain` and `rdfs:range` declarations in the vocabulary are
documentation for external consumers. Turning RDFS inference on would materialize types
*from* those declarations - anything on the receiving end of `biz:ownedBy` would become
an `Actor` by fiat - and every endpoint check in `ontology/shapes/biz.ttl` would then
pass on data it was written to reject. The validator is pinned to `inference="none"`
in `src/semantic_layer/graph.py`.

**Compare timestamps; never do duration arithmetic in a query.** SPARQL engines
disagree about `dateTime + duration`: rdflib evaluates it, oxigraph leaves it unbound.
An unbound value in a `FILTER` is not an error, it is simply false, so a query written
with duration arithmetic fails *open* and silently - every row quietly passing a check
that never ran. Only `dateTime > dateTime` behaves the same everywhere. Materialize any
computed instant when the data is written, and keep every query to plain comparison.

This was cheap advice when L1 had only `core:validFrom` and `core:validTo`, and it is now
the rule the technical layer is built around. `tech:freshUntil` is computed once, when an
observation is reconciled, and written down; `queries/is-the-observation-fresh.rq`
compares against it and against an instant the caller supplies, and never against the
clock. Nothing anywhere adds a duration to a timestamp.

A related trap sits one step down. rdflib will happily order an `xsd:date` against an
`xsd:dateTime` and hand back an answer, so a freshness rule written without checking the
datatypes first reports a perfectly coherent window as expired - one rule failing for
another rule's reason, and a reader told to fix the wrong thing.
`shpt:ObservationShape` checks the datatype before it compares.

## Validation is a batch pass, never a write-time check

`shp:AssignmentShape` requires that an assignment's assignee holds a role permitting
the targeted capability. That rule cannot be enforced as each edge arrives, in any
store: a graph is assembled one statement at a time, and the same finished, valid graph
is invalid halfway through, depending only on the order the statements happened to
arrive in. Validity is a property of the completed graph.

So validation runs over the whole graph, on every change, in CI. That is SHACL's
contract, and it is the reason the layer is worth expressing in RDF rather than as
tables with triggers.
