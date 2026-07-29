.PHONY: help install install-metal lint format typecheck test cov check pre-commit clean

help:
	@echo "Targets:"
	@echo "  install        uv sync --extra dev"
	@echo "  install-metal  llama-cpp-python with Metal"
	@echo "  lint           ruff check"
	@echo "  format         ruff format"
	@echo "  typecheck      mypy"
	@echo "  test           pytest"
	@echo "  check          lint + format check + mypy + test"
	@echo "  pre-commit     run all pre-commit hooks"
	@echo "  clean          caches and generated audio"

install:
	uv sync --extra dev
	@echo "Note: re-run 'make install-metal' on macOS after sync (llama-cpp-python is not in the lockfile)."

install-metal:
	./scripts/install_metal.sh

lint:
	uv run ruff check .

format:
	uv run ruff check . --fix
	uv run ruff format .

typecheck:
	uv run mypy main.py local_orpheus.py tests

test:
	uv run pytest

cov:
	uv run pytest --cov-report=html
	@echo "open htmlcov/index.html"

# Same order as CI: lint → format --check → mypy → pytest
check:
	uv run ruff check .
	uv run ruff format --check .
	$(MAKE) typecheck
	$(MAKE) test

pre-commit:
	uv run pre-commit run --all-files

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache .coverage htmlcov __pycache__ tests/__pycache__
	rm -f speech.wav speech.mp3 .groq_usage.json
