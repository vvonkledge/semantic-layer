"""The one place in this repository that touches the network, and never at test time.

Everything else reads committed files. This reads the public GitHub API for exactly
one repository, projects the response onto the contract in ``github.py``, and writes
the result where a human can review it as a diff. It is one-way in the strongest
sense: there is no request here that is not a GET, and nothing that could authorize
one - no token is read from the environment, no credential is accepted as an argument,
and no header carrying either is ever set. An unauthenticated read of a public
repository is the whole of what this is allowed to do, and it is also the whole of
what the trust basis it writes down claims.

Failure is the interesting half. A network error, a rate limit, a 404, malformed JSON,
a response that has drifted from the contract, or a pagination chain that stops early
must all leave the last accepted observation exactly as it was. So nothing is written
until everything has been read, projected and hashed, and every failure before that
point leaves the working tree untouched and says what happened.

What is written is two files, and two renames are not one. A capture writes the
snapshot and then its digest, each atomically, and a process killed between the two
leaves a new snapshot beside the old digest. That state is not silent and is not
believed: the pair no longer agrees, ``github.read_snapshot`` refuses it by name
before anything is reconciled, and the accepted graph and the context pack - which are
written by other commands, from a snapshot that passed that check - cannot move
because of it. See ``write_snapshot`` for the contract as it actually stands and for
the recovery.

There is no promote step in code, because git already is one. A capture lands as an
uncommitted diff; it becomes accepted L2 truth when that diff is reviewed and merged,
the same way a business fact does (docs/evolution.md).
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path

from semantic_layer import github

API_ROOT = "https://api.github.com"

#: Which installation of the provider this is, as a slug. Half of the scope every
#: identifier from this source is minted under, so it is written down rather than
#: assumed: a GitHub Enterprise host issues the same numeric ids for different things.
INSTANCE = "api-github-com"

#: How long an observation of this source is worth believing. Twenty-four hours is a
#: judgement about how fast repository metadata moves and how stale an answer may be
#: before a consumer should go and look again; it is written into every observation, so
#: changing it changes nothing already committed.
FRESHNESS_SECONDS = 86400

#: What a consumer is being asked to believe, and what they are not. It travels with
#: every context pack, so it is written for someone deciding whether this is good
#: enough for what they are about to do.
TRUST_BASIS = (
    "Unauthenticated GET of the public GitHub REST API, captured in full and hashed. "
    "It is what GitHub showed an anonymous caller at the observation instant and "
    "nothing more: no private repository, no protection rule, no permission and no "
    "field this contract does not read. It says what the repository was, never what "
    "the organization is accountable for."
)

#: A safety net, not a policy: the target is locked and the paths are built here, so a
#: run that walks past this many pages is a bug or a loop rather than a large answer.
MAX_PAGES = 20

PER_PAGE = 100

#: `Link: <...>; rel="next"`, which is how GitHub says there is more.
NEXT_LINK = re.compile(r'<([^>]+)>\s*;\s*rel="next"')

USER_AGENT = "semantic-layer/0.1 (+https://semantic-layer.19h09.co)"


class AcquisitionError(RuntimeError):
    """A capture could not be completed, and says what stopped it."""


#: What a reader hands back: the status, the headers, and the body. Injected so every
#: failure below is exercised by the suite without a socket.
Reader = Callable[[str], tuple[int, Mapping[str, str], bytes]]


def read_url(url: str) -> tuple[int, Mapping[str, str], bytes]:
    """One GET, with no credential and no way to attach one."""
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": USER_AGENT,
        },
    )
    # Checked before the request is opened, not after it is built: every URL here is
    # constructed from the locked target or read from GitHub's own pagination header,
    # and this is what stops either of those becoming a file: or an http: read.
    if request.type != "https":
        raise AcquisitionError(f"{url} is not an https URL")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers or {}), error.read()
    except OSError as error:
        raise AcquisitionError(
            f"GET {url} did not complete: {error}. Nothing was written; the last accepted "
            f"observation is untouched."
        ) from error


def _fail_for(url: str, status: int, headers: Mapping[str, str]) -> AcquisitionError:
    remaining = headers.get("x-ratelimit-remaining") or headers.get("X-RateLimit-Remaining")
    reset = headers.get("x-ratelimit-reset") or headers.get("X-RateLimit-Reset")
    if status in (403, 429) and remaining == "0":
        return AcquisitionError(
            f"GET {url} was rate limited by GitHub (HTTP {status}; the quota resets at unix "
            f"time {reset}). This capture reads anonymously and has no way to raise the "
            f"limit, so the answer is to wait. Nothing was written."
        )
    if status in (401, 403):
        return AcquisitionError(
            f"GET {url} was refused (HTTP {status}). This capture sends no credential by "
            f"design, so a refusal means the resource is not public - which is an answer "
            f"about the resource, not a reason to authenticate. Nothing was written."
        )
    if status == 404:
        return AcquisitionError(
            f"GET {url} was not found (HTTP 404). Either the target no longer exists at that "
            f"path or it is no longer public. Both are real changes and neither is an empty "
            f"answer, so nothing was written."
        )
    return AcquisitionError(
        f"GET {url} returned HTTP {status}, which this capture does not read. Nothing was "
        f"written; the last accepted observation is untouched."
    )


def _get(url: str, reader: Reader):
    status, headers, body = reader(url)
    if status != 200:
        raise _fail_for(url, status, headers)
    try:
        return json.loads(body), headers
    except json.JSONDecodeError as error:
        raise AcquisitionError(
            f"GET {url} returned HTTP 200 with a body that is not JSON: {error}. A response "
            f"nothing can parse is not an empty answer. Nothing was written."
        ) from error


def _get_all(url: str, reader: Reader) -> tuple[list, int]:
    """Every page of a collection, or an error - never the pages that did arrive."""
    items: list = []
    pages = 0
    next_url: str | None = url
    while next_url is not None:
        pages += 1
        if pages > MAX_PAGES:
            raise AcquisitionError(
                f"following pagination from {url} passed {MAX_PAGES} pages. Nothing was "
                f"written: a collection this size is not what this source was scoped for, "
                f"and committing a prefix of it would look like the whole answer."
            )
        page, headers = _get(next_url, reader)
        if not isinstance(page, list):
            raise AcquisitionError(f"GET {next_url} returned {type(page).__name__}, not a list")
        items += page
        link = headers.get("link") or headers.get("Link") or ""
        match = NEXT_LINK.search(link)
        next_url = match.group(1) if match else None
        if next_url is not None and not next_url.startswith(f"{API_ROOT}/"):
            raise AcquisitionError(
                f"GitHub's pagination pointed at {next_url}, which is not under {API_ROOT}. "
                f"Nothing was written."
            )
    return items, pages


def _project(payload: Mapping, fields, where: str) -> dict:
    """``payload`` narrowed to the contract, refusing anything the contract requires and
    the source did not send.

    This is where the response stops being GitHub's shape and becomes ours. Projecting
    rather than storing the whole body is what makes the committed snapshot reviewable,
    what keeps a field nobody chose out of the graph, and what makes schema drift an
    error at capture time rather than a surprise at reconcile time.
    """
    if not isinstance(payload, Mapping):
        raise AcquisitionError(f"{where} is {type(payload).__name__}, not an object")
    missing = sorted(set(fields) - set(payload))
    if missing:
        raise AcquisitionError(
            f"{where} is missing {missing}, which this contract reads. GitHub's response has "
            f"drifted from what was agreed; that is a decision about the contract, not "
            f"something to fill in. Nothing was written."
        )
    return {key: payload[key] for key in sorted(fields)}


def capture(
    *,
    target: str = github.TARGET,
    observed_at: str | None = None,
    reader: Reader = read_url,
) -> dict:
    """Read the source and return a snapshot, or raise having written nothing."""
    if target != github.TARGET:
        raise AcquisitionError(
            f"this source is locked to {github.TARGET!r} and was asked for {target!r}. "
            f"Observing a second repository is a decision, and it is made by adding a source "
            f"with its own contract, capture and fixtures - not by passing a different name "
            f"to this one."
        )
    if observed_at is None:
        observed_at = datetime.now(UTC).strftime(github.INSTANT_FORMAT)

    repository, _ = _get(f"{API_ROOT}/repos/{target}", reader)
    branches, pages = _get_all(f"{API_ROOT}/repos/{target}/branches?per_page={PER_PAGE}", reader)

    projected = _project(repository, github.REPOSITORY_FIELDS, "the repository response")
    projected["owner"] = _project(
        repository["owner"], github.OWNER_FIELDS, "the repository response's owner"
    )

    items = []
    for index, branch in enumerate(branches):
        entry = _project(branch, github.BRANCH_FIELDS, f"branch {index}")
        entry["commit"] = _project(
            branch["commit"], github.BRANCH_COMMIT_FIELDS, f"branch {index}'s commit"
        )
        items.append(entry)

    return {
        "snapshot_version": github.SNAPSHOT_VERSION,
        "provider": github.PROVIDER,
        "instance": INSTANCE,
        "api_root": API_ROOT,
        "target": target,
        "trust_basis": TRUST_BASIS,
        "observed_at": observed_at,
        "freshness_seconds": FRESHNESS_SECONDS,
        "repository": projected,
        "branches": {"complete": True, "pages": pages, "items": items},
    }


def render(snapshot: Mapping) -> bytes:
    """A snapshot as the bytes that get hashed and committed.

    Sorted keys and a fixed indent, so two captures of an unchanged repository differ
    only where the repository did.
    """
    return (json.dumps(snapshot, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()


def write_atomically(path: Path, payload: bytes) -> None:
    """Replace ``path`` with ``payload`` in one step, or not at all.

    A capture that dies midway must leave the last accepted bytes in place, so the new
    ones are written to a temporary file in the same directory - the same filesystem,
    so the rename is atomic - and moved over the old ones only once they are complete
    and on disk.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(dir=path.parent, delete=False, suffix=".partial")
    try:
        with handle as temporary:
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(handle.name, path)
    except BaseException:
        Path(handle.name).unlink(missing_ok=True)
        raise


