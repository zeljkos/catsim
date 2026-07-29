# Use the project venv's tools when present; fall back to PATH (e.g. CI).
VENV_BIN := $(if $(wildcard .venv/bin),.venv/bin/,)

.PHONY: check lint typecheck imports test format setup demo demo-docker reset

## demo: Act 1 ready to grow — the elastic fleet (1 chip, process fallback) + dashboard
demo:
	$(VENV_BIN)python -m catsim.cli serve --fleet 1 --machine chip-256

## demo-docker: the same fleet as real containers (dashboard at :8000)
demo-docker:
	docker compose -f deploy/docker-compose.yaml up --build -d
	@echo "dashboard: http://localhost:8000"

## reset: kill every fleet process and container, fresh slate in <10 s
## (chips first: they hold the compose network, so down would fail to remove it)
reset:
	-pkill -f "catsim.cli node" 2>/dev/null || true
	-docker ps -aq --filter "label=catsim-chip" | xargs docker rm -f 2>/dev/null || true
	-docker compose -f deploy/docker-compose.yaml down --remove-orphans -t 2 2>/dev/null || true

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
