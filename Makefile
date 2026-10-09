# Common tasks. Uses .venv/bin/python when it exists, else the python on PATH.
# Pass extra flags with ARGS, e.g. make scan ARGS="--preset rich --symbols SPY,QQQ".

PY    := $(if $(wildcard .venv/bin/python),.venv/bin/python,python)
IMAGE ?= ghcr.io/corrionhank/alpha-surface:latest
APP   := src/alphasurface/app.py
ARGS  ?=

.DEFAULT_GOAL := help
.PHONY: help install install-locked lock lint format typecheck test cov check run collect \
        collect-bars scan study docker-build docker-run clean

help:  ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-15s %s\n", $$1, $$2}'

install:  ## Editable install with dev tools, then the git hooks
	$(PY) -m pip install -e ".[dev]"
	$(PY) -m pre_commit install

install-locked:  ## Install the pinned set from requirements-dev.lock
	$(PY) -m pip install -r requirements-dev.lock
	$(PY) -m pip install --no-deps -e .

lock:  ## Re-resolve requirements.lock and requirements-dev.lock (needs pip-tools)
	$(PY) -m piptools compile --quiet --strip-extras -o requirements.lock pyproject.toml
	$(PY) -m piptools compile --quiet --strip-extras --extra dev -o requirements-dev.lock pyproject.toml

lint:  ## Lint and check formatting
	$(PY) -m ruff check src tests studies
	$(PY) -m ruff format --check src tests studies

format:  ## Apply lint fixes and formatting
	$(PY) -m ruff check --fix src tests studies
	$(PY) -m ruff format src tests studies

typecheck:  ## Static types
	$(PY) -m mypy src

test:  ## Test suite
	$(PY) -m pytest -q $(ARGS)

cov:  ## Tests with coverage; fails under the floor in pyproject.toml
	$(PY) -m pytest -q --cov --cov-report=term --cov-report=xml $(ARGS)

check: lint test  ## Lint and tests, then the type check (reported, not enforced yet)
	-$(MAKE) --no-print-directory typecheck

run:  ## Dashboard on http://localhost:8501
	$(PY) -m streamlit run $(APP) $(ARGS)

collect:  ## tastytrade market metrics and SPY/QQQ chains into the store
	$(PY) -m alphasurface.collector.tastytrade_collector $(ARGS)

collect-bars:  ## Top up daily and hourly bars from Yahoo
	$(PY) -m alphasurface.collector.yfinance_collector --interval 1d --period 5d $(ARGS)
	$(PY) -m alphasurface.collector.yfinance_collector --interval 1h --period 5d $(ARGS)

scan:  ## Run the screener from the command line (make scan ARGS="--list")
	$(PY) -m alphasurface.collector.scan $(ARGS)

study:  ## Protective put study (needs the studies extra)
	$(PY) -m studies.protective_puts $(ARGS)

docker-build:  ## Build the app image
	docker build -t $(IMAGE) .

docker-run:  ## Run the image with ./data mounted and .env if present
	docker run --rm -p 8501:8501 -v "$(CURDIR)/data:/data" \
		$(if $(wildcard .env),--env-file .env,) $(IMAGE)

clean:  ## Remove caches and build output (never data/)
	rm -rf build dist .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage coverage.xml
	find src tests studies -type d -name __pycache__ -prune -exec rm -rf {} +
	find src -maxdepth 2 -type d -name '*.egg-info' -prune -exec rm -rf {} +
