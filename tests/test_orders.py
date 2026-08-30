"""The root orders still say the load-bearing things a cold contributor is held to.

`ORDERS.md` is the only thing a contributor who has never seen this repository is given
before they change it, and the pipeline half of it is the part that cannot be learned by
reading the code: nothing in `src/` or `tests/` records that a pass is bound to one
commit, or that exit 2 is somebody else's decision. Prose has no compiler, so a rewrite
that drops a rule reads exactly like one that keeps it.

So the rules are pinned here, tolerantly. What is asserted is that each instruction is
still present and still says the same thing - not the sentence it is written in. Rewrite
the prose freely; if a check here fails, either the rule left the file, or it now says
the opposite, and both are the failure this file exists to catch.

Nothing here needs SIANA installed. These are contract tests over committed guidance,
and they read files.
"""

import re

import pytest

from semantic_layer import graph

ORDERS = graph.ROOT / "ORDERS.md"
JUSTFILE = graph.ROOT / "justfile"
WORKFLOW = graph.ROOT / ".github" / "workflows" / "check.yml"


def _flat(text: str) -> str:
    """The document with every run of whitespace collapsed to one space.

    Prose here wraps at 88 columns, so any sentence long enough to be load-bearing is
    also long enough to be split across lines - and where it splits changes whenever a
    word before it changes. Matching against the flattened text asks what the orders
    say rather than how they happen to be laid out.
    """
    return " ".join(text.split())


@pytest.fixture(scope="module")
def orders() -> str:
    """The orders, or an empty string if the file is gone.

    Missing is a case worth reporting rather than erroring on: a deleted `ORDERS.md`
    should fail as "the orders are missing" and not as somebody's `FileNotFoundError`
    in a fixture, which reads like a broken test rather than a removed contract.
    """
    return ORDERS.read_text(encoding="utf-8") if ORDERS.exists() else ""


@pytest.fixture(scope="module")
def flat_orders(orders: str) -> str:
    return _flat(orders)


def test_the_orders_exist(orders: str):
    """Delete the file and every other check here would pass vacuously."""
    assert orders.strip(), f"{ORDERS} is missing or empty"


#: Each rule the orders may not lose, and a pattern that is true only while it is there.
#: The name is what a failure reports, so it says the rule rather than the regex.
REQUIRED = [
    (
        "`just check` is named as this project's delivery command",
        r"`just check` is this project's delivery command",
    ),
    (
        "`just test` is named as the inner command, and so not as the gate",
        r"`just test` is the inner command",
    ),
    (
        "delivery runs lint and the suite together",
        r"delivery command\..{0,160}?\blint\b.{0,120}?\bsuite\b",
    ),
    (
        "a run is started with `siana-pipeline run`",
        r"siana-pipeline run",
    ),
    (
        "verification is `siana-pipeline check`",
        r"`verify: siana-pipeline check`",
    ),
    (
        "`check` reads the record and starts nothing",
        r"`check` starts nothing",
    ),
    (
        "a run refuses a tree that is not committed",
        r"refuses a dirty tree",
    ),
    (
        "the run records the head it validated, and a pass is bound to it",
        r"recorded the head it validated",
    ),
    (
        "no commit may follow a passing run",
        r"Do not commit again",
    ),
    (
        "a change after a pass is committed and run again, never called done",
        r"never do is change it and call `done`",
    ),
    (
        "the pipeline does not push and does not publish",
        r"neither pushes nor publishes",
    ),
    (
        "a finding nobody here can settle is relayed verbatim, not answered",
        r"relay it word for word",
    ),
]


@pytest.mark.parametrize(("rule", "pattern"), REQUIRED, ids=[rule for rule, _ in REQUIRED])
def test_the_orders_still_carry(rule: str, pattern: str, flat_orders: str):
    assert re.search(pattern, flat_orders), f"ORDERS.md no longer says: {rule}"


#: The exit code protocol, as the orders lay it out: a code, then what it means. Each
#: entry is a code and the words its line must still contain, because a code that has
#: quietly changed meaning is worse than one that is missing - a minion would follow it.
PROTOCOL = [
    ("0", [r"pass"]),
    ("1", [r"fix", r"run again"]),
    ("2", [r"block"]),
]


@pytest.fixture(scope="module")
def exit_codes(orders: str) -> dict:
    """The indented `<code> <meaning>` block the orders print the protocol in."""
    return {
        match.group(1): match.group(2)
        for match in re.finditer(r"^ {4}([0-9])\s{2,}(\S.*)$", orders, re.MULTILINE)
    }


@pytest.mark.parametrize(("code", "words"), PROTOCOL, ids=[c for c, _ in PROTOCOL])
def test_the_exit_code_protocol_is_intact(code: str, words: list, exit_codes: dict):
    assert code in exit_codes, f"ORDERS.md no longer states what exit {code} means"
    meaning = exit_codes[code]
    for word in words:
        assert re.search(word, meaning, re.IGNORECASE), (
            f"exit {code} in ORDERS.md no longer says {word!r}: {meaning!r}"
        )


def test_the_protocol_has_no_fourth_state(exit_codes: dict):
    """Three codes and no others. A fourth would be a state with no instruction."""
    assert sorted(exit_codes) == ["0", "1", "2"]


def test_the_commands_the_orders_name_are_real():
    """The orders describe this justfile, not a recipe somebody wishes existed.

    A delivery command that is documented but unwritten fails at the worst moment: a
    minion following these orders runs it, gets `just: unknown recipe`, and has no way
    to tell a stale document from its own mistake.
    """
    justfile = JUSTFILE.read_text(encoding="utf-8")
    assert re.search(r"^check: lint test$", justfile, re.MULTILINE), (
        "`just check` is no longer lint plus test; ORDERS.md says it is"
    )
    assert re.search(r"^test:$", justfile, re.MULTILINE)
    assert re.search(r"^lint:$", justfile, re.MULTILINE)


def test_ci_runs_the_delivery_command():
    """What CI runs and what the orders call delivery are the same command."""
    assert "just check" in WORKFLOW.read_text(encoding="utf-8")
