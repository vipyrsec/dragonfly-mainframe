.ONESHELL:
.SILENT:
.DEFAULT_GOAL = help

PYTHON_FILES = $(shell find src/ tests/ -type f -name '*.py')

.PHONY: all
all: format lint test ## Format, lint, and run tests

.PHONY: format
format: $(PYTHON_FILES) ## Format Python files
	uv run --locked ruff format $?

LINT_OPTIONS = --fix # Fix the lint violations

.PHONY: lint
lint: $(PYTHON_FILES) ## Lint Python files
	uv run --locked pyright; uv run --locked ruff check $(LINT_OPTIONS) $?

.PHONY: test
test: $(PYTHON_FILES) ## Run tests in Docker
	docker compose \
		-f compose.yaml -f compose-tests.yaml \
		up --build --exit-code-from mainframe

.PHONY: coverage
coverage: $(PYTHON_FILES) ## Generate coverage report
	uv run --locked --no-default-groups --group=test coverage run -m pytest tests -vv
	uv run --locked --no-default-groups --group=test coverage report -m --skip-covered
	uv run --locked --no-default-groups --group=test coverage xml

.PHONY: pre-commit
pre-commit: ## Run pre-commit on all files
	uv run --locked pre-commit install
	uv run --locked pre-commit run --all-files

.PHONY: start
start: ## Start the project in Docker
	docker compose up --build

.PHONY: help
help: ## Prints help for targets with comments
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%s:\033[0m %s\n", $$1, $$2}' | \
		column -c2 -ts:
