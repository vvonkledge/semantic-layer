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
one exists.

Adding a property to the vocabulary automatically widens what L1 entities may carry:
the boundary shape asks the vocabulary which properties L1 defines, so there is no
second allowlist to keep in step. Adding a *technical* term to the business vocabulary
is therefore how the L1/L2 boundary would be breached, and it is a review question, not
a mechanical one.

## Adding an entity

1. Mint the identifier with the rules in [identifiers.md](identifiers.md).
2. Add it to a Turtle file under `ontology/instances/business/`.
3. Give it an `rdfs:label` a person outside the team would recognize.
4. Run `just test`. A capability with no owner, an assignment with no policy or an
   agent assigned work no role permits will be rejected with a message saying which.

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
This costs nothing today, when L1 has only `core:validFrom` and `core:validTo`, and it
is the trap that bites hardest when the technical layer arrives with freshness on every
node.

## Validation is a batch pass, never a write-time check

`shp:AssignmentShape` requires that an assignment's assignee holds a role permitting
the targeted capability. That rule cannot be enforced as each edge arrives, in any
store: a graph is assembled one statement at a time, and the same finished, valid graph
is invalid halfway through, depending only on the order the statements happened to
arrive in. Validity is a property of the completed graph.

So validation runs over the whole graph, on every change, in CI. That is SHACL's
contract, and it is the reason the layer is worth expressing in RDF rather than as
tables with triggers.
