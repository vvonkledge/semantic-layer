"""One recorded run, and the pieces to build variations of it.

Shared by the four trace test files rather than repeated in each, because most of what
they assert is about one field of an otherwise-valid run and a run written out in full
four times is four places for the valid case to drift.
"""

from dataclasses import replace

from semantic_layer.trace import Finding, Metric, Run, Span

#: The instant every test verifies the committed pack against. Supplied rather than
#: read from the clock: the committed pack has a freshness limit, and a suite that
#: verified it against "now" would go red on a Tuesday for no reason anybody could see.
AS_OF = "2026-08-30T09:00:12Z"

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
ROOT_SPAN = "00f067aa0ba902b7"
CHILD_SPAN = "a2fb4a1d1a96d312"

REPOSITORY = "https://semantic-layer.19h09.co/l2/github/api-github-com/repository/1347717349"
AGENT = "https://semantic-layer.19h09.co/biz/agent/siana"
TARGET = "vvonkledge/siana"


def span(span_id=ROOT_SPAN, **over):
    defaults = {
        "span_id": span_id,
        "operation": "verify-pack",
        "kind": "internal",
        "status": "ok",
        "started_at": "2026-08-30T09:00:00Z",
        "ended_at": "2026-08-30T09:00:02Z",
    }
    return Span(**{**defaults, **over})


def run(**over) -> Run:
    defaults = {
        "trace_id": TRACE_ID,
        "started_at": "2026-08-30T09:00:00Z",
        "ended_at": "2026-08-30T09:00:12Z",
        "outcome": "succeeded",
        "spans": [
            span(),
            span(
                CHILD_SPAN,
                operation="read-branches",
                kind="client",
                started_at="2026-08-30T09:00:02Z",
                ended_at="2026-08-30T09:00:11Z",
                parent_span_id=ROOT_SPAN,
                touched=[REPOSITORY],
            ),
        ],
        "metrics": [Metric("branches-read", 2, "count"), Metric("pack-bytes", 7911, "byte")],
        "findings": [
            Finding("branch-moved", "warning", about=REPOSITORY),
            Finding("pack-nearly-stale", "info"),
        ],
        "agent": AGENT,
    }
    return Run(**{**defaults, **over})


def with_spans(*spans) -> Run:
    return replace(run(), spans=list(spans))
