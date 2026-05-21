default:
    @just --list

# Install/sync dependencies
sync:
    uv sync

# Run the CLI (pass args after --)
run *ARGS:
    uv run proj {{ARGS}}

# Run tests
test *ARGS:
    uv run pytest {{ARGS}}

# Run tests with coverage
cov:
    uv run pytest --cov=proj --cov-report=term-missing

# Lint
lint:
    uv run ruff check

# Lint with autofix
fix:
    uv run ruff check --fix

# Format
fmt:
    uv run ruff format

# Check formatting without writing
fmt-check:
    uv run ruff format --check

# Run all checks (lint + format check + tests)
check: lint fmt-check test

# Build sdist + wheel
build:
    uv build

# Install proj as a uv tool from the current source
install:
    uv tool install --force --reinstall .

# Remove build artifacts and caches
clean:
    rm -rf dist build *.egg-info .pytest_cache .ruff_cache .coverage htmlcov
    find . -type d -name __pycache__ -exec rm -rf {} +
