"""What a wheel carries, and whether the command works when that is all there is.

Every other test in this suite runs against the checkout, where `ontology/` is sitting
two directories above the code and every path resolves whether or not anything was
packaged. That makes a green suite silent on the question a consumer actually has: does
this work once it is installed? A missing resource is invisible in an editable install
by construction, because the editable install is the checkout.

So this file does not take the checkout's word for anything. It builds the wheel with
the same backend that builds it for release, reads what is inside it, then installs it
into a virtual environment of its own and runs every command from a working directory
outside this repository with an environment that carries nothing from this one. What
passes here passes for somebody who has only ever run ``pip install semantic-layer``.

It stays offline like the rest of the suite, and it is careful about how. Installing a
wheel and running the installed command are two different questions, and only the second
one is this project's boundary:

* **Installing** has to put the wheel's declared runtime dependencies somewhere the
  command can import them. This file does that from the distributions this interpreter
  already has, because they are certainly here - the suite imports rdflib and pyshacl to
  run at all. It does not resolve them, so it needs no index, no network and no cache;
  every uv command below is handed a uv cache created empty by this session, which is
  the condition a clean Linux runner installs under.
* **Running** must reach the network from nowhere, and that is proved rather than
  implied: the installed environment has connecting and resolving taken away from it,
  the way `tests/conftest.py` takes this process's socket away, and a test below shows
  the refusal firing in the environment the commands run in.

An earlier version of this file installed with ``uv pip install --offline`` and let uv
resolve the dependencies out of whatever the machine's global cache happened to hold.
That passed wherever somebody had installed these packages by name before and failed on
both clean CI runners, where ``uv run --frozen`` fills the cache with the locked
artifacts and nothing that a resolver could search. It failed as five identical
``CalledProcessError`` lines with uv's actual refusal captured and discarded, which is
why every command started here reports what it printed.
"""

import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from collections.abc import Iterable
from email import message_from_string
from importlib import metadata
from pathlib import Path

import pytest
import trace_runs

from semantic_layer import graph
from semantic_layer import pack as packs
from semantic_layer.cli import response, run_input

#: Where the vocabularies and shapes live inside the wheel. ``graph.PACKAGED_ONTOLOGY``
#: is the reader of this and this is the writer's side of the same fact.
PACKAGED = "semantic_layer/_ontology"

#: What no wheel may carry. Every one of these is either this installation's own content
#: or the evidence of a run, and a wheel is something anybody can install: shipping one
#: site's captured responses, accepted observations or trace store to everybody who
#: installs the library is a different mistake each time and the same rule.
NEVER_PACKAGED = ("packs/", "sources/", "instances", ".sqlite3", ".env", "queries/", "tests/")


@pytest.fixture(scope="session")
def wheel(tmp_path_factory) -> Path:
    """The wheel, built by the backend pyproject.toml names, from this working tree."""
    from hatchling.build import build_wheel

    out = tmp_path_factory.mktemp("wheel")
    with contextlib.chdir(graph.ROOT):
        name = build_wheel(str(out))
    return out / name


@pytest.fixture(scope="session")
def carried(wheel) -> dict[str, bytes]:
    with zipfile.ZipFile(wheel) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


## What is in the wheel.


def _vocabularies() -> list[Path]:
    """Every Turtle file the library itself reads: the vocabularies and the shapes.

    Found by looking rather than listed, so a shapes file added to the repository
    without a line in pyproject.toml fails here instead of failing in somebody's
    installation.
    """
    checkout = graph.ROOT / "ontology"
    return sorted(
        path for path in checkout.rglob("*.ttl") if not path.is_relative_to(checkout / "instances")
    )


def test_every_vocabulary_and_shape_is_in_the_wheel(carried):
    for path in _vocabularies():
        name = f"{PACKAGED}/{path.relative_to(graph.ROOT / 'ontology')}"
        assert name in carried, f"{path.name} is not packaged; add it to force-include"
        assert carried[name] == path.read_bytes()


