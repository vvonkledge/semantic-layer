# L2: the technical layer

L1 says what the organization does. L2 says what a system was observed to hold, when it
was observed, and how long that is worth believing.

The difference is not a matter of subject. A business fact is true because the
organization declared it, and stays true until the organization declares otherwise. A
technical fact is true as of the last time somebody looked, and starts decaying
immediately. Mixing them gives business truth an expiry date it cannot honour and gives
technical truth an authority it has not earned, so they are separate vocabularies, in
separate files, in separate named graphs, with one edge between them.

This is one vertical slice of L2, end to end, against one real source: the public
GitHub metadata for `vvonkledge/siana`. It is the first source, not a GitHub ingestion
framework.

## The five things it describes

| | what it is | the question it answers |
|---|---|---|
| **Source** | a system, at one installation of it | which system said this? |
| **Observation** | one reading of one source at one instant | when was it last true? |
| **Account** | an account at the source | which account does the source say it is under? |
| **Repository** | a repository at the source | which repository? |
| **Branch** | a named line of development in one repository | which branch, pointing where? |

And how they join up:

```
Observation  observedFrom     -> Source          (exactly one)
Artifact     observedIn       -> Observation     (exactly one)
Repository   ownedByAccount   -> Account         (exactly one)
Repository   defaultBranch    -> Branch          (exactly one)
Branch       branchOf         -> Repository      (exactly one)

Artifact     realizes         -> biz:Capability  (the one edge that leaves L2)
```

`Account`, `Repository` and `Branch` are all `Artifact`s, which is where provenance and
the layer boundary are stated once rather than three times.

## The crossing, and its direction

Exactly one term joins the layers: `tech:realizes`. A technical artifact realizes a
business capability. There is no downward term and there will not be one, because a
capability has to survive the deletion of every system that ever delivered it.

It is **authored by a human, under review, and never imported.** A source knows what it
contains; it does not know what the organization is accountable for. Nothing in the
GitHub reconciler writes a `tech:realizes` edge, and
`tests/test_reconciliation.py::test_the_import_writes_no_crossing_edge` is what keeps
that true.

Writing one is two lines in a file under `ontology/instances/technical/`, and there is
exactly one committed - `realizes-vvonkledge-siana.ttl`, which says the repository this
layer observes is one of the systems the organization delivers `Orchestrate fleet
delivery` with:

```turtle
<https://semantic-layer.19h09.co/l2/github/api-github-com/repository/1347717349>
    tech:realizes <https://semantic-layer.19h09.co/biz/capability/orchestrate-fleet-delivery> .
```

It is a file of its own beside `github-vvonkledge-siana.ttl` rather than a line inside
it, because that file is generated: the suite asserts it is exactly what the committed
capture reconciles to, so a hand-written line there fails the build. The separation is
also what a reviewer reads - one file is a reading of a system, the other is a judgement
about the organization, and they are never mixed in one diff.

The capability end lives in `ontology/instances/business/`, and the two files are in
different graphs. That is deliberate: the edge is an L2 statement about an L2 thing, so
it belongs with the layer that decays. If the capability is later retired, L1 deprecates
it and the edge keeps resolving, which is the whole reason identifiers are never reused
([identifiers.md](identifiers.md)).

The boundary is enforced in three places, and each has a negative fixture:

- An L1 node may carry only properties the core or business vocabularies define, so a
  capability that names a repository - or that writes `tech:realizes` backwards - is
  rejected (`shp:L1BoundaryShape`).
- An L2 node may carry only properties the core or technical vocabularies define, so an
  import that decided who owns something is rejected (`shpt:L2BoundaryShape`).
- A technical fact committed in a curated directory, or a business fact committed in a
  technical one, is rejected on where it is committed rather than on what it says
  (`shpt:ObservedFactInTheCuratedGraphShape`, `shpt:CuratedFactInTheObservedGraphShape`).

The third one is what the named graphs buy. The loader chooses a file's graph from the
directory it sits in, and Turtle has no syntax for naming a graph, so a file cannot
claim to be the other layer. The same mechanism is why an instance file cannot grant
itself a vocabulary allowance: each vocabulary loads into a named graph of its own and
the boundary shapes ask inside it, so only a vocabulary can say what a vocabulary
defines. See `graph.data_graph`.

## The source contract

`src/semantic_layer/github.py` is the contract, and it is deliberately narrow. Ten
fields of the repository response, three of its owner, three of a branch. Everything
else GitHub returns - topics, star counts, permissions, avatars, the forty URL
templates - is dropped at the capture boundary and never reaches the graph.

Three rules make that a contract rather than a preference.

