# Project orders: semantic-layer

This repository is a semantic layer kept in git. There is no server, no database and no
runtime: the files are the layer. Two kinds of truth are committed here - L1, what the
organization declared about itself, and L2, what a system was observed to hold at an
instant - and almost everything in this repository exists to stop a convenient change
blurring the difference between them.

Read `README.md` for what the layers are and what the suite proves, then the file under
`docs/` for the layer you are about to touch. This file is what you are held to.

## What is where

- `ontology/core.ttl`, `ontology/biz.ttl`, `ontology/tech.ttl` are the vocabularies.
  Each loads under the IRI it declares, into a named graph of its own, which is what
  lets a shape ask a vocabulary what that vocabulary defines and get its own answer.
- `ontology/shapes/biz.ttl` and `ontology/shapes/tech.ttl` are SHACL: what a valid
  business graph and a valid observed graph look like.
- `ontology/instances/business/` is L1. A person authored every line of it from what
  the organization declared, under review. Nothing imports into it.
- `ontology/instances/technical/` is accepted L2. `github-vvonkledge-siana.ttl` is
  generated from the committed capture and is not yours to edit by hand.
  `realizes-vvonkledge-siana.ttl` is the one hand-authored edge that crosses upward,
  in a file of its own so the reviewed line and the imported ones are never mixed.
- `ontology/instances/fixtures/` is test data, valid and invalid, one set per layer.
  Every invalid fixture commits the exact rejection message it must produce, in the
  `.expected.txt` beside it.
- `sources/github/` holds the captured response and its digest. `packs/github/` holds
  the context pack a consumer is handed: `content.nt` and `manifest.json`.
- `queries/` holds the competency questions, each with its committed answer.
- `src/semantic_layer/` is the code: `ids.py` (identity), `graph.py` (named graphs,
  validation, querying), `github.py` (the source contract and its reconciler),
  `acquire.py` (the one place that touches the network), `pack.py`, `serialize.py`.
- `tests/` is the suite: pytest, offline, deterministic. `docs/` is the prose a
  contributor reads. The `justfile` holds every command, and
  `.github/workflows/check.yml` runs one of them on a clean runner.

## How your work is checked

    just check

`just check` is this project's delivery command. It is lint and the complete suite
together - `ruff check`, `ruff format --check`, then `uv run pytest` - and it is exactly
what CI runs from `.github/workflows/check.yml`. Green here is the claim you are making
about your branch.

    just test

`just test` is the inner command: the suite alone, without lint. Use it while you are
working, because it is the faster half. It is not what delivery is judged on. A
formatting failure is a red run like any other, and finding one after you have spent a
pipeline round costs you the round.

The whole suite is deterministic and runs in a few seconds. What it proves is listed in
`README.md`, and the list is worth reading before you argue with a test.

**The suite is offline by construction, and it enforces that on itself.**
`tests/conftest.py` takes the socket away for the whole session, so a test that reaches
for the network fails saying so rather than passing on a machine that happens to be
online. Do not weaken that, do not grant a test a network of its own, and do not skip a
test when it has none. Acquisition is exercised by injecting a reader
(`tests/test_acquisition.py`), which is how the failure modes that matter most - a rate
limit, a refusal, malformed JSON, a chain that breaks mid-page - can be driven at all.

The one narrow exception is `just capture`, reached through `just refresh`. It reads the
public GitHub API and writes into the working tree, so what it produces is a candidate:
a diff, reviewed and merged like any other change. A person runs it deliberately. It is
not part of `just check`, CI never runs it, and no test may reach it.

## Boundaries a change must not cross

Almost all of this is enforced somewhere in the suite, and a test that fails will name
the rule it holds. It is written out here anyway, because a failing test tells you that
a rule exists and never tells you what it was for.

1. **L1, L2 and L3 are different kinds of truth.** L1 is declared: true because the
   organization said so, and true until it says otherwise. It never names a service, a
   repository, an environment or an endpoint, and it is never inferred from what a
   system below it contains. L2 is observed: true as of the last time somebody looked,
   carrying the instant it was read and the instant it stops being worth believing, and
   it never states who is accountable for anything. L3 is evidence: what was observed
   to have happened, admissible only as far as the evidence committed beside it goes,
   and never a route by which a trace becomes a declaration. Wherever L3 exists in the
   tree in front of you, it lives beside L2 under its own vocabulary, shapes and named
   graph, and it never becomes a source of L1 truth.
2. **Exactly one term crosses, and it points upward.** A technical artifact
   `tech:realizes` a business capability, never the reverse, because a capability has to
   survive the deletion of every system that ever delivered it. A human authors that
   edge under review; no import writes one.
3. **Named graphs are what separate the layers, and a file cannot choose its own.** The
   loader in `graph.py` puts a file into the curated or the observed graph based on the
   directory it sits in, and Turtle has no syntax for naming a graph. That
   classification lives in one place. Moving it into the files, or letting a file
   assert its own layer, silences every boundary shape at once.
