PY ?= .venv/bin/python
UV ?= uv

.PHONY: install dev web-dev serve test lint typecheck check build-web openapi demo eval e2e ui-audit capture samples clean

install:            ## install backend (editable, dev extras) and frontend deps
	$(UV) venv -q .venv || true
	$(UV) pip install -e ".[dev]"
	cd web && npm ci

serve:              ## run the API + built UI on http://127.0.0.1:8765
	.venv/bin/ordnung serve

web-dev:            ## run the Vite dev server (proxies /api to :8765)
	cd web && npm run dev

test:               ## backend tests + frontend unit tests
	$(PY) -m pytest -m "not slow" --cov=ordnung --cov-report=term-missing:skip-covered
	$(PY) -m pytest -m slow
	cd web && npm test

lint:
	$(PY) -m ruff check src tests scripts evals
	$(PY) -m ruff format --check src tests scripts evals
	cd web && npm run lint

typecheck:
	$(PY) -m mypy
	cd web && npm run typecheck

check: lint typecheck test   ## lint, types and tests (CI also runs the rules coverage gate, both benchmarks, demo --check, the build check and e2e)

build-web:          ## build the SPA into src/ordnung/web/dist
	cd web && npm run build

openapi:            ## regenerate web/openapi.json and TS types from the FastAPI app
	.venv/bin/ordnung openapi > web/openapi.json
	cd web && npm run gen:api

samples:            ## regenerate the fictional sample life + eval dataset
	$(PY) scripts/make_sample_life.py

demo:               ## explore the sample life (replayed model outputs, zero tokens)
	.venv/bin/ordnung demo --serve

eval:               ## recompute benchmark metrics from recorded outputs
	.venv/bin/ordnung eval

e2e: build-web      ## Playwright end-to-end tests against demo mode
	cd web && npx playwright test

UI_AUDIT_DIR ?= /tmp/ordnung-ui-audit
UI_AUDIT_PORT ?= 8811
UI_AUDIT_ARGS ?=

ui-audit: build-web ## screenshots + layout/a11y probes of every screen: demo, first run, static demo (ports N..N+2)
	node web/scripts/ui-audit.mjs --target demo,fresh,static --port $(UI_AUDIT_PORT) --data $(UI_AUDIT_DIR)/data --out $(UI_AUDIT_DIR)/out $(UI_AUDIT_ARGS)

capture: build-web  ## README screenshots, demo video and GIF (needs ffmpeg)
	scripts/capture.sh

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage web/dist src/ordnung/web/dist
