# Command aliases. Every target is a thin wrapper around a visible command, so
# anything run here can also be run by hand. CI invokes these same targets.
#
# Targets for later phases (integration, golden, api, worker, dashboard,
# compose, benchmark) are added by the phase that has something to run.

UV ?= uv

.DEFAULT_GOAL := help
.PHONY: help bootstrap lock-check lint format format-check typecheck test test-integration test-golden check version doctor fixtures clean migrate run-api run-worker-cpu run-worker-celery run-dashboard compose-up compose-down benchmark

help: ## List available targets
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

bootstrap: ## Create .venv and install every dependency group from the lockfile
	$(UV) sync --all-groups

lock-check: ## Fail if uv.lock disagrees with pyproject.toml
	$(UV) lock --check

lint: ## Ruff lint
	$(UV) run ruff check .

format: ## Ruff format, in place
	$(UV) run ruff format .

format-check: ## Fail if any file is unformatted
	$(UV) run ruff format --check .

typecheck: ## mypy, strict
	$(UV) run mypy src apps

test: ## Unit tests with coverage
	$(UV) run pytest -q --cov-fail-under=100

test-integration: ## Integration tests (Postgres URL, ffmpeg, optional Redis)
	$(UV) run pytest tests/integration -q --no-cov

test-golden: ## Golden fixture tests
	$(UV) run pytest tests/golden -q --no-cov

benchmark: ## Cold/warm CPU-core timings into build/release-benchmark.json
	mkdir -p build
	$(UV) run cine-analyzer benchmark --manifest fixtures/benchmark/manifest.yaml --output build/release-benchmark.json --profile
	$(UV) run cine-analyzer validate-benchmark build/release-benchmark.json

check: lock-check lint format-check typecheck test ## Everything CI runs

version: ## Print the package version through the module entry point
	$(UV) run python -m cine_analyzer --version

doctor: ## Report runtime capabilities
	$(UV) run cine-analyzer doctor

fixtures: ## Generate tiny local video fixtures (gitignored; requires ffmpeg)
	$(UV) run python scripts/generate_fixtures.py

migrate: ## Apply Alembic migrations (requires CINE_DATABASE_URL)
	$(UV) run alembic upgrade head

run-api: ## Bind the FastAPI control plane
	$(UV) run cine-analyzer serve

run-worker-cpu: ## Claim queued analyses and run local pipeline stages
	$(UV) run cine-analyzer worker

run-worker-celery: ## Celery CPU worker (requires the celery extra and Redis)
	$(UV) run --group celery cine-analyzer celery-worker --role cpu

run-dashboard: ## Streamlit API client (requires the dashboard dependency group)
	$(UV) run --group dashboard streamlit run apps/dashboard/app.py

compose-up: ## Postgres, Redis, API, and CPU worker
	docker compose up -d --build postgres redis migrate api worker-cpu

compose-down: ## Stop Compose services
	docker compose down

clean: ## Remove tool caches and coverage output
	rm -rf .mypy_cache .pytest_cache .ruff_cache .hypothesis .coverage htmlcov
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