**The payload is closed.** A field the contract does not name is an error, not
something ignored. GitHub adds fields constantly, and a reader that ignores what it does
not recognize cannot tell a new field from a renamed one, or either from a response that
is not the response it thinks it is. It is also what keeps a credential out of the
graph: there is no field a token could arrive in and be written from.

**Absent is not empty.** A branch list is only an authoritative answer if the capture
followed pagination to the end, so the snapshot records whether it did and a collection
that does not say so is refused. An optional field is absent when GitHub said `null`,
and an error when GitHub did not mention it: the first is an answer, the second is a
different response.

**Topics and names are not read for meaning.** Repository names, topics and contributors
are the fields somebody would be tempted to read a capability or an owner out of, and
that inference is L1's to make, by a person, under review. Topics are not in the
supported payload at all, and the layer boundary would reject the result if they were.

## Identity

An L1 identifier is a human-authored slug. None of that carries over: an L2 entity is
not authored, it is observed, and the thing being observed already has a name in a system
that renames things without telling anyone.

So an L2 identifier is **scoped by its source** and **built from the source's own
immutable id**. The source is the scope, so it is named by the scope and nothing more:

```
source     https://semantic-layer.19h09.co/l2/github/api-github-com
entity     https://semantic-layer.19h09.co/l2/github/api-github-com/repository/1347717349
observation https://semantic-layer.19h09.co/l2/github/api-github-com/observation/<sha256 hex>
```

`src/semantic_layer/ids.py` is the only place these rules live, and nothing else builds
one by hand - not the reconciler, not the fixtures, not the tests.

**A rename changes nothing.** GitHub renames a repository in one click and keeps the
numeric id, so the next observation updates `tech:repositoryPath` and mints no second
entity. If the identifier tracked the path, the rename would create a new repository,
the old one would go quiet, and nothing would say the two were one thing.

**Two sources never collide.** GitHub's numeric ids mean nothing outside GitHub, and
nothing outside the installation that issued them: a GitHub Enterprise host issues
`1347717349` to something else entirely. Both the provider and the installation are in
the path, so the two are different identifiers.

**A branch carries the pair that gives its name meaning.** GitHub issues a branch no
immutable id and git has none to issue - a branch *is* its name within its repository,
and renaming one is a delete and a create. So the identifier carries the repository id
and the branch name, and a rename is honestly a different branch.

**Source text never becomes structure.** A branch name is whatever somebody pushed. Each
local-id segment is percent-encoded, so a slash, a fragment or a query in a branch name
lands as characters rather than as segments a parser would read back as a different
entity. `.` and `..` are refused outright: nothing resolves these IRIs, so neither is a
vulnerability here, but an identifier that means one thing before normalization and
another after is not a stable identifier.

**A missing immutable id is a refusal.** An id that is absent, `null`, zero, negative or
a string gets no identifier at all. Minting one from the name instead is exactly how a
rename becomes a second entity.

## Freshness, and why it is a timestamp

Every observation carries two instants: `tech:observedAt`, when the source was read, and
`tech:freshUntil`, when the reading stops being worth believing. The second is
**materialized when the observation is reconciled** - `observedAt` plus the source's
freshness window, which is 24 hours and is declared in `acquire.FRESHNESS_SECONDS`.

Asking whether something is fresh is then a comparison of two timestamps, and never
duration arithmetic. That is not a style choice. SPARQL engines disagree about
`dateTime + duration`: rdflib evaluates it, oxigraph leaves it unbound, and an unbound
value in a `FILTER` is not an error - it is false. A freshness check written with
duration arithmetic passes everything, silently. See [evolution.md](evolution.md).

The comparison instant is always supplied by the caller. `queries/is-the-observation-fresh.rq`
supplies two, one inside the window and one past it, so its committed answer proves both
directions rather than whichever one today happens to give. Nothing in this repository
reads the wall clock to decide whether a fact is fresh.

**Staleness is therefore not a shape, and could not be.** SHACL judges a graph, and a
graph does not know what time it is. A rule that rejected stale observations would have
to read the clock, which would make `just test` pass in the morning and fail in the
afternoon over a file nobody touched - and worse, it would delete history: an observation
that has gone stale is still a true record of what the source held, and the honest thing
to do with it is say when it stopped being current, not refuse to load it.

So the shapes enforce what a graph can answer for itself - that both instants are
present, are instants, and describe a window that closes after it opens
(`shpt:ObservationShape`) - and the staleness question is asked where somebody is about
to act on the answer, against an instant they name: in the competency query, and in
`pack.verify`.

The window is deliberately blunt: 24 hours for every artifact this source imports, rather
than a per-field guess about how fast each one moves. A branch head goes stale in
minutes and a repository id never does, and pretending to know the difference would be a
number nobody could defend. One declared window a consumer can read is more useful than
five invented ones.

