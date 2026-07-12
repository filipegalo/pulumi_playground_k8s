SHELL := /bin/bash

PULUMI_CONFIG_PASSPHRASE ?= local-dev-only
ENV ?= dev
STACK ?= $(ENV)
NAMESPACE ?= nginx-dev
SERVICE ?= nginx
LOCAL_PORT ?= 8080
SERVICE_PORT ?= 80
SECRET_KEY ?= DUMMY_SECRET
UV_CACHE_DIR ?= .uv-cache
PYTHONPATH ?= .
export UV_CACHE_DIR
export PYTHONPATH

UV := uv
PYTHON := $(UV) run python
PYTEST := $(UV) run pytest
PULUMI := PULUMI_CONFIG_PASSPHRASE=$(PULUMI_CONFIG_PASSPHRASE) pulumi

.PHONY: help setup install install-dev login stack-select set-secret preview preview-diff up destroy stack-rm compile test coverage coverage-html pre-commit-install pre-commit validate kube-context kube-nodes kube-all port-forward clean

help:
	@echo "Useful commands:"
	@echo "  make setup          Create .venv and install Python dependencies"
	@echo "  make install        Sync runtime dependencies with uv"
	@echo "  make install-dev    Sync runtime and dev dependencies with uv"
	@echo "  make login          Use Pulumi local backend"
	@echo "  make stack-select   Select Pulumi stack, default ENV=dev"
	@echo "  make set-secret     Set encrypted secret config for ENV=$(ENV), SERVICE=$(SERVICE), SECRET_KEY=$(SECRET_KEY)"
	@echo "  make preview        Run pulumi preview"
	@echo "  make preview-diff   Run pulumi preview --diff"
	@echo "  make up             Apply with pulumi up --diff"
	@echo "  make destroy        Destroy stack resources"
	@echo "  make compile        Compile Python files"
	@echo "  make test           Run Pulumi mock tests"
	@echo "  make coverage       Run tests with terminal coverage report"
	@echo "  make coverage-html  Run tests and write HTML coverage to htmlcov/"
	@echo "  make pre-commit-install Install local git pre-commit hooks"
	@echo "  make pre-commit     Run pre-commit hooks against all files"
	@echo "  make validate       Compile, test, and run preview --diff"
	@echo "  make kube-context   Show current kube context"
	@echo "  make kube-nodes     List Kubernetes nodes"
	@echo "  make kube-all       List resources in NAMESPACE=$(NAMESPACE)"
	@echo "  make port-forward   Forward LOCAL_PORT=$(LOCAL_PORT) to SERVICE=$(SERVICE)"
	@echo "  make clean          Remove generated Python cache files"

setup: install

install:
	$(UV) sync --no-dev

install-dev:
	$(UV) sync

login:
	pulumi login --local

stack-select:
	$(PULUMI) stack select $(STACK)

set-secret:
	@if [ -z "$$SECRET_VALUE" ]; then \
		echo "SECRET_VALUE is required. Example: SECRET_VALUE=local-dev-only make set-secret ENV=dev SERVICE=nginx SECRET_KEY=DUMMY_SECRET"; \
		exit 1; \
	fi
	@$(PULUMI) stack select $(STACK) >/dev/null
	@$(PULUMI) config set --secret $(SERVICE):$(SECRET_KEY) "$$SECRET_VALUE"

preview:
	$(PULUMI) preview

preview-diff:
	$(PULUMI) preview --diff

up:
	$(PULUMI) up --diff

destroy:
	$(PULUMI) destroy --diff

stack-rm:
	$(PULUMI) stack rm $(STACK)

compile:
	$(PYTHON) -m py_compile __main__.py paas_platform/*.py services/__init__.py

test:
	$(PYTEST) -q

coverage:
	$(PYTEST) --cov=paas_platform --cov=services --cov-report=term-missing --cov-fail-under=100

coverage-html:
	$(PYTEST) --cov=paas_platform --cov=services --cov-report=term-missing --cov-report=html --cov-fail-under=100

pre-commit-install:
	chmod +x .githooks/pre-commit
	git config core.hooksPath .githooks

pre-commit:
	$(UV) run pre-commit run --all-files

validate: compile coverage preview-diff

kube-context:
	kubectl config current-context

kube-nodes:
	kubectl get nodes

kube-all:
	kubectl -n $(NAMESPACE) get all

port-forward:
	kubectl -n $(NAMESPACE) port-forward svc/$(SERVICE) $(LOCAL_PORT):$(SERVICE_PORT)

clean:
	find . \( -path ./.venv -o -path ./.git \) -prune -o -type d -name __pycache__ -exec rm -rf {} +
	rm -rf .pytest_cache .coverage htmlcov .uv-cache
