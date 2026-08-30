"""The closed JSON a run arrives as, and why it is not ``Run(**document)``.

``semantic_layer.trace.model`` spends its whole docstring explaining that a trace has no
attribute bag: every record is a frozen dataclass with a closed set of fields, so a
prompt or a tool result cannot arrive under a key nobody reviewed. That guarantee is
worth exactly as much as the thinnest way into it, and this module is now the thinnest
way into it - a process boundary that takes JSON somebody else wrote.

JSON is an attribute bag. Splatting one into a dataclass gets most of the way there,
because an unknown keyword is a ``TypeError``, but only the top level: nothing about
``Run(**document)`` stops ``spans`` being a list of dictionaries that are never held to
anything, or ``touched`` holding an object, or a metric value arriving as ``true``,
which Python counts as the integer 1. So the conversion here is closed and explicit at
every level. Each record is built field by field from the fields its dataclass declares,
each value is held to the one JSON shape that field is written in, and anything else is
refused by name before a store is opened.

What this module holds, and what it deliberately does not:

* **Layout, which is this contract's.** Whether the document is JSON at all, whether it
  declares a layout this reader knows, whether every key is one of the fields the model
  declares, whether a key was written twice, and whether each value is text, a whole
  number, a list or null. All of it is refused as ``input``, at exit 2, because a
  caller whose serializer emits it has a bug that no data would have fixed.
* **Content, which is the model's.** Whether the trace id is thirty-two hex characters,
  whether the outcome is one of the three, whether the spans form one tree, whether a
  reference is an identifier this layer mints. None of that is re-implemented here: the
  document is converted into the model's own records and ``model.validate`` refuses it,
  with the sentence it already writes, at exit 1.

The split is what keeps the two from drifting. There is one place that says what a run
may be, and this is not it - this says only what one looks like written down.
"""

from __future__ import annotations

import json
from dataclasses import MISSING
from dataclasses import fields as declared_fields

from semantic_layer.cli.response import CommandError
from semantic_layer.trace import Finding, Metric, Run, Span

#: What layout an input document is written in, and which revision of it. Stated by the
#: caller and held exactly, so a document written for a later contract is refused rather
#: than read as though it were this one - the same rule the response document and a pack
#: manifest follow.
SCHEMA = "https://semantic-layer.19h09.co/cli/run"
VERSION = 1

#: The whole of the top level. Three fields: the two that name the layout, and the run.
TOP_LEVEL_FIELDS = frozenset({"schema", "version", "run"})


def _refuse(what: str, why: str) -> CommandError:
    return CommandError("input", f"{what} {why}")


def _text(value, what: str) -> str:
    if not isinstance(value, str):
        raise _refuse(what, f"is {_shown(value)}, and this reads text there.")
    return value


def _text_or_null(value, what: str) -> str | None:
    if value is None:
        return None
    return _text(value, what)


def _whole_number(value, what: str) -> int:
    # bool is an int in Python, and `true` is neither a count nor a layout version.
    if not isinstance(value, int) or isinstance(value, bool):
        raise _refuse(what, f"is {_shown(value)}, and this reads a whole number there.")
    return value


