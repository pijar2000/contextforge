.PHONY: install install-dev lint format test test-integration sample-docs up down logs init ingest \
        evaluate evaluate-local api dashboard clean

PYTHON ?= python

install:
	$(PYTHON) -m pip install -e ".[dashboard,dev]"

lint:
	ruff check .
	ruff format --check .

format:
	ruff format .
	ruff check --fix .

test:
	pytest tests/unit tests/integration -m "not integration and not model"

test-integration:  # needs `make up` first
	pytest -m integration tests/integration

sample-docs:  # regenerates the DOCX and PDF sample files
	$(PYTHON) scripts/generate_sample_documents.py

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f api

init:
	contextforge init

ingest:
	contextforge ingest

evaluate:
	contextforge evaluate

evaluate-local:  # no Docker needed; indexes the sample corpus in memory
	contextforge evaluate --local

api:
	uvicorn contextforge.api.app:get_app --factory --reload --port 8000

dashboard:
	streamlit run dashboard/app.py

clean:
	rm -rf .pytest_cache .ruff_cache build dist *.egg-info data
