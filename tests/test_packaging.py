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

It stays offline like the rest of the suite: the build backend and the dependencies are
already in this machine's cache because this environment was synced from them, and both
commands below are told not to reach for anything else.
"""

import contextlib
import inspect
import json
import shutil
import subprocess
import sys
import zipfile
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


## What the wheel does once it is installed.


@pytest.fixture(scope="session")
def uv() -> str:
    executable = shutil.which("uv")
    assert executable, "uv builds and runs this project; the suite needs it on PATH"
    return executable


@pytest.fixture(scope="session")
def installed(uv, wheel, tmp_path_factory) -> Path:
    """The command, installed into a virtual environment of its own and nothing else.

    Offline, from this machine's cache: everything the wheel depends on is already
    there, because the environment this suite is running in was resolved from the same
    lock. A dependency that is not cached is a failure here rather than a download.
    """
    root = tmp_path_factory.mktemp("installed")
    environment = root / "venv"
    # Built for the interpreter this suite is running on rather than whichever one uv
    # would pick: offline, an interpreter that has to be fetched is a failure, and the
    # one already running is the one that is certainly here.
    subprocess.run(
        [uv, "venv", "--offline", "--python", sys.executable, str(environment)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [uv, "pip", "install", "--offline", "--python", str(environment), str(wheel)],
        check=True,
        capture_output=True,
    )
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


def test_the_installation_reaches_no_network():
    """The two commands in this file that could go online are told not to.

    The suite takes the socket away for the whole session, and that reaches every test
    in this process and none of the subprocesses this file starts. So the guarantee for
    those two is the flag, and the flag is what is checked: without it, a machine with a
    cold cache would quietly download rather than fail, and this file would be the one
    place in the repository that goes to the network on a test run.
    """
    source = inspect.getsource(installed.__wrapped__)
    assert source.count("--offline") == 2, "a uv command here may reach the network"