def test_the_wheel_carries_no_site_content(carried):
    for name in carried:
        for forbidden in NEVER_PACKAGED:
            assert forbidden not in name, f"the wheel carries {name}"


def test_the_command_is_declared_as_an_entry_point(carried):
    entry_points = next(name for name in carried if name.endswith("entry_points.txt"))
    assert "semantic-layer = semantic_layer.cli:main" in carried[entry_points].decode()


def test_the_packaged_location_is_the_one_the_library_reads():
    """One fact, written in pyproject.toml and read in graph.py, held against itself."""
    assert graph.PACKAGED_ONTOLOGY.name == Path(PACKAGED).name
    assert graph.PACKAGED_ONTOLOGY.parent.name == "semantic_layer"


def test_the_checkout_reads_the_checkout():
    """The fallback is what makes a checkout work, and it is worth saying it is in use.

    Nothing is packaged into `src/`, so a test run here reads `ontology/` at the root.
    That is exactly why the wheel is built and installed below rather than believed.
    """
    assert not graph.PACKAGED_ONTOLOGY.exists()
    assert graph.ONTOLOGY == graph.ROOT / "ontology"


## Building the installation the commands are run out of.

#: The head of a `Requires-Dist:` line, which is all of it this file needs: the version
#: range was already settled by whoever installed this environment, and re-checking it
#: here would be asking the lock a question the lock has answered.
_REQUIREMENT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")

#: Taken away from the installed environment, so that "this reaches no network" is a
#: thing the commands below run under rather than a thing a flag on the installer
#: implies. Python imports `sitecustomize` at interpreter startup, so it reaches the
#: installed command however that command is invoked. `tests/conftest.py` does the same
#: to this process; neither reaches the other, because a subprocess gets its own socket
#: module and that is the whole reason this exists.
#:
#: What is refused is reaching somewhere, not holding a socket object. Replacing the
#: class the way conftest.py does is safe there only because `ssl` was imported long
#: before the fixture ran; at interpreter startup it is not, and `ssl.SSLSocket`
#: subclasses whatever `socket.socket` is by then. Denying the three calls that turn a
#: socket into a connection is both the narrower change and the closer statement of
#: what this environment is not allowed to do.
_NO_SOCKETS = '''\
"""Refuse a connection. Written into this environment by tests/test_packaging.py."""

import socket


def _refuse(*_args, **_kwargs):
    raise RuntimeError("the installed command tried to reach the network")


socket.socket.connect = _refuse
socket.socket.connect_ex = _refuse
socket.create_connection = _refuse
socket.getaddrinfo = _refuse
'''


@pytest.fixture(scope="session")
def uv() -> str:
    executable = shutil.which("uv")
    assert executable, "uv builds and runs this project; the suite needs it on PATH"
    return executable


@pytest.fixture(scope="session")
def cold_cache(tmp_path_factory) -> Path:
    """A uv cache with nothing in it, which is what a clean runner installs against.

    Handed to every uv command in this file. Anything here that started needing a
    package it had not been given fails on every machine rather than only on the ones
    whose global cache happens to be cold, which is the failure this arrangement is
    the repair for.
    """
    cache = tmp_path_factory.mktemp("uv-cache")
    assert not any(cache.iterdir()), f"{cache} was supposed to be empty"
    return cache


def _uv(uv: str, cold_cache: Path, *argv: str) -> None:
    """One uv command, reporting what it printed rather than only what it exited with.

    ``subprocess.run(check=True)`` raises a `CalledProcessError` that holds the output
    and shows none of it, so an installer refusal arrives as a returncode and a command
    line. That is how the failure this file repairs reached CI: five identical "returned
    non-zero exit status 1" lines, and uv's actual sentence about what was missing
    captured and thrown away.
    """
    finished = subprocess.run(
        [uv, *argv],
        capture_output=True,
        text=True,
        env=os.environ | {"UV_CACHE_DIR": str(cold_cache)},
    )
    if finished.returncode != 0:
        raise AssertionError(
            f"uv {' '.join(argv)} exited {finished.returncode}\n"
            f"--- stdout ---\n{finished.stdout}"
            f"--- stderr ---\n{finished.stderr}"
        )


