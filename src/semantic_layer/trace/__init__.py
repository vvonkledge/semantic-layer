"""L3, the execution trace: what a run was told, what it did, and what came of it.

This is a library and there is no service to start. A caller opens a store on a local
file, records whole runs into it, expires span detail against an instant it supplies,
and asks for the PROV-O summary of a run. Four things, and nothing listening:

    from semantic_layer import pack as packs
    from semantic_layer.trace import Finding, Metric, Run, Span, TraceStore

    with TraceStore.open("trace.sqlite3") as store:
        run_iri = store.record(
            Run(
                trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
                started_at="2026-08-30T09:00:00Z",
                ended_at="2026-08-30T09:00:12Z",
                outcome="succeeded",
                spans=[Span("00f067aa0ba902b7", "verify-pack", "internal", "ok",
                            "2026-08-30T09:00:00Z", "2026-08-30T09:00:02Z")],
                metrics=[Metric("branches-read", 2, "count")],
                findings=[Finding("branch-moved", "warning")],
            ),
            pack=packs.read(packs.pack_dir()),
            as_of="2026-08-30T09:00:12Z",
            expect_target="vvonkledge/siana",
        )
        summary = store.summary("4bf92f3577b34da6a3ce929d0e0e4736")
        expired = store.expire_spans(as_of="2026-12-01T00:00:00Z")

Three rules hold everywhere in here, and each is enforced by the representation rather
than by a note in a review checklist:

* **Evidence, never truth.** Nothing recorded here states a business or a technical
  fact. A trace names L1 and L2 nodes and asserts nothing about them, and no path
  through this package writes to the curated graph, the observed graph, an accepted
  capture or a committed pack. See ontology/shapes/trace.ttl.
* **Structure, never payload.** There is no field and no column for a prompt, a
  completion, a tool argument, a tool result, a body, an environment or a blob, and no
  free-form attribute one could arrive under instead. See ``model`` and ``store``.
* **Written once.** A run is recorded whole or not at all, never updated, and never
  selectively deleted. The one narrow exception is retention, which removes full span
  detail older than ninety days and keeps every rollup indefinitely. The API offers no
  way to edit a record and the schema refuses an ordinary UPDATE or DELETE as well, so
  the guarantee does not depend on everyone using the front door - but a local SQLite
  file cannot defend itself from whoever owns it, and ``store`` says exactly where that
  line falls.

See docs/l3-execution-trace.md.
"""

from semantic_layer.trace.model import (
    FINDING_SEVERITIES,
    METRIC_UNITS,
    OUTCOME_STATUSES,
    SPAN_KINDS,
    SPAN_STATUSES,
    Finding,
    Metric,
    Run,
    Span,
    TraceError,
    validate,
)
from semantic_layer.trace.project import summary
from semantic_layer.trace.store import (
    RETENTION_DAYS,
    PackBinding,
    RunRecord,
    TraceStore,
    retention_horizon,
)

__all__ = [
    "FINDING_SEVERITIES",
    "METRIC_UNITS",
    "OUTCOME_STATUSES",
    "RETENTION_DAYS",
    "SPAN_KINDS",
    "SPAN_STATUSES",
    "Finding",
    "Metric",
    "PackBinding",
    "Run",
    "RunRecord",
    "Span",
    "TraceError",
    "TraceStore",
    "retention_horizon",
    "summary",
    "validate",
]
