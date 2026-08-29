# Run `just` with no arguments to get the same check CI runs.
default: check

# The delivery rigor: validate every committed graph, prove every negative fixture
# fails for its stated reason, and assert every competency question's answer.
test:
    uv run --frozen pytest

lint:
    uv run --frozen ruff check .
    uv run --frozen ruff format --check .

check: lint test