def _declared(requirements: Iterable[str] | None) -> list[str]:
    """The names out of a distribution's `Requires-Dist` headers.

    Extras are dropped: they are what somebody else may ask for, not what this wheel
    needs to answer, and an installation is evidence about the declared runtime
    dependencies or it is evidence about nothing in particular.
    """
    return [
        match.group()
        for requirement in requirements or ()
        if "extra ==" not in requirement
        if (match := _REQUIREMENT_NAME.match(requirement.strip()))
    ]


def _wheel_requires(carried: dict[str, bytes]) -> list[str]:
    """What the built wheel declares it needs at runtime.

    Read out of the wheel rather than out of `pyproject.toml`, because the wheel is the
    artifact under test and its METADATA is what a consumer's installer would be handed.
    """
    name = next(name for name in carried if name.endswith(".dist-info/METADATA"))
    return _declared(message_from_string(carried[name].decode("utf-8")).get_all("Requires-Dist"))


def _runtime_closure(carried: dict[str, bytes]) -> list[metadata.Distribution]:
    """Every distribution the built wheel needs, transitively, as this one already holds.

    A name this interpreter has no distribution for is a requirement its markers exclude
    - `importlib-metadata` below 3.12, and nothing else here today - and is skipped. A
    name it excludes wrongly is not silently survivable: the command would fail to import
    it, in every test below.
    """
    queue = _wheel_requires(carried)
    seen: set[str] = set()
    closure: list[metadata.Distribution] = []
    while queue:
        name = queue.pop()
        key = re.sub(r"[-_.]+", "-", name).lower()
        if key in seen:
            continue
        seen.add(key)
        try:
            distribution = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue
        closure.append(distribution)
        queue.extend(_declared(distribution.metadata.get_all("Requires-Dist")))
    return closure


def _site_packages(environment: Path) -> Path:
    found = sorted(environment.glob("lib/*/site-packages"))
    assert len(found) == 1, f"expected one site-packages under {environment}, found {found}"
    return found[0]


def _install_runtime_dependencies(environment: Path, carried: dict[str, bytes]) -> None:
    """Put the wheel's declared runtime dependencies into an environment of its own.

    Copied out of the distributions this interpreter is running on, which is the one
    source that is certainly present: this suite imports rdflib and pyshacl to start.
    Resolving them instead would mean an index, and an index means either a network the
    suite does not have or a global cache warmed by something outside this run - the
    assumption that put five errors on a clean runner.

    Console scripts are skipped. They live outside `site-packages`, they name the
    interpreter that installed them, and no command below invokes one.
    """
    target = _site_packages(environment)
    for distribution in _runtime_closure(carried):
        files = distribution.files
        assert files is not None, f"{distribution.metadata['Name']} records no files to copy"
        for entry in files:
            if ".." in entry.parts:
                continue
            source = Path(distribution.locate_file(entry))
            # A RECORD lists what installing wrote, and bytecode caches come and go
            # underneath it. What is not there now is not part of the distribution.
            if not source.is_file():
                continue
            destination = target / Path(*entry.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)


@pytest.fixture(scope="session")
def installed(uv, wheel, carried, cold_cache, tmp_path_factory) -> Path:
    """The command, installed into a virtual environment of its own and nothing else."""
    root = tmp_path_factory.mktemp("installed")
    environment = root / "venv"
    # Built for the interpreter this suite is running on rather than whichever one uv
    # would pick: an interpreter that has to be fetched is a failure against a cache
    # with nothing in it, and the one already running is the one that is certainly here.
    _uv(uv, cold_cache, "venv", "--offline", "--python", sys.executable, str(environment))
    _uv(
        uv,
        cold_cache,
        *("pip", "install", "--offline", "--no-deps"),
        *("--python", str(environment), str(wheel)),
    )
    _install_runtime_dependencies(environment, carried)
    (_site_packages(environment) / "sitecustomize.py").write_text(_NO_SOCKETS, encoding="utf-8")
    command = environment / "bin" / "semantic-layer"
    assert command.exists(), "the wheel installed no semantic-layer command"
    return command


