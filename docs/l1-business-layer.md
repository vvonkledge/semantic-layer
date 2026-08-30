# L1: the business layer

L1 says what the organization is trying to do, who answers for each part of it, what
an agent may be asked to do, and under which rule. It is written in the language a
director would use in a meeting, and it stays true when every system underneath it is
replaced.

## The nine things it describes

| | what it is | the question it answers |
|---|---|---|
| **Goal** | an outcome the organization wants | what are we trying to achieve? |
| **Capability** | something the organization is able to do | what do we do? |
| **Actor** | anyone or anything held accountable | who is answerable? |
| **Person** | a named human | which human? |
| **Team** | a standing group held accountable as a unit | which group? |
| **AgentIdentity** | a non-human actor work is given to | which agent? |
| **Role** | a bundle of permission to perform capabilities | what may they do? |
| **Policy** | a rule constraining how work is carried out | under what constraint? |
| **Assignment** | one piece of work given to one agent | who is doing what, and why? |

And how they join up:

```
Capability   supports          -> Goal
Capability   ownedBy           -> Actor           (exactly one)
Actor        grantsRole        -> Role            (read: the actor holds the role)
Role         permits           -> Capability
Assignment   assignedTo        -> AgentIdentity   (exactly one)
Assignment   targetsCapability -> Capability      (exactly one)
Assignment   servesGoal        -> Goal            (exactly one)
Assignment   governedBy        -> Policy          (exactly one)
```

## The two decisions worth understanding

**An agent identity is an Actor.** An agent is something the organization gives work
to and holds to account, which is the definition of an actor it already had. So
ownership, permission and accountability work the same way for agents and for people,
rather than agents getting a second, weaker mechanism that drifts out of step with
the first. This is the single move the rest of the model rests on.

**A capability must have exactly one owner.** Not zero, because unowned work is
unassignable: nobody can grant permission for it and nobody answers when it goes
wrong. Not two, because shared accountability is how a decision ends up with nobody
making it. If two teams genuinely own different parts, those are two capabilities.

## The boundary with L2

L1 never names a service, a repository, a database, an environment or an endpoint. Those
belong to the technical layer, L2, which now exists: see
[l2-technical-layer.md](l2-technical-layer.md).

The reason is not tidiness. A technical fact is only true as of the last time someone
looked at reality, so it decays and must carry an observation time. A business fact is
true because the organization declared it, and stays true until the organization
declares otherwise. Mixing them gives business truth an expiry date it has no way to
honour, and gives technical truth an authority it has not earned.

Exactly one edge crosses between the layers, and it points **upward**: a service
*realizes* a capability. Never the reverse, because a capability has to survive the
deletion of every system that ever delivered it. It is written in L2, authored by a
human under review, and no import creates one - a source knows what it contains, not
what the organization is accountable for.

The boundary is enforced, not merely documented, and in three places rather than one.

**What an L1 node may say.** An L1 entity may carry only properties defined by the core
or business vocabularies, plus the standard RDF annotations. Anything else is rejected
with a message saying so (`ontology/shapes/biz.ttl`, `shp:L1BoundaryShape`) - including
`tech:realizes` itself, written backwards onto a capability.

**Where it may be said.** Curated business truth is committed under
`ontology/instances/business/` and observed technical truth under
`ontology/instances/technical/`. The loader reads each directory into a named graph of
its own, and a business entity committed as observed truth is rejected on that alone
(`ontology/shapes/tech.ttl`, `shpt:CuratedFactInTheObservedGraphShape`). Turtle has no
syntax for naming a graph, so a file cannot claim to be the other layer.

**And it is enforced against the data it is judging, not only against honest data.** The
vocabularies are loaded into named graphs of their own and the boundary shapes ask their
question inside them, so a file cannot grant itself an allowance by declaring a technical
term to be part of L1. Widening the boundary takes a vocabulary edit, which is a reviewed
change to a small file, and [evolution.md](evolution.md) says what to look for.

## What the model can be asked

Three questions are committed as queries in `queries/`, with their answers committed
beside them. They are the ontology's acceptance tests: a vocabulary change that stops
the model answering a business question fails the build.

- **Which capabilities serve this goal?** - where effort should go.
- **Who owns this capability, and who may perform it?** - ownership and permission are
  different answers, and the model must not conflate them.
- **Under which policy is this agent doing this work?** - the audit question. One row
  carries agent, capability, goal and policy.

## What is deliberately not here

No technical entities, no freshness or staleness, no execution traces, no runtime data,
and no real organizational content. Freshness in particular belongs to L2 and stops
there: an L1 statement has no observation behind it, because nobody observed the
organization deciding what it is accountable for - they wrote it down.

`ontology/instances/business/` is where curated content lands, and it is empty on purpose
until the organization's own goals and capabilities are authored. L2 now holds a real
observation of a real repository, and that is not a reason to fill it: nothing about what
a system contains says what the organization answers for.

Everything under `ontology/instances/fixtures/` is test data and is minted in namespaces
no curated entity and no accepted observation ever uses, so the two can never be
confused.
