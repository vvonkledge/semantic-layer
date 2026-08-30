# The captured source response

`snapshot.json` is what the public GitHub API returned for `vvonkledge/siana` at the
instant recorded in it, projected onto the contract in
`src/semantic_layer/github.py` - ten repository fields, three of its owner, three of a
branch, and nothing else. `snapshot.json.sha256` is the digest of those exact bytes.

It is committed so the layer can be audited offline. `just test` reconciles it and
asserts the result is byte-for-byte
`ontology/instances/technical/github-vvonkledge-siana.ttl`, so the graph and the bytes it
came from can never drift apart unnoticed, and no test needs a network. The hand-authored
`tech:realizes` edge sits in a file of its own beside that one and is no part of this
pairing: a source says what it holds, never what the organization is accountable for.

Editing either file breaks the pair on purpose: `just reconcile` refuses when the
snapshot and its digest disagree, because bytes nothing vouches for are not reconciled
into truth. Recapture instead:

```sh
just refresh    # capture, reconcile, pack
```

The capture is unauthenticated and read-only. It carries no credential, sends nothing
but a GET, and the fields it keeps are chosen rather than swept up - which is why there
is no field a token could arrive in. See
[docs/l2-technical-layer.md](../../../docs/l2-technical-layer.md).
