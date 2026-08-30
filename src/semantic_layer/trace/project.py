"""Spans to a PROV-O summary: the bounded part of a trace that reaches a graph.

The span store holds the detail and the graph holds the summary, and the split is what
makes both halves work. Time-shaped access and retention do not belong in RDF files;
lineage, interoperability and the join to L1 and L2 do not belong in a SQLite table.

Two things are decided here rather than left to a reader.

**Both vocabularies are written, not one.** A run is typed ``trc:Run`` *and*
``prov:Activity``, and every edge is stated in the trace vocabulary's spelling and in
PROV-O's. That looks redundant and is not: this repository never runs a reasoner
(``semantic_layer.graph`` says why), so ``rdfs:subClassOf`` and
``rdfs:subPropertyOf`` in ontology/trace.ttl are documentation. Materializing both is
what makes the claim true in practice - a lineage, audit or compliance tool that speaks
only PROV can read a summary here with no integration work, having never been told this
vocabulary exists.

**Nothing is asserted about anything outside L3.** The summary names the pack's
observation, its source, the agent identity and whatever the run touched, and states
nothing about any of them: not a type, not a label, not a property. Naming is what a
trace is for; asserting is the one thing it may never do, and
ontology/shapes/trace.ttl refuses a summary that tries.

The projection is a function of the record and nothing else - no clock, no ordering, no
identifier minted from anything but the run's own content - so two projections of one
record are the same triples, and serializing them with
``semantic_layer.serialize.ntriples`` gives the same bytes.
"""

from __future__ import annotations

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, RDFS, XSD

from semantic_layer import ids
from semantic_layer.graph import PROV, TRACE

#: Whether a summary is for real evidence or for a fixture. Fixtures are minted under a
#: segment no recorded run ever uses, so one can never be mistaken for the other.
FIXTURE = False


def _instant(value: str) -> Literal:
    """An xsd:dateTime keeping the spelling this repository writes.

    rdflib normalizes a typed literal on construction, which rewrites the trailing Z as
    +00:00. The two mean the same instant, but a summary is hashed and compared by
    whoever receives it, so it commits to one spelling and writes it - exactly as the
    reconciler does for an observation.
    """
    return Literal(value, datatype=XSD.dateTime, normalize=False)