@pytest.fixture(scope="session")
def elsewhere(tmp_path_factory) -> Path:
    """A directory outside this repository, holding only what a caller would hand over.

    The pack is copied rather than pointed at, because the point is that the installed
    command reads files its caller named and nothing that happens to sit near the code.
    """
    root = tmp_path_factory.mktemp("elsewhere")
    committed = packs.read(packs.pack_dir())
    pack = root / "pack"
    pack.mkdir()
    (pack / packs.CONTENT_NAME).write_bytes(committed.content)
    (pack / packs.MANIFEST_NAME).write_bytes(committed.manifest)
    (root / "run.json").write_text(
        json.dumps(
            {
                "schema": run_input.SCHEMA,
                "version": run_input.VERSION,
                "run": {
                    "trace_id": trace_runs.TRACE_ID,
                    "started_at": "2026-08-30T09:00:00Z",
                    "ended_at": "2026-08-30T09:00:12Z",
                    "outcome": "succeeded",
                    "spans": [
                        {
                            "span_id": trace_runs.ROOT_SPAN,
                            "operation": "verify-pack",
                            "kind": "internal",
                            "status": "ok",
                            "started_at": "2026-08-30T09:00:00Z",
                            "ended_at": "2026-08-30T09:00:02Z",
                        }
                    ],
                    "metrics": [{"name": "branches-read", "value": 2, "unit": "count"}],
                },
            }
        ),
        encoding="utf-8",
    )
    return root


## What the wheel does once it is installed.


