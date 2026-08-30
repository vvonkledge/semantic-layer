# Accepted L2 truth

What a source was observed to hold, at an instant, after the observation was reviewed
and merged. The loader reads this directory into the observed named graph, and that -
rather than anything written in the files - is what makes a fact here technical rather
than business. See [docs/l2-technical-layer.md](../../../docs/l2-technical-layer.md).

Two kinds of file live here, and only one of them is written by hand.

**Generated.** `github-vvonkledge-siana.ttl` is `just reconcile` run over the capture
committed under `sources/github/vvonkledge-siana/`. Do not edit it: `just test` asserts
that it is exactly what that capture reconciles to, so an edit fails the build rather
than surviving quietly. To change what is here, capture a new observation:

```sh
just refresh    # capture, reconcile, pack
git diff        # this is the review
```

**Authored.** `realizes-vvonkledge-siana.ttl` is the one term that crosses into L1: a
single `tech:realizes` edge saying that the observed repository delivers the capability
`Orchestrate fleet delivery`, which is declared in
[`../business/`](../business/README.md). That is a decision about what the organization
is accountable for, so it is written by a person under review and lives in a file of its
own beside the generated one. No import writes one, and none ever will: a source knows
what it contains, not what the organization answers for.

The edge is an L2 statement about an L2 artifact, so it decays with the observation and
travels in the context pack; the capability on the other end does not. Reading it the
other way round is the mistake the direction exists to prevent - if the repository is
deleted, this line goes and the capability is untouched.

Everything under `../fixtures/technical/` is test data, minted in a namespace no accepted
observation ever uses, and is not a statement about any real system.
