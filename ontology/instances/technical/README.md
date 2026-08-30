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

**Authored.** A `tech:realizes` edge - the one term that crosses into L1 - is a decision
about what the organization is accountable for, so it is written by a person under
review and belongs in a file of its own beside the generated one. No import writes one:
a source knows what it contains, not what the organization answers for.

Everything under `../fixtures/technical/` is test data, minted in a namespace no accepted
observation ever uses, and is not a statement about any real system.
