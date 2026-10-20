.PHONY: install test lint format typecheck run

install:
	pip install -e ".[dev]"
	pre-commit install

test:
	pytest -q

lint:
	ruff check .
	ruff format --check .

format:
	ruff check --fix .
	ruff format .

typecheck:
	mypy src

run:
	extracto run
