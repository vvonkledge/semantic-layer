"""The committed queries are the ontology's acceptance tests.

A vocabulary change that stops the model answering a business question fails here,
which is the only thing that makes the question a commitment rather than a comment.
"""

import json

import pytest

from semantic_layer import graph

QUERIES = sorted(graph.QUERIES_DIR.glob("*.rq"))


def test_the_model_answers_at_least_three_questions():
    assert len(QUERIES) >= 3


@pytest.mark.parametrize("query_file", QUERIES, ids=lambda path: path.stem)
def test_query_returns_its_committed_answer(query_file, fixture_graph):
    expected_file = query_file.with_suffix(".expected.json")
    assert expected_file.exists(), f"{query_file.name} has no committed expected result"
    expected = json.loads(expected_file.read_text(encoding="utf-8"))

    assert graph.query(fixture_graph, query_file) == expected


@pytest.mark.parametrize("query_file", QUERIES, ids=lambda path: path.stem)
def test_query_returns_something(query_file, fixture_graph):
    """A question the fixtures cannot exercise is not being tested by anything."""
    assert graph.query(fixture_graph, query_file)
