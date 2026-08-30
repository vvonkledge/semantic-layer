"""The one document every invocation writes, and the three exit codes it comes with.

A consumer of this command is another program. It never reads a sentence, never greps
stdout, and never decides what happened from an exit code alone - so every invocation
that is not ``--help`` writes exactly one JSON document to stdout, on success and on
refusal alike, and writes nothing at all to stderr. There is no partial output: the
document is rendered once, whole, after the work either finished or was refused.

The document names its own layout first. ``schema`` and ``version`` are the two fields a
reader checks before it reads anything else, so a consumer written against version 1
refuses a version 2 document rather than reading the fields it recognizes out of it and
guessing about the rest. That is the same rule a context pack manifest follows, for the
same reason: a layout that is unstated is one a reader believes field by field.

The exit code is derived from the refusal's kind and never passed alongside it, because
the two disagreeing is the failure this whole boundary exists to prevent - a consumer
that branches on the code and a consumer that branches on the kind would take different
paths through the same answer. The kinds are closed and split on one question:

* **exit 2, the call is not one this contract defines.** The grammar did not parse, an
  option's value is not the shape the contract states for it, or the input document's
  layout is not one this reader understands. Nothing is written either way, and the two
  kinds differ in what had to be read to get there: a ``usage`` refusal happens before
  anything is opened, while an ``input`` one happens after the document was read - which
  is how its layout is known - and before any store is opened.
* **exit 1, the call was understood and the answer is no.** A pack that is stale,
  tampered with or about something else; a run this layer will not record; a path that
  is missing, is not a file, or cannot be read; a store that is locked, is at another
  schema version, or holds no such run.
* **exit 0, a complete answer.**

The line between the two failures is where the fault lies rather than how serious it is.
Exit 2 says the caller's own code is wrong and no input would have helped; exit 1 says
the call was right and the data or the state refused it.
"""

from __future__ import annotations

import json
from typing import Any

#: What layout this document is written in, and which revision of it. A consumer pins
#: both. They are versioned apart from the package version on purpose: this is the
#: contract, and it changes when the contract does rather than when the code does.
SCHEMA = "https://semantic-layer.19h09.co/cli/response"
VERSION = 1

#: Every way this command can refuse, and the exit code each one carries. One table, so
#: a kind cannot acquire a code that disagrees with what it means, and a consumer can
#: branch on either and get the same answer. See this module's docstring for the line
#: the two codes fall on.
EXIT_BY_KIND = {
    "usage": 2,
    "input": 2,
    "pack": 1,
    "trace": 1,
    "path": 1,
    "store": 1,
}

ERROR_KINDS = tuple(sorted(EXIT_BY_KIND))

OK = 0


class CommandError(Exception):
    """One refusal, named by its kind, carrying the exit code that kind means.

    Every path out of this command that is not a complete answer raises one of these,
    so the rendering below has one failure shape to write and a consumer has one to
    read. A kind not in ``EXIT_BY_KIND`` is this module's own bug and is raised as
    such rather than rendered, because a document naming a kind nothing defines is
    worse than a traceback: it looks like an answer.
    """

    def __init__(self, kind: str, message: str) -> None:
        if kind not in EXIT_BY_KIND:
            raise ValueError(f"{kind!r} is not one of {list(ERROR_KINDS)}")
        super().__init__(message)
        self.kind = kind
        self.message = message

    @property
    def status(self) -> int:
        return EXIT_BY_KIND[self.kind]


def render(document: dict[str, Any]) -> str:
    """One document, written the one way this command writes one.

    Sorted and indented rather than compact, because determinism is a property this
    boundary promises: two invocations that answer the same question write the same
    bytes, so a consumer can hash a response, diff two of them, or commit one as a
    fixture.

    ASCII, which the files this repository commits are not. A committed file is written
    by this code to a path it chose, so its encoding is settled; standard output is not.
    Python encodes it with whatever the caller's locale says, and a consumer running this
    from a daemon, a container or a cron entry commonly has no locale at all - so a
    repository name with an accent in it would raise a ``UnicodeEncodeError`` on that
    machine and answer nothing, having verified everything. JSON's escapes are lossless
    and every reader unescapes them, so the character survives and the failure mode does
    not.
    """
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def answered(command: str | None, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "command": command,
        "status": "ok",
        "result": result,
    }


def refused(command: str | None, error: CommandError) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "command": command,
        "status": "error",
        "error": {"kind": error.kind, "message": error.message},
    }
