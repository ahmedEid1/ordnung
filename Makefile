PY ?= .venv/bin/python
UV ?= uv
SAMPLES_MANIFEST = src/ordnung/demo/samples/manifest.json
DE_ZIP ?= DE.zip

.PHONY: install dev web-dev serve test lint typecheck check build-web openapi demo eval browser e2e ui-audit capture samples postcodes constraints clean

install:            ## install backend (editable, dev extras, the versions CI pins) and frontend deps
	$(UV) venv -q .venv || true
	$(UV) pip install -e ".[dev]" -c constraints.txt
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

postcodes:          ## rebuild the postcode table from GeoNames' DE.zip (download it first; DE_ZIP=path, --check: CHECK=1)
	$(PY) -I scripts/make_postcode_table.py $(DE_ZIP) $(if $(CHECK),--check)

constraints:        ## re-pin what CI and `make install` install (CONSTRAINTS_ARGS=--upgrade for the newest); the samples' libraries keep their manifest's versions
	$(PY) -c 'import json; env = json.load(open("$(SAMPLES_MANIFEST)"))["generator"]["environment"]; print(*(f"{name}=={env[name]}" for name in ("fpdf2", "fonttools", "pillow", "pypdfium2")), sep="\n")' > .sample-pins.txt
	$(UV) pip compile pyproject.toml --extra dev --extra eval --universal --python-version 3.11 -c .sample-pins.txt --custom-compile-command "make constraints" --no-annotate -o constraints.txt $(CONSTRAINTS_ARGS)
	rm -f .sample-pins.txt

demo:               ## explore the sample life (replayed model outputs, zero tokens)
	.venv/bin/ordnung demo --serve

eval:               ## recompute benchmark metrics from recorded outputs
	.venv/bin/ordnung eval

browser:            ## the Chromium Playwright drives (skipped when PW_CHROMIUM_PATH names one)
	@if [ -z "$$PW_CHROMIUM_PATH" ]; then cd web && npx playwright install chromium; fi

e2e: build-web browser   ## Playwright end-to-end tests: the demo, then the real app with a fake Claude
	cd web && npx playwright test

UI_AUDIT_DIR ?= /tmp/ordnung-ui-audit
UI_AUDIT_PORT ?= 8811
UI_AUDIT_ARGS ?=

ui-audit: build-web browser ## screenshots + layout/a11y probes of every screen: demo, first run, static demo (ports N..N+2)
	node web/scripts/ui-audit.mjs --target demo,fresh,static --port $(UI_AUDIT_PORT) --data $(UI_AUDIT_DIR)/data --out $(UI_AUDIT_DIR)/out $(UI_AUDIT_ARGS)

capture: build-web browser  ## README screenshots (two of them from the real app), demo video and GIF (needs ffmpeg)
	scripts/capture.sh

clean:              ## caches and coverage; the committed web build in src/ordnung/web/dist stays
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage web/dist
