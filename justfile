# Run `just` with no arguments to get the same check CI runs.
default: check

# Validate every committed graph in all three layers, prove every negative fixture fails
# for its stated reason, assert every competency question's answer, and exercise the L3
# trace library end to end. Offline by construction: the socket is taken away for the
# whole session, so a test that reaches for the network fails saying so rather than
# passing on a machine that happens to be online. L3 needs no service either - its store
# is a local SQLite file, and the suite opens it in memory.

# Validate everything, and prove the guardrails still hold.
test:
    uv run --frozen pytest

lint:
    uv run --frozen ruff check .
    uv run --frozen ruff format --check .

check: lint test

# The only recipe here that touches the network, and the only one that is not
# reproducible: it reads a system that moves. It writes into the working tree, so what
# it produces is a candidate - a diff. It becomes accepted L2 truth when that diff is
# reviewed and merged, the same way a business fact does. See docs/l2-technical-layer.md.

# Read the public GitHub API for vvonkledge/siana and capture an observation.
capture:
    uv run --frozen python -m semantic_layer.acquire

# Deterministic: a run that changes nothing writes the same bytes back and shows no
# diff, so what a reviewer sees is exactly the difference between two observations. The
# candidate is validated against the L2 shapes before it is written, so a graph that
# would not pass never reaches the working tree.

# Turn the committed capture into the committed L2 graph.
reconcile:
    uv run --frozen python -m semantic_layer.github

# Build the context pack for the accepted observation.
pack:
    uv run --frozen python -m semantic_layer.pack

# One observation, end to end. `git diff` is the review; `just check` is the gate.
refresh: capture reconcile pack
