"""The JSON a run arrives as, refused everywhere the model's closed shape would be.

``semantic_layer.trace.model`` makes a payload field impossible by making every record a
frozen dataclass with a closed set of fields. A process boundary that takes JSON is the
one way that guarantee could be given away, because JSON *is* an attribute bag: the
question this file asks, over and over, is whether some shape a caller can write reaches
the store as something the dataclasses would never have allowed.

Every refusal here is ``input`` at exit 2 - the caller's document does not match the
published layout - and every refusal here happens before a store is opened, which
tests/test_cli.py holds from the outside. What is checked in this file is which
documents are refused, and that the message says what is wrong without repeating what
was in it.
"""

import json
import math
import sys
from dataclasses import asdict

import pytest
import trace_runs

from semantic_layer.cli import run_input
from semantic_layer.cli.response import CommandError
from semantic_layer.trace import Run
from semantic_layer.trace.model import RECORD_FIELDS


def document(**over) -> dict:
    """One run as a caller would write it: JSON, so every sequence is a list.

    ``asdict`` keeps the model's tuples, and a tuple is not a shape a document can have.
    Round-tripping through JSON here means the tests below amend the same structure a
    caller sends rather than a Python-shaped approximation of it.
    """
    stated = {"schema": run_input.SCHEMA, "version": run_input.VERSION, "run": asdict(run())}
    return {**json.loads(json.dumps(stated)), **over}


def run() -> Run:
    return trace_runs.run()


def decode(payload) -> Run:
    return run_input.decode(
        payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
    )


def refusal(payload) -> str:
    with pytest.raises(CommandError) as raised:
        decode(payload)
    assert raised.value.kind == "input"
    assert raised.value.status == 2
    return raised.value.message


def amended(path: tuple, value) -> dict:
    """One document with one field changed, reached by the path that names it."""
    stated = document()
    holder = stated
    for step in path[:-1]:
        holder = holder[step]
    holder[path[-1]] = value
    return stated


def dropped(path: tuple) -> dict:
    stated = document()
    holder = stated
    for step in path[:-1]:
        holder = holder[step]
    del holder[path[-1]]
    return stated


## The document a caller is meant to write.


def test_a_whole_document_becomes_the_run_it_describes():
    """The round trip, which is the only reason any of the refusals below are worth it."""
    assert decode(document()) == run()


def test_every_field_of_every_record_has_a_shape():
    """A field added to a dataclass without a rule here is a failing build, not a surprise.

    ``RECORD_FIELDS`` is the model's own list of what a run may be written down as, and
    the decoder reads its required-ness straight off the dataclasses. What it cannot read
    off them is which JSON shape each field arrives in, so that table is written out - and
    this is what stops it falling behind the thing it describes.
    """
    named = {field for fields in RECORD_FIELDS.values() for field in fields}
    assert set(run_input.SHAPES) == named


def test_the_fields_a_record_defaults_may_be_left_out():
    stated = document()
    del stated["run"]["agent"]
    del stated["run"]["metrics"]
    del stated["run"]["findings"]
    for span in stated["run"]["spans"]:
        span.pop("touched", None)
        if span["parent_span_id"] is None:
            del span["parent_span_id"]
    decoded = decode(stated)
    assert decoded.agent is None
    assert decoded.metrics == () and decoded.findings == ()


## The layout, refused before anything in it is read.


@pytest.mark.parametrize(
    "payload",
    [b"", b"{", b"not json at all", b"[1, 2, 3]", b'"a string"', b"null", b"\xff\xfe{}"],
    ids=["nothing", "half an object", "prose", "a list", "a string", "null", "not utf-8"],
)
def test_a_document_that_is_not_an_object_of_json_is_refused(payload):
    refusal(payload)


def test_a_document_declaring_another_layout_is_refused():
    assert "schema" in refusal(amended(("schema",), "https://example.com/other"))


@pytest.mark.parametrize("version", [2, 0, "1", 1.0, True, None], ids=repr)
def test_a_document_declaring_another_revision_is_refused(version):
    refusal(amended(("version",), version))


@pytest.mark.parametrize(
    "payload",
    [{"schema": run_input.SCHEMA, "version": run_input.VERSION}, document(extra="anything")],
    ids=["missing the run", "carrying a field nothing reads"],
)
def test_the_top_level_is_exactly_a_layout_and_a_run(payload):
    refusal(payload)


def test_a_key_written_twice_is_refused():
    """json.loads keeps the last of two and says nothing; two of one key is two claims."""
    text = json.dumps(document())
    doubled = text.replace('"outcome": "succeeded"', '"outcome": "succeeded", "outcome": "failed"')
    assert "twice" in refusal(doubled.encode("utf-8"))


def test_a_key_written_twice_deep_inside_is_refused():
    text = json.dumps(document())
    doubled = text.replace('"unit": "count"', '"unit": "count", "unit": "byte"', 1)
    refusal(doubled.encode("utf-8"))


