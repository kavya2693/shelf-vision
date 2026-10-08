.PHONY: run generate train detect eval lint test check api

generate:
	uv run shelf-vision generate

train:
	uv run shelf-vision train

detect:
	uv run shelf-vision detect

eval:
	uv run shelf-vision eval

run:
	uv run shelf-vision run

api:
	uv run shelf-vision-api

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy

test:
	uv run pytest -q

check: lint test
