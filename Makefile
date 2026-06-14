PYTHON = .venv/bin/python
PIP    = .venv/bin/pip

.PHONY: venv test run ingest scan clean

venv:
	python3 -m venv .venv
	$(PIP) install -r requirements.txt

test:
	$(PYTHON) -m pytest -q

run:
	$(PYTHON) -c "from sepa import db, ingest; from sepa.run_daily import run; con=db.connect(); ingest.seed_synthetic(con); run(con)"

ingest:
	$(PYTHON) -c "from sepa import db, ingest; con=db.connect(); ingest.ingest_us(con)"

scan:
	$(PYTHON) -m sepa.run_daily

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true
	rm -rf .pytest_cache
