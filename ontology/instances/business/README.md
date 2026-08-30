# Curated L1 content

The organization's own goals, capabilities, actors, roles, policies and assignments go
here, as Turtle files, minted under `https://semantic-layer.19h09.co/biz/`.

Everything here is true because the organization declared it, and stays true until the
organization declares otherwise. Nothing here was read out of a system, and nothing here
carries an observation time or an expiry: a fact that decays is an L2 fact and belongs
under [`../technical/`](../technical/README.md).

`siana-fleet-orchestration.ttl` is the first of it, and today it is all of it: one
outcome the captain wants, the one capability the organization exercises to reach it,
who answers for that capability, the agent identity it is delegated to, the role that
permits it, the policy it is carried out under, and the assignment that joins them. One
chain, end to end, rather than several areas half modelled.

Three lines are worth reading against the model rather than past it. The capability is
owned by a person and performed by an agent, which is the distinction
`queries/who-owns-and-may-perform-a-capability.rq` exists to keep: being asked to do
something is not being permitted to. The agent holds a role that permits exactly the
capability its assignment targets, and `shp:AssignmentShape` rejects the graph if that
stops being true. And the policy is where the limits on that delegation are written
down, so an auditor reads one entity rather than inferring the rule from what the fleet
happens to do.

What is deliberately absent is as much a decision as what is here. No team, no product,
no customer, no second capability, and nothing inferred from what any system contains:
a source knows what it holds, never what the organization answers for. Anything under
[`../fixtures/`](../fixtures/) is test data, lives in a namespace curated content never
uses, and is not a statement about the organization.

One system is recorded as delivering the capability above, and that statement is not
here: it is a single upward `tech:realizes` edge in
`../technical/realizes-vvonkledge-siana.ttl`, because the system is what decays and the
capability is what outlives it.

Everything in this directory is validated by `just test` against
`ontology/shapes/biz.ttl`, and a merge request is the only way anything gets in. See
[docs/evolution.md](../../../docs/evolution.md) for how to add an entity, and
[docs/identifiers.md](../../../docs/identifiers.md) for how to name one.