Trust works the same way: `tech:trustBasis` is a sentence saying what was read, with
whose authority, and what that authority does not cover. It travels with every context
pack, so a consumer weighs a stated claim instead of inventing a generous one.

## Refreshing and promoting an observation

There is no promote step in code, because git already is one.

```sh
just refresh    # capture, reconcile, pack
git diff        # this is the review
```

1. **`just capture`** reads the public GitHub API for `vvonkledge/siana`, projects the
   response onto the contract, and writes `sources/github/vvonkledge-siana/snapshot.json`
   with its digest beside it. It is the only command here that touches the network.
2. **`just reconcile`** turns that snapshot into
   `ontology/instances/technical/github-vvonkledge-siana.ttl`. It is byte-deterministic,
   so a refresh that changes nothing shows no diff, and what a reviewer sees is exactly
   the difference between two observations.
3. **`just pack`** rebuilds the context pack under `packs/github/vvonkledge-siana/`.
4. **The diff is the candidate.** It becomes accepted L2 truth when it is reviewed and
   merged. Nothing reads from a branch.

A refresh that changes something changes the committed competency answers too, because
the questions are asked of everything committed as valid and two of them report the
observation. That is intended: the answers a consumer is promised are part of what a
refresh moves, so they are reviewed in the same diff rather than drifting behind it.
Re-run `just test`, which names the question whose answer moved, and commit the new one
with the observation it came from. The authored `tech:realizes` edge is untouched by any
of this - it names the repository by its identifier, which a refresh never changes.

`just check` then holds all of it together: the committed graph must be exactly what the
committed snapshot reconciles to, the committed pack must be exactly what the committed
graph packs, and both must satisfy every shape.

**Source drift is what the diff shows.** A new head commit, a new branch, a rename, a
repository that went private - each appears as lines in
`ontology/instances/technical/github-vvonkledge-siana.ttl` and in the snapshot beside it.
A rename in particular is worth reading carefully: `tech:repositoryPath` changes, the
identifier does not, and every reference held elsewhere keeps resolving. If the
identifier had changed, that would be the bug.

**A repository that stopped being public** is a 404, and the capture refuses. That is an
answer about the repository, not a reason to authenticate: the last accepted observation
stays exactly where it is, and stops being fresh on its own schedule.

## When a capture fails

Every failure says what stopped it, and nothing is written until everything has been
read, projected and hashed. Each write is one atomic replace, so no file is ever left
half-written: what is on disk is whole bytes, either the new ones or the previous ones.

A capture writes two files, though - the snapshot and its digest - and two renames are
not one. So there are two outcomes, not one. Killed before or during the first write,
both files are still the last accepted observation and there is nothing to clean up.
Killed between the two, the snapshot is the new one and the digest still commits the old
bytes: the pair disagrees, and `just reconcile` refuses it by name rather than
reconciling it. That is what stops it being believed downstream - the accepted graph and
the context pack are written by other commands, from a snapshot that has already passed
that check, so neither can move because of an unfinished capture.

Recovering from that pair is yours, and it is a choice rather than one command: run
`just capture` again to land the new observation whole, or `git checkout` the snapshot
and its digest together to return to the old one. A capture writes into a git working
tree, so both observations are still there to choose between.

| what happened | what you get |
|---|---|
| network unreachable, timeout | `GET ... did not complete`, nothing written |
| rate limited (403/429, quota 0) | the reset time, and a note that anonymous reads cannot raise the limit |
| 401, or 403 that is not a rate limit | a refusal means the resource is not public - which is an answer, not a reason to authenticate |
| 404 | the target no longer exists at that path, or is no longer public |
| any other status | the status, and nothing written |
| HTTP 200 with a body that is not JSON | a response nothing can parse is not an empty answer |
| a page of a collection failed | nothing, not the pages that did arrive |
| pagination pointed off the API | refused |
| a field the contract reads is missing | schema drift, named, as a decision about the contract |
| the process died during a write | that file's previous bytes, and no `.partial` file |
| the process died between the two writes | a new snapshot beside the old digest, refused by name at `just reconcile` |

For every row but the last, nothing was written and recovery is to fix the cause and run
`just capture` again. The last row is the one that leaves something behind, and it is
recovered by the choice above.

Whenever a snapshot and its committed digest disagree - because a write was interrupted,
or because one of them was edited after the other was written - `just reconcile` refuses
outright, and bytes nothing vouches for are not reconciled into truth.

## Context packs

A pack is what leaves this repository. Everything else here is for the people who
maintain the layer; a pack is for a consumer with none of the context, no access to the
git history, and a decision to make.