4. **No inference, ever.** No reasoner is run. `sh:class` already follows
   `rdfs:subClassOf*`, so class hierarchies work without one, while `rdfs:domain` and
   `rdfs:range` stay documentation. Turning inference on would materialize types from
   domain and range and quietly disable every endpoint check in both shapes files.
5. **Every constraint has a negative fixture, and the fixture commits its message.** A
   fixture that merely fails proves nothing: the shape could have stopped enforcing
   while something else failed in its place. The exact message is committed beside the
   fixture, and the pairing between constraints and fixtures is itself checked, so a
   constraint cannot be removed, loosened or added without a fixture saying what it was
   for. Two SHACL families are refused by name rather than covered; `README.md` says
   which and why.
6. **Time is explicit, and never the clock.** Freshness is a comparison of two committed
   instants against an instant the caller supplies - in the competency query and in
   `pack.verify` - never duration arithmetic, and never `now`. Staleness is not a shape
   and could not be: a graph does not know what time it is, and a rule that read the
   clock would make `just check` pass in the morning and fail in the afternoon over a
   file nobody touched.
7. **Serialization is deterministic and generated files are generated.** The committed
   L2 graph must be exactly what the committed capture reconciles to, byte for byte,
   under a changed hash seed, timezone and locale. The committed pack must be exactly
   what that graph packs. So a refresh that changes nothing shows no diff, and a hand
   edit to a generated file fails the build rather than surviving in it.
8. **A context pack is verified exactly.** Stale, tampered with, internally
   inconsistent, from another source, about another target, or in a layout this reader
   does not understand - each is refused as a `PackError` naming the field or the half
   at fault, before any of it reaches a parser. A manifest carrying a field nothing
   holds is refused rather than partly checked. Adding a field means adding what holds
   it.
9. **An identifier is minted in one place and never reused.** `ids.py` is that place,
   and every committed entity in both layers is checked against what minting would give
   it. A retired thing is deprecated and superseded; its name keeps resolving.

## Conventions

- Never the em dash. Use a plain dash.
- Wrap prose at 88 columns. Fenced and indented blocks are commands: wrapping one
  changes what it does.
- Comments and docstrings say why, not what. The diff already shows the what, and a
  refusal with no reason beside it will be deleted by whoever meets it next.
- Python is formatted and linted by ruff at 100 columns, configured in `pyproject.toml`.
  `just check` is what says so.
- Minimum code that solves the problem. Nothing speculative.
- If you change a behaviour a test names, change that test in the same commit and say
  why. If you add a behaviour worth having, add the test that fails without it.

## The pipeline

**Every ship task in this project is validated by `siana-pipeline`.** SIANA queues ship
work here with `verify: siana-pipeline check`, and `check` reads what a run recorded
instead of starting one. No brief has to ask for this, and none does: if you are
shipping, you are driving a run, and work that never reached a passing run cannot
verify. Whether a project is driven this way is a field on the captain's registry
record. That record is SIANA's, and nothing you change in this worktree sets it.

A run is two steps, in that order. First it executes this project's own ship command,
which is the `just check` above: exact, a few seconds, and yours to get green before you
spend a run on it. Then it puts an agent on your diff, read against your brief and
against these orders. That second step is why the rigor is a pipeline and not a command:
it is judgment, it costs tokens, and every finding it raises costs you another round.

The rest of this section is how a round behaves.

### A round

From your own worktree, with everything committed:

    siana-pipeline run

It refuses a dirty tree. A run validates one commit and records which one, so anything
you have not committed is work it would pass without having seen. It runs `just check`
first and starts the reviewer only on a green run of it, so a red suite costs you a few
seconds and no tokens.

Then read the exit code. It is the whole protocol:

    0   passed. The record is green at this commit. Stop here.
    1   yours to fix. Fix it, commit, and run again.
    2   not yours. `block`, and relay what it printed, verbatim.

There is no third state, and there is no run to attach to: the command returns or it
does not, so nothing can be parked at a gate and there is no status to poll. An exit
code here really is a verdict, because the thing that produced it has already finished.

The pipeline neither pushes nor publishes, and neither do you. It is review, lint and
tests, and your branch is where it ends. Nothing leaves this machine until a second
minion has accepted the work, and what lands is SIANA's.

### After a pass

**Do not commit again.** The run recorded the head it validated, and your verify is
`siana-pipeline check`, which compares that head against where your branch actually is.
A pass is bound to that one commit. A commit after a passing run turns a finished task
into a red verify, and it does so for a good reason: the QA minion is cut from this
branch, and it would otherwise read a head nothing validated while wearing your green.

If you do have to change something, that is fine. Change it, commit it, and run again.
What you must never do is change it and call `done`.

`check` starts nothing; it reads the record. So `done` cannot produce a green that a run
did not already earn, and there is no flag anywhere that makes it try.

### What a finding is

A finding the run lists for you to fix is yours: the reviewer read your diff against
your brief and says that part is wrong. Fix it, commit, run again.

A finding the run prints as one nobody here can settle is not yours at all. It is a
product choice, a destructive step, or a change to what you were asked for. `block` and
relay it word for word. Answering it yourself is deciding something the pipeline already
said was not the minion's to decide, and paraphrasing it decides half of it on the way
past.