def outside(installed: Path, elsewhere: Path, *argv: str):
    """One invocation of the installed command, from outside this repository.

    The environment carries a search path and nothing else - no ``PYTHONPATH``, no
    variable this repository's tooling set, and nothing naming a store, a pack or a
    home. If the command needed any of it, it would fail here.
    """
    finished = subprocess.run(
        [str(installed), *argv],
        cwd=elsewhere,
        env={"PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
    )
    assert finished.stderr == "", finished.stderr
    document = json.loads(finished.stdout)
    assert document["schema"] == response.SCHEMA
    assert document["version"] == response.VERSION
    assert finished.returncode == (
        response.OK
        if document["status"] == "ok"
        else response.EXIT_BY_KIND[document["error"]["kind"]]
    )
    return finished.returncode, document


def test_an_installed_command_verifies_a_pack_it_was_handed(installed, elsewhere):
    """Which needs the packaged vocabulary: a manifest states the version it was built for."""
    status, document = outside(
        installed, elsewhere, "pack", "verify", "--directory", "pack", "--as-of", trace_runs.AS_OF
    )
    assert status == 0
    committed = json.loads(packs.read(packs.pack_dir()).manifest)
    assert document["result"]["pack"]["vocabulary_version"] == committed["vocabulary_version"]


def test_an_installed_command_exports_the_bytes_it_verified(installed, elsewhere):
    status, document = outside(
        installed, elsewhere, "pack", "export", "--directory", "pack", "--as-of", trace_runs.AS_OF
    )
    assert status == 0
    assert document["result"]["content"]["text"].encode("utf-8") == (
        (elsewhere / "pack" / packs.CONTENT_NAME).read_bytes()
    )


def test_an_installed_command_records_reads_projects_and_expires(installed, elsewhere):
    """The whole L3 round trip, from a wheel, against files a caller named."""
    store = "trace.sqlite3"
    status, recorded = outside(
        installed,
        elsewhere,
        *("trace", "record", "--store", store, "--pack", "pack"),
        *("--as-of", trace_runs.AS_OF, "--expect-target", trace_runs.TARGET),
        *("--input", "run.json"),
    )
    assert status == 0 and recorded["result"]["created"] is True

    status, replayed = outside(
        installed,
        elsewhere,
        *("trace", "record", "--store", store, "--pack", "pack"),
        *("--as-of", trace_runs.AS_OF, "--input", "run.json"),
    )
    assert status == 0 and replayed["result"]["created"] is False

    status, held = outside(
        installed, elsewhere, "trace", "get", "--store", store, "--trace-id", trace_runs.TRACE_ID
    )
    assert status == 0
    assert held["result"]["run"]["spans"][0]["span_id"] == trace_runs.ROOT_SPAN

    status, projected = outside(
        installed,
        elsewhere,
        *("trace", "project", "--store", store, "--trace-id", trace_runs.TRACE_ID),
    )
    assert status == 0
    assert projected["result"]["summary"]["media_type"] == "application/n-triples"

    status, expired = outside(
        installed,
        elsewhere,
        *("trace", "expire", "--store", store, "--as-of", "2026-12-01T00:00:00Z"),
    )
    assert status == 0
    assert expired["result"]["expired"] == [trace_runs.TRACE_ID]


def test_an_installed_command_refuses_with_a_document_and_not_a_traceback(installed, elsewhere):
    status, document = outside(
        installed,
        elsewhere,
        *("pack", "verify", "--directory", "pack", "--as-of", "2027-01-01T00:00:00Z"),
    )
    assert status == 1
    assert document["error"]["kind"] == "pack"


def test_an_installed_command_needs_no_checkout_beside_it(installed, elsewhere):
    """Nothing it reads is found relative to where the code was written."""
    status, document = outside(
        installed, elsewhere, "pack", "verify", "--directory", "pack", "--as-of", trace_runs.AS_OF
    )
    assert status == 0
    assert not (Path(installed).parents[1] / "ontology").exists()
    assert sys.prefix not in json.dumps(document)
    assert str(graph.ROOT) not in json.dumps(document)


def test_the_installation_holds_what_the_wheel_declares(installed, carried):
    """Installed there, rather than importable from wherever this suite happens to run.

    `importlib.metadata` answers out of the `.dist-info` directories beside the code, so
    asking the installed interpreter for a version is asking whether each distribution
    arrived whole rather than as a directory of modules. The names come out of the wheel
    so a dependency added to `pyproject.toml` is covered without being written here too;
    the two it must always declare are named, because a list read out of the artifact
    would pass just as happily if the artifact declared nothing.
    """
    declared = _wheel_requires(carried)
    assert {"rdflib", "pyshacl"} <= set(declared), declared
    finished = subprocess.run(
        [
            str(Path(installed).parent / "python"),
            "-c",
            "import importlib.metadata as found, sys\n"
            "print('\\n'.join(found.version(name) for name in sys.argv[1:]))",
            *declared,
        ],
        env={"PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
    )
    assert finished.returncode == 0, finished.stderr
    assert len(finished.stdout.split()) == len(declared)


@pytest.mark.parametrize(
    "attempt",
    [
        "socket.socket().connect(('127.0.0.1', 9))",
        "socket.create_connection(('127.0.0.1', 9))",
        "socket.getaddrinfo('example.invalid', 443)",
    ],
)
def test_the_installed_command_runs_where_the_network_is_refused(installed, elsewhere, attempt):
    """The environment every test above ran in has no network, shown rather than argued.

    A flag on the installer says what uv was allowed to do; it says nothing about the
    command afterwards, and it was the only thing this file used to check. So the
    network is taken away from the installation itself, and this is the control that
    proves the refusal is live: the same interpreter that runs the command, in the same
    environment, from the same directory, reaches nowhere.
    """
    finished = subprocess.run(
        [str(Path(installed).parent / "python"), "-c", f"import socket; {attempt}"],
        cwd=elsewhere,
        env={"PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
    )
    assert finished.returncode != 0
    assert "the installed command tried to reach the network" in finished.stderr