def write_snapshot(snapshot: Mapping, path: Path) -> str:
    """Commit a captured snapshot to disk with its digest, and return the digest.

    Two files, written in one order and each atomically. The pair is not a transaction
    and this does not claim to be one: two renames cannot be made into one without a
    second mutable truth - an index, a lock, a journal - and adding one to hold two
    files honest would be a bigger thing to keep true than the two files are.

    What is guaranteed instead is that no interruption is believed. Killed before the
    snapshot lands, both files are the last accepted observation and nothing changed.
    Killed between the two, the snapshot is new and the digest still commits the old
    bytes, so ``github.read_snapshot`` refuses the pair by name and no reconcile, graph
    or pack is built from it. Recovery is a person's, and it is one of two commands: run
    `just capture` again, or `git checkout` the pair - a capture writes into a git
    working tree, so the last accepted observation is still there to return to.
    """
    payload = render(snapshot)
    digest = github.digest_of(payload)
    write_atomically(path, payload)
    write_atomically(path.with_name(path.name + ".sha256"), f"{digest}\n".encode())
    return digest


def main() -> None:
    path = github.snapshot_path()
    snapshot = capture()
    digest = write_snapshot(snapshot, path)
    print(f"captured {snapshot['target']} at {snapshot['observed_at']}")
    print(f"  {path}")
    print(f"  {digest}")
    print("Run `just reconcile`, then review the diff before committing it.")


if __name__ == "__main__":
    main()