def _text_list(value, what: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise _refuse(what, f"is {_shown(value)}, and this reads a list there.")
    return tuple(_text(item, f"{what} entry {index}") for index, item in enumerate(value, start=1))


def _records(record, label: str):
    """A list of one kind of record, each converted by the rules its dataclass declares."""

    def hold(value, what: str) -> tuple:
        if not isinstance(value, list):
            raise _refuse(what, f"is {_shown(value)}, and this reads a list there.")
        return tuple(
            _record(record, item, f"{label} {index}") for index, item in enumerate(value, start=1)
        )

    return hold


#: How each field of each record arrives, by the name the model gives it. The names are
#: unique across the four records, and where two records share one - a start, an end -
#: they share its shape as well, so one flat table says it all and there is no second
#: place for a rule to be written differently. Every field of every record has an entry
#: and nothing else does, which tests/test_cli_run_input.py holds against
#: ``model.RECORD_FIELDS`` so a field added to a dataclass without a shape here fails
#: the build rather than being refused at runtime as unknown.
SHAPES = {
    "trace_id": _text,
    "started_at": _text,
    "ended_at": _text,
    "outcome": _text,
    "agent": _text_or_null,
    "spans": _records(Span, "span"),
    "metrics": _records(Metric, "metric"),
    "findings": _records(Finding, "finding"),
    "span_id": _text,
    "parent_span_id": _text_or_null,
    "operation": _text,
    "kind": _text,
    "status": _text,
    "touched": _text_list,
    "name": _text,
    "value": _whole_number,
    "unit": _text,
    "code": _text,
    "severity": _text,
    "about": _text_or_null,
}


def _shown(value) -> str:
    """One rejected value, named by its JSON type and never printed back.

    A refusal names the shape that arrived rather than what was in it, because what
    arrived is the caller's data and this message goes to a log. A field that was meant
    to be a name and turned up as an object is the interesting fact; the object's
    contents are the thing this layer exists not to write down.
    """
    if value is None:
        return "null"
    return {bool: "a boolean", int: "a number", float: "a number", str: "text"}.get(
        type(value), "a list" if isinstance(value, list) else "an object"
    )


def _record(record, value, what: str):
    """One record, built from exactly the fields its dataclass declares.

    Required-ness is read off the dataclass rather than restated: a field with a default
    may be left out and a field without one may not, so the document and the model agree
    about what a whole record is by construction.
    """
    if not isinstance(value, dict):
        raise _refuse(what, f"is {_shown(value)}, and this reads an object there.")
    fields = {field.name: field for field in declared_fields(record)}
    unknown = sorted(set(value) - set(fields))
    if unknown:
        raise _refuse(
            what,
            f"carries {unknown}, and a {record.__name__} has {sorted(fields)}. An unknown key "
            f"is refused rather than ignored: a field nobody reviewed is how a prompt, a tool "
            f"result or an environment arrives in an append-only history.",
        )
    given = {}
    for name, field in fields.items():
        if name in value:
            given[name] = SHAPES[name](value[name], f"{what}'s {name}")
        elif field.default is MISSING and field.default_factory is MISSING:
            raise _refuse(
                what,
                f"states no {name}, and a {record.__name__} is recorded whole. A record "
                f"missing a field it has no default for is a partial one, and partial "
                f"evidence is worse than none.",
            )
    return record(**given)


def _pairs(pairs: list[tuple[str, object]]) -> dict:
    """One JSON object, refused if it wrote a key twice.

    ``json.loads`` keeps the last of two keys and says nothing, so a document carrying
    ``"outcome": "succeeded"`` twice - once as the caller meant it and once as something
    else appended it - would be read as whichever came last. Two of one key is two
    claims, and this reader will not pick between them.
    """
    seen = {}
    for key, value in pairs:
        if key in seen:
            raise _refuse(f"the key {key!r}", "is written twice in one object.")
        seen[key] = value
    return seen


def _constant(name: str):
    raise _refuse(
        f"the value {name}",
        "is not a number JSON defines. A measurement that is not finite cannot be counted, "
        "compared or serialized to the same bytes twice.",
    )


def decode(document: bytes) -> Run:
    """One input document, converted into the run the model will be asked to validate."""
    try:
        text = document.decode("utf-8")
    except UnicodeDecodeError as error:
        raise _refuse("the input document", f"is not UTF-8: {error}") from error
    try:
        stated = json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)
    except json.JSONDecodeError as error:
        raise _refuse("the input document", f"is not valid JSON: {error}") from error

    if not isinstance(stated, dict):
        raise _refuse("the input document", f"is {_shown(stated)}, and this reads an object.")
    fields = set(stated)
    if fields != TOP_LEVEL_FIELDS:
        raise _refuse(
            "the input document",
            f"carries {sorted(fields - TOP_LEVEL_FIELDS)} that this reader has no rule for and "
            f"lacks {sorted(TOP_LEVEL_FIELDS - fields)}. It is exactly a layout and a run.",
        )
    if _text(stated["schema"], "the document's schema") != SCHEMA:
        raise _refuse(
            "the input document",
            f"declares the schema {stated['schema']!r} and this reader reads {SCHEMA!r}.",
        )
    if _whole_number(stated["version"], "the document's version") != VERSION:
        raise _refuse(
            "the input document",
            f"declares version {stated['version']!r} and this reader understands {VERSION}. A "
            f"document written for another revision is refused rather than reinterpreted.",
        )
    return _record(Run, stated["run"], "the run")
