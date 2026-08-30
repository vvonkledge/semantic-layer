# Identifiers

Every entity in the semantic layer has one identifier, and it looks like a URL. This
page is about L1, where identifiers are authored by people. L2 identifiers are minted
from a source's own immutable ids and are a different rule for a different reason; the
end of this page says what carries over and what does not, and
[l2-technical-layer.md](l2-technical-layer.md) has the whole of it.

```
https://semantic-layer.19h09.co/biz/capability/payment-processing
\_____________________________/\__/\________/ \_________________/
          permanent base      curated  kind          slug
```

`src/semantic_layer/ids.py` is the only place these rules live. Nothing else builds an
identifier by hand.

## Why a URL, when nothing is served from it

The base is a namespace, not a website. Nothing needs to answer an HTTP request there
and this repository does not make anything do so.

It is a URL because a URL is globally unique without anybody running a registry. The
organization already controls the domain, so no two teams, no two tools and no two
vendors can mint the same identifier for different things, and an identifier can be
handed to an external system without an accompanying explanation of whose `id 4127` it
is. That is the whole of the argument, and it is worth the mild strangeness of an
address that does not resolve.

Making the host resolve later - to documentation, to a lookup service - is possible and
purely additive. It is not required, and nothing in the layer should ever assume it.

## The slug

Lowercase letters and digits, joined by single hyphens: `payment-processing`,
`checkout-reliability`. Deliberately narrow, because a slug that can only be written
one way cannot be written two ways for the same entity.

Slugs are authored by a human, not generated. That is affordable here because L1 is
small and curated, and it is worth it because a readable identifier is one a person can
recognize in a report, in a review and in a five-year-old audit record.

Pick the name the business uses, not the name of the system that happens to implement
it today.

## The kinds

One per concrete business class: `goal`, `capability`, `person`, `team`, `agent`,
`role`, `policy`, `assignment`. The kind is part of the identifier so that reading it
tells you what you are looking at, and so a typo cannot quietly turn a goal into a
capability.

## Fixtures live in their own namespace

Test data is minted under `.../fixture/biz/...`, which curated content never uses:

```
https://semantic-layer.19h09.co/fixture/biz/capability/payment-processing
```

This is not a naming convention that people are asked to remember. `just test` walks
every committed instance file and checks that each entity's identifier is exactly what
minting would produce for its class and its directory, so a fixture cannot leak into
curated content or be mistaken for a statement about the organization.

## An entity with no identifier is not an entity

Turtle lets a node be written anonymously, and everything below is about identifiers
that are wrong rather than absent, so the absent case is stated separately:
`shp:IdentityShape` rejects a business entity written as a blank node. Such a node
validates as a capability or a goal in every other respect and can still never be
superseded, cited from another layer, or named in an audit record, because there is
nothing to cite. Mint the identifier first.

## Identifiers are never reused and never renamed

An identifier is a promise. Audit records, past assignments and anything the layer ever
handed to another system are holding copies of it, and those references have to keep
resolving years later.

So a rename is not an edit. It is:

1. Mint a **new** identifier with the new slug.
2. Point it at the old one with `core:supersedes`.
3. Mark the old one `owl:deprecated true`, and leave it in the graph.

```turtle
cap:payment-processing
    a biz:Capability ;
    rdfs:label "Payment processing" ;
    biz:ownedBy team:payments ;
    core:supersedes cap:card-payments .

cap:card-payments
    a biz:Capability ;
    rdfs:label "Card payments" ;
    biz:ownedBy team:payments ;
    owl:deprecated true .
```

Retiring something without a replacement is the same, minus the `core:supersedes`.

A supersession that leaves the old identifier undeprecated is rejected, because then
both look current and a reader has no way to tell which one to use
(`shp:SupersessionShape`). Deletion is never the answer: a deleted identifier is one
that some older record now points at and cannot resolve, and no error is raised
anywhere.

Queries that answer "what do we do now" filter out deprecated entities explicitly. See
`queries/capabilities-serving-a-goal.rq`.

## What L2 does instead

An L1 slug is authored, because L1 is small, curated, and named in the language the
business uses. None of that is true of a technical fact. An L2 entity is not authored,
it is observed, and the thing being observed already has a name in a system that renames
things without telling anyone and issues ids that mean nothing anywhere else.

So an L2 identifier is **scoped by its source** and built from the source's **immutable
id**, never from a name:

```
https://semantic-layer.19h09.co/l2/github/api-github-com/repository/1347717349
\_________________________________/\_____/\_____________/\_________/\________/
          permanent base           provider installation    kind     local id
```

Three things carry over from L1 and one does not.

**Carries over:** the base is a namespace, not a website. The rules live in one place,
`src/semantic_layer/ids.py`, and nothing builds an identifier by hand. Test data is
minted under a segment accepted content never uses - `.../fixture/l2/` here, as
`.../fixture/biz/` above - and `just test` checks every committed entity against what
minting would produce.

**Does not carry over:** an L2 identifier is not readable, and is not meant to be.
`1347717349` is what GitHub calls the repository, and the point is precisely that a
person cannot recognize it - because a name a person recognizes is a name somebody can
change, and a rename that mints a second entity is the failure this rule exists to
prevent. The readable part is an attribute: `tech:repositoryPath` says where the
repository is reachable today, and a refresh rewrites it while the identifier stays put.