def summary(record, *, fixture: bool = FIXTURE) -> Graph:
    """The PROV-O summary of one recorded run.

    Takes a ``store.RunRecord`` - the run as the store holds it *now*, which after
    retention is the run without its span detail. That is the point: the summary stays
    valid and stays readable once the spans are gone, because everything a run is
    judged by afterwards is a rollup that never expires. What changes is that the
    activities are no longer there and the run says when they were removed.
    """
    run, pack = record.run, record.pack
    graph = Graph()

    def mint(kind: str, *local_id: str) -> URIRef:
        return URIRef(ids.mint_trace(kind, *local_id, fixture=fixture))

    run_iri = mint("run", run.trace_id)
    pack_iri = mint("pack", pack.identity)
    outcome_iri = mint("outcome", run.trace_id)

    ## The run.
    graph.add((run_iri, RDF.type, TRACE.Run))
    graph.add((run_iri, RDF.type, PROV.Activity))
    graph.add((run_iri, RDFS.label, Literal(f"run {run.trace_id}")))
    graph.add((run_iri, TRACE.traceId, Literal(run.trace_id)))
    graph.add((run_iri, TRACE.usedPack, pack_iri))
    graph.add((run_iri, PROV.used, pack_iri))
    graph.add((run_iri, TRACE.hasOutcome, outcome_iri))
    graph.add((run_iri, PROV.startedAtTime, _instant(run.started_at)))
    graph.add((run_iri, PROV.endedAtTime, _instant(run.ended_at)))
    if run.agent is not None:
        # Named, and nothing more. The agent identity is an L1 entity; typing it
        # prov:Agent here would be this layer asserting a business fact.
        graph.add((run_iri, PROV.wasAssociatedWith, URIRef(run.agent)))
    if record.span_detail_expired_at is not None:
        graph.add((run_iri, TRACE.spanDetailExpiredAt, _instant(record.span_detail_expired_at)))

    ## What it was told.
    graph.add((pack_iri, RDF.type, TRACE.ContextPack))
    graph.add((pack_iri, RDF.type, PROV.Entity))
    graph.add((pack_iri, RDFS.label, Literal(f"context pack {pack.identity[:16]}")))
    graph.add((pack_iri, TRACE.contentDigest, Literal(pack.content_digest)))
    graph.add((pack_iri, TRACE.manifestDigest, Literal(pack.manifest_digest)))
    graph.add((pack_iri, TRACE.packObservation, URIRef(pack.observation)))
    graph.add((pack_iri, TRACE.packSource, URIRef(pack.source)))
    graph.add((pack_iri, TRACE.packTarget, Literal(pack.target)))

    ## What it did, while the detail is still here.
    for span in run.spans:
        span_iri = mint("span", run.trace_id, span.span_id)
        graph.add((span_iri, RDF.type, TRACE.Span))
        graph.add((span_iri, RDF.type, PROV.Activity))
        graph.add((span_iri, RDFS.label, Literal(span.operation)))
        graph.add((span_iri, TRACE.spanId, Literal(span.span_id)))
        graph.add((span_iri, TRACE.ofRun, run_iri))
        graph.add((span_iri, PROV.wasInformedBy, run_iri))
        graph.add((span_iri, TRACE.operation, Literal(span.operation)))
        graph.add((span_iri, TRACE.spanKind, Literal(span.kind)))
        graph.add((span_iri, TRACE.spanStatus, Literal(span.status)))
        graph.add((span_iri, PROV.startedAtTime, _instant(span.started_at)))
        graph.add((span_iri, PROV.endedAtTime, _instant(span.ended_at)))
        if span.parent_span_id is not None:
            parent = mint("span", run.trace_id, span.parent_span_id)
            graph.add((span_iri, TRACE.parentSpan, parent))
            graph.add((span_iri, PROV.wasInformedBy, parent))
        for iri in sorted(span.touched):
            graph.add((span_iri, TRACE.touched, URIRef(iri)))

    ## What came of it, which outlives all of the above.
    graph.add((outcome_iri, RDF.type, TRACE.Outcome))
    graph.add((outcome_iri, RDF.type, PROV.Entity))
    graph.add((outcome_iri, RDFS.label, Literal(run.outcome)))
    graph.add((outcome_iri, TRACE.outcomeStatus, Literal(run.outcome)))
    graph.add((outcome_iri, PROV.wasGeneratedBy, run_iri))

    for metric in run.metrics:
        metric_iri = mint("metric", run.trace_id, metric.name)
        graph.add((metric_iri, RDF.type, TRACE.Metric))
        graph.add((metric_iri, RDF.type, PROV.Entity))
        graph.add((metric_iri, RDFS.label, Literal(metric.name)))
        graph.add((metric_iri, TRACE.ofRun, run_iri))
        graph.add((metric_iri, PROV.wasGeneratedBy, run_iri))
        graph.add((metric_iri, TRACE.metricName, Literal(metric.name)))
        graph.add((metric_iri, TRACE.metricValue, Literal(metric.value)))
        graph.add((metric_iri, TRACE.metricUnit, Literal(metric.unit)))

    for ordinal, finding in enumerate(run.findings, start=1):
        finding_iri = mint("finding", run.trace_id, str(ordinal))
        graph.add((finding_iri, RDF.type, TRACE.Finding))
        graph.add((finding_iri, RDF.type, PROV.Entity))
        graph.add((finding_iri, RDFS.label, Literal(finding.code)))
        graph.add((finding_iri, TRACE.ofRun, run_iri))
        graph.add((finding_iri, PROV.wasGeneratedBy, run_iri))
        graph.add((finding_iri, TRACE.findingCode, Literal(finding.code)))
        graph.add((finding_iri, TRACE.findingSeverity, Literal(finding.severity)))
        if finding.about is not None:
            graph.add((finding_iri, TRACE.findingAbout, URIRef(finding.about)))

    return graph
