# MediaHub — developer Makefile
.PHONY: install test run build clean deploy-render deploy-fly docker docker-run lint

PYTHON ?= python3
PIP    ?= pip
PORT   ?= 5000
export PYTHONPATH := $(CURDIR)/src

install:
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	$(PIP) install -e .

test:
	$(PYTHON) -m pytest tests/ -x -q

test-collect:
	$(PYTHON) -m pytest tests/ --co -q

run:
	$(PYTHON) -m mediahub.web

build:
	$(PYTHON) -m build

clean:
	rm -rf build/ dist/*.tar.gz dist/*.whl *.egg-info src/*.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type d -name .pytest_cache -prune -exec rm -rf {} +
	rm -rf runs_v4/* uploads_v4/* .cache/*

docker:
	docker build -t mediahub:latest .

docker-run:
	docker run --rm -p $(PORT):5000 --env-file .env mediahub:latest

deploy-render:
	@echo "Push to a Render-connected git remote; Render will read render.yaml automatically."
	@echo "Or: render blueprint apply"

deploy-fly:
	fly deploy

lint:
	$(PYTHON) -m py_compile $$(find src/mediahub -name '*.py')
