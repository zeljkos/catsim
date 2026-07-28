# Use the project venv's tools when present; fall back to PATH (e.g. CI).
VENV_BIN := $(if $(wildcard .venv/bin),.venv/bin/,)

.PHONY: check lint typecheck imports test format setup

## check: the quality gate — lint + typecheck + import contracts + tests
check: lint typecheck imports test

lint:
	$(VENV_BIN)ruff check catsim tests
	$(VENV_BIN)ruff format --check catsim tests

typecheck:
	$(VENV_BIN)mypy

imports:
	$(VENV_BIN)lint-imports

test:
	$(VENV_BIN)pytest

## format: auto-fix lint and formatting
format:
	$(VENV_BIN)ruff check --fix catsim tests
	$(VENV_BIN)ruff format catsim tests

## setup: create the venv, install the package + dev tools, install pre-commit hooks
setup:
	python3 -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -e ".[dev]"
	.venv/bin/pre-commit install