```
packs/github/vvonkledge-siana/
  content.nt      sorted N-Triples: one canonical line per triple
  manifest.json   what it is, and what to check it against
```

The content is one observation and nothing else: the source, the reading, and the
artifacts that reading saw.

It **points at** L1 and asserts nothing **about** it. A `tech:realizes` edge is an L2
statement about an L2 artifact, so it travels - and it is the fact a consumer most wants,
because it says which capability the system they are looking at delivers. The capability
on the other end does not, because L1 has no observation behind it and no freshness to
state, and shipping it here would stamp declared business truth with an expiry date it
has no way to honour. A consumer that needs the capability's own details asks L1, where
they are true until the organization says otherwise.

The manifest names the graph, the vocabulary version a consumer compiles against, the
source and what backs it - the provider, the API root, and the trust basis - the target,
the observation, `observed_at`, `fresh_until`, the digest of the capture it came from,
the digest and size of the content itself, how many artifacts it holds, and how it is
encoded.

Every one of those is checked, and a manifest carrying a field this reader has no rule
for is refused rather than partly checked. There are three kinds of rule and each field
has exactly one. Most are **read back off the content**: the source, the target, both
instants, the snapshot digest, the provider, the API root and the trust basis are each
compared against the triple that states them, on the node that states it. Four are
**recomputed from the content**: the observation it names, what the content hashes to,
how long it is, and how many artifacts it holds. The remaining four - the pack layout,
the named graph, the vocabulary version and the content media type - state nothing about
GitHub and nothing in the content could restate them, so they are held against the
constants this reader itself is built for, and a pack declaring another is about a
layer, a vocabulary or an encoding this code does not speak.

That list is not maintained by hand on either side. `pack.build` writes the manifest from
the same enumeration `pack.verify` reads it back with, and the suite asserts that the
fields built, the fields verified and the fields it forges one by one are the same set -
so a field added to the manifest fails the build rather than reaching a consumer with
nothing holding it. `trust_basis` is why that matters: it is the field this page tells a
consumer to weigh before acting, and a manifest is read *instead of* the graph.

`pack.verify` is the half that matters, and a consumer runs it:

```python
from semantic_layer import pack

held = pack.read(directory)
try:
    pack.verify(
        held.content,
        held.manifest,
        as_of="2026-08-30T12:00:00Z",  # your instant, not the clock
        expect_source="https://semantic-layer.19h09.co/l2/github/api-github-com",
        expect_target="vvonkledge/siana",
    )
except pack.PackError:
    refuse()
```

It refuses a pack that is **tampered with** (the content does not hash to what the
manifest claims), **inconsistent** (any field of the manifest says something the content
or this reader's own constants do not),
**stale** (your instant is not before `fresh_until`), **from another source** (an
identifier means nothing outside the source that issued it, so the same number elsewhere
is a different thing), **about another target**, or **written in a layout this reader
does not understand**. Each refusal is a test in `tests/test_context_pack.py`.

That `except` is the whole of a consumer's error path, and it is meant to be. A pack is
two files somebody else wrote, so it can be malformed as easily as it can be dishonest -
a manifest field holding a number where text belongs, content that is not parseable
N-Triples, an `as_of` that is not a UTC instant. Every one of those is refused as a
`PackError` naming the field or the half at fault, before any of it reaches an RDF term
or a parser. A refusal escaping as somebody's library exception would be caught by
nothing a consumer was told to write, so the suite drives every manifest field against
every shape its rule cannot read and asserts the type and the sentence.

`as_of` is supplied rather than read from the clock for the same reason the competency
question supplies its own: a check against "now" answers a different question every time
it runs, and cannot be tested at all.

The pack is also the join key between this layer and the evidence above it. A recorded
run names the exact pack it was handed, by the digest of each of its halves, and
`semantic_layer.trace` gets those digests by running this same verifier rather than by
believing the caller - so "what did that run know" and "which reading of GitHub was it
looking at" are one question with one answer. See
[l3-execution-trace.md](l3-execution-trace.md).

## What is deliberately not here

No second repository and no organization crawl - this is one source, chosen because it
is public, bounded and rich enough to prove the whole path. No webhooks, no polling, no
daemon, no server, no database. No write-back of any kind: nothing here sends anything
to GitHub but a GET. No authentication, no secrets, no private repositories. No workflow
runs, jobs or deployments - those are execution traces, and an execution trace is L3.

And no business content inferred from any of it. `ontology/instances/business/` is no
longer empty, and nothing in this layer is why: what is there was declared by the
organization and authored by a person under review. The single sentence joining the two
is the `tech:realizes` edge above, and a person wrote that too.
