.PHONY: install test lint dev

install:
	uv sync --extra dev

test:
	uv run pytest

lint:
	uv run ruff check .

dev:
	uv run mcp dev src/portfolio_copilot/server.py
