.PHONY: install test lint typecheck fmt clean run help

# ── Installation ──────────────────────────────────────────────────────────────

install:  ## Install the package and dev dependencies
	pip install -e ".[dev]"

# ── Quality gates ─────────────────────────────────────────────────────────────

test:  ## Run the test suite with coverage
	pytest

test-fast:  ## Run tests without coverage (faster feedback loop)
	pytest --no-cov

lint:  ## Run ruff linter
	ruff check alarm_clock tests

fmt:  ## Auto-format with ruff
	ruff format alarm_clock tests

typecheck:  ## Run mypy type checker
	mypy alarm_clock

check: lint typecheck test  ## Run all quality gates (lint + types + tests)

# ── Development ───────────────────────────────────────────────────────────────

run:  ## Start the alarm scheduler (example: make run)
	alarm run

clean:  ## Remove build artifacts and caches
	rm -rf dist/ build/ .eggs/ *.egg-info/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type d -name ".mypy_cache" -exec rm -rf {} +
	find . -type d -name ".ruff_cache" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -name ".coverage" -delete
	find . -name "coverage.xml" -delete

# ── Help ──────────────────────────────────────────────────────────────────────

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'
