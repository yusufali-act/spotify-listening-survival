PY := .venv/bin/python

.PHONY: setup synthetic run all demo serve clean

setup:            ## create the virtualenv and install dependencies
	python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt

synthetic:        ## generate the synthetic demo export
	$(PY) -m src.generate_synthetic --out data/synthetic

run:              ## run the pipeline (uses data/raw if it has files, otherwise synthetic)
	$(PY) -m src.pipeline

demo: synthetic   ## always run on synthetic data
	$(PY) -m src.pipeline --source synthetic

all: setup synthetic run

serve:            ## view the dashboard at http://localhost:8000
	python3 -m http.server 8000 --directory dashboard

clean:
	rm -rf data/synthetic data/*.duckdb powerbi/data