def test_a_document_nested_past_the_parser_is_refused():
    """Valid JSON the parser gives up on rather than rejects, which is a third thing.

    A `RecursionError` is neither a `JSONDecodeError` nor anything this boundary catches,
    so before this it left the command as a traceback on the stream that is promised to
    stay empty, with nothing at all on stdout. A run is a handful of levels deep, so
    nothing that exhausts a parser is one.
    """
    depth = sys.getrecursionlimit() * 20
    nested = f'{{"schema": "{run_input.SCHEMA}", "version": 1, "run": '
    nested += "[" * depth + "]" * depth + "}"
    assert "nested deeper" in refusal(nested.encode("utf-8"))


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_a_number_json_does_not_define_is_refused(constant):
    """A measurement that is not finite cannot be counted, compared or serialized twice."""
    text = json.dumps(document()).replace('"value": 2', f'"value": {constant}', 1)
    assert constant in refusal(text.encode("utf-8"))
    assert math.isnan(float("nan"))  # the value this refuses never reaches Python at all


## Unknown keys, at every level.


@pytest.mark.parametrize(
    "path",
    [
        ("run", "prompt"),
        ("run", "spans", 0, "tool_result"),
        ("run", "metrics", 0, "body"),
        ("run", "findings", 0, "description"),
    ],
    ids=["on the run", "on a span", "on a metric", "on a finding"],
)
def test_a_field_nobody_reviewed_is_refused_rather_than_ignored(path):
    stated = document()
    holder = stated
    for step in path[:-1]:
        holder = holder[step]
    holder[path[-1]] = "everything the agent was told"
    message = refusal(stated)
    assert path[-1] in message
    assert "everything the agent was told" not in message


## Shapes, at every level.


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("run", "trace_id"), 1),
        (("run", "trace_id"), None),
        (("run", "outcome"), {"status": "succeeded"}),
        (("run", "agent"), ["one", "two"]),
        (("run", "spans"), {"first": {}}),
        (("run", "spans", 0), "a span"),
        (("run", "spans", 0, "operation"), {"prompt": "..."}),
        (("run", "spans", 0, "touched"), "one thing"),
        (("run", "spans", 0, "touched"), [{"iri": "..."}]),
        (("run", "metrics", 0, "value"), "2"),
        (("run", "metrics", 0, "value"), 2.5),
        (("run", "metrics", 0, "value"), True),
        (("run", "findings", 0, "severity"), 3),
        (("run", "findings", 0, "about"), {"iri": "..."}),
    ],
    ids=[
        "a number where a trace id belongs",
        "null where a trace id belongs",
        "an object where an outcome belongs",
        "a list where an agent belongs",
        "an object where the spans belong",
        "text where a span belongs",
        "an object where a name belongs",
        "text where a list of references belongs",
        "an object inside a list of references",
        "text where a measurement belongs",
        "a fraction where a whole number belongs",
        "true where a measurement belongs",
        "a number where a severity belongs",
        "an object where a reference belongs",
    ],
)
def test_a_value_of_another_shape_is_refused(path, value):
    refusal(amended(path, value))


def test_a_refusal_names_the_shape_and_never_the_value():
    """What arrived is the interesting fact; what was in it is what this layer never writes."""
    payload = "the model was asked to summarize the following customer record"
    message = refusal(amended(("run", "metrics", 0, "value"), payload))
    assert payload not in message
    assert "text" in message


## Partial records.


@pytest.mark.parametrize(
    "path",
    [
        ("run", "trace_id"),
        ("run", "started_at"),
        ("run", "ended_at"),
        ("run", "outcome"),
        ("run", "spans"),
    ],
    ids=["no trace id", "no start", "no end", "no outcome", "no spans"],
)
def test_a_run_missing_a_field_it_has_no_default_for_is_refused(path):
    assert path[-1] in refusal(dropped(path))


@pytest.mark.parametrize(
    "field", ["span_id", "operation", "kind", "status", "started_at", "ended_at"]
)
def test_a_span_missing_a_field_it_has_no_default_for_is_refused(field):
    refusal(dropped(("run", "spans", 0, field)))


@pytest.mark.parametrize("field", ["name", "value", "unit"])
def test_a_metric_missing_a_field_is_refused(field):
    refusal(dropped(("run", "metrics", 0, field)))


@pytest.mark.parametrize("field", ["code", "severity"])
def test_a_finding_missing_a_field_is_refused(field):
    refusal(dropped(("run", "findings", 0, field)))


## What this module does not decide.


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("run", "trace_id"), "4BF92F3577B34DA6A3CE929D0E0E4736"),
        (("run", "outcome"), "exploded"),
        (("run", "spans", 0, "kind"), "wherever"),
        (("run", "started_at"), "2026-08-30 09:00:00"),
        (("run", "metrics", 0, "name"), "a name with spaces"),
        (("run", "spans", 0, "touched"), ["https://example.com/anything"]),
    ],
    ids=[
        "an id in the wrong case",
        "an outcome outside the closed set",
        "a span kind outside the closed set",
        "an instant spelled another way",
        "a name that is not a slug",
        "a reference this layer did not mint",
    ],
)
def test_content_the_model_owns_is_converted_here_and_refused_there(path, value):
    """Layout is this module's; what a run may say is the model's, and stays there.

    Each of these is a well-formed document carrying a value the model refuses. It
    converts cleanly - which is the point - and is then refused by ``model.validate``
    with the sentence that already exists for it, rather than by a second rule written
    here that would have to be kept in step with the first.
    """
    from semantic_layer.trace import TraceError, validate

    converted = decode(amended(path, value))
    with pytest.raises(TraceError):
        validate(converted)
