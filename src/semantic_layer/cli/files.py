"""Every byte this process reads, read once and held to a shape before it is believed.

Two rules shape this module, and both are about the gap between deciding a file is
acceptable and reading what is in it.

**Read once.** A pack is two files, and what this command verifies, hashes and hands
back must be one set of bytes rather than three readings of the same name. Reopening a
path to export what a previous reading verified is how a caller ends up holding bytes
that were never checked, whether the swap in between was a race, a symlink repointed, or
a person editing the file. So each half is read exactly once, and every later step -
verification, the digest, the exported text - is that value and never the path again.

**Hold the descriptor, not the name.** A path is checked after it is opened, on the
descriptor that was opened, so nothing can be substituted between the check and the
read. That is what makes "a regular file" a statement about what was read rather than
about what was there a moment earlier. It cannot make the *choice* of file safe - a name
repointed before the open opens the other file, and no caller-supplied path can be
defended against that - but it does mean this command never verifies one file and
returns another.

Everything here refuses with a ``CommandError`` naming what is wrong. A traceback out of
this boundary is a bug, not an answer: a consumer parsing stdout would see a truncated
document or none at all, and could not tell a refusal from a crash.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

from semantic_layer import pack as packs
from semantic_layer.cli.response import CommandError

#: The most this command will read from any one file or from standard input. It is far
#: above anything this layer produces - the committed context pack is eight kilobytes,
#: and a run of a thousand spans is well under a megabyte - and far below what would
#: exhaust the process reading it. A boundary that reads a caller-supplied pipe with no
#: bound at all has no way to refuse a stream that never ends.
MAX_BYTES = 16 * 1024 * 1024

#: The store path that means "no file at all". It is what the suite opens, and it is
#: exactly wrong here: a process that exits leaves nothing behind, so a caller who
#: recorded a run into one would be handed an identifier for evidence that no longer
#: exists.
MEMORY_STORE = ":memory:"


def _read(descriptor: int, what: str) -> bytes:
    """Everything on an open descriptor, bounded, or a refusal saying it was too much."""
    chunks, read = [], 0
    while True:
        chunk = os.read(descriptor, 1 << 16)
        if not chunk:
            return b"".join(chunks)
        read += len(chunk)
        if read > MAX_BYTES:
            raise CommandError(
                "path",
                f"{what} is longer than {MAX_BYTES} bytes, which is more than this command "
                f"reads. Nothing this layer writes comes close to it, so a document that "
                f"large is either not the one that was meant or is not this layer's at all.",
            )
        chunks.append(chunk)


def read_file(path: Path, what: str) -> bytes:
    """One regular file, opened once and read from the descriptor that was opened."""
    try:
        # Non-blocking, because a named pipe opened for reading blocks until somebody
        # opens the other end, and this command would hang on a path it is about to
        # refuse. A regular file ignores the flag, which is the only kind that gets
        # past the check below.
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    except OSError as error:
        raise CommandError(
            "path", f"{what} at {path} could not be opened: {error.strerror}"
        ) from error
    try:
        mode = os.fstat(descriptor).st_mode
        if not stat.S_ISREG(mode):
            raise CommandError(
                "path",
                f"{what} at {path} is not a regular file. A directory, a device or a pipe "
                f"named where a file belongs is refused rather than read: what a second "
                f"read of it would return is not what the first one did, and this command "
                f"verifies exactly what it read.",
            )
        return _read(descriptor, what)
    except OSError as error:
        raise CommandError(
            "path", f"{what} at {path} could not be read: {error.strerror}"
        ) from error
    finally:
        os.close(descriptor)


def read_input(source: str) -> bytes:
    """The document a caller handed in, from a file or from standard input."""
    if source != "-":
        return read_file(Path(source), "the input document")
    # Python leaves ``sys.stdin`` as None when the process was started with descriptor
    # zero closed, which is a real way to invoke this and would otherwise be an
    # AttributeError rather than an answer.
    if sys.stdin is None:
        raise CommandError(
            "path",
            "--input is -, and this process was started with no standard input to read. "
            "Name a file, or open the stream the document is meant to arrive on.",
        )
    return _read(sys.stdin.fileno(), "the input document on standard input")


def read_pack(directory: str) -> packs.Pack:
    """Both halves of a pack, each read once, as the two byte sequences to be verified.

    The directory itself is not checked before the halves are: a missing directory and
    a directory missing a half are the same failure to a caller, and naming the half
    that is not there says more than naming the directory that is.
    """
    root = Path(directory)
    return packs.Pack(
        content=read_file(root / packs.CONTENT_NAME, "the pack content"),
        manifest=read_file(root / packs.MANIFEST_NAME, "the pack manifest"),
    )


def store_file(value: str, *, creating: bool) -> Path:
    """The store this command opens, held to being a file this caller named.

    The path is always the caller's. Nothing here reads an environment variable, a
    configuration file or a home directory to find a store, because a command that
    guesses where evidence lives writes it somewhere the caller never asked for and
    reads it back from somewhere else.

    ``creating`` says whether this command may bring a store into existence. Recording
    may: the first run written to a machine has no store to write into yet. Reading,
    projecting and expiring may not, because SQLite would answer a mistyped path by
    creating an empty database and every one of those commands would then report,
    truthfully and uselessly, that it holds no such run.
    """
    if value == MEMORY_STORE:
        raise CommandError(
            "usage",
            f"--store is {MEMORY_STORE!r}, and this command records to a file. An in-memory "
            f"store lives as long as the process holding it, so a run recorded into one from "
            f"here is gone before the answer describing it is read.",
        )
    path = Path(value)
    try:
        existing = path.stat()
    except FileNotFoundError:
        existing = None
    except OSError as error:
        raise CommandError(
            "path", f"the store at {path} could not be read: {error.strerror}"
        ) from error

    if existing is not None:
        if not stat.S_ISREG(existing.st_mode):
            raise CommandError(
                "path",
                f"the store at {path} is not a regular file. A trace store is one SQLite "
                f"file; a directory or a device named in its place is refused rather than "
                f"opened.",
            )
        return path
    if not creating:
        raise CommandError(
            "path",
            f"there is no store at {path}. This command reads a store rather than starting "
            f"one, so a path that names nothing is refused rather than answered from an "
            f"empty database that would say the run is not recorded.",
        )
    if not path.parent.is_dir():
        raise CommandError(
            "path",
            f"the store at {path} would be created in {path.parent}, which is not a "
            f"directory. Recording creates the store file and never the tree above it.",
        )
    return path
