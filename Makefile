SHELL := /bin/bash

PULUMI_CONFIG_PASSPHRASE ?= local-dev-only
ENV ?= dev
STACK ?= $(ENV)
NAMESPACE ?= nginx
SERVICE ?= nginx
LOCAL_PORT ?= 8080
SERVICE_PORT ?= 80
SECRET_KEY ?= DUMMY_SECRET
DEV_CLUSTER ?= dev
STAGING_CLUSTER ?= staging
CICD_CLUSTER ?= cicd
CICD_STACK ?= cicd
UV_CACHE_DIR ?= .uv-cache
PYTHONPATH ?= .
export UV_CACHE_DIR
export PYTHONPATH

UV := uv
KIND := kind
PYTHON := $(UV) run python
PYTEST := $(UV) run pytest
PULUMI := PULUMI_CONFIG_PASSPHRASE=$(PULUMI_CONFIG_PASSPHRASE) pulumi
PULUMI_STACK_ARG = $(if $(filter command line environment,$(origin STACK)),--stack $(STACK),)

.PHONY: help setup install install-dev cluster-dev cluster-staging cluster-cicd launch-clusters login stack-init stack-select set-secret set-argocd-admin-password preview preview-diff up destroy stack-rm compile test coverage coverage-html generate-gitops check-gitops pre-commit-install pre-commit validate kube-context kube-nodes kube-all port-forward clean

help:
	@echo "Useful commands:"
	@echo "  make setup          Create .venv and install Python dependencies"
	@echo "  make install        Sync runtime dependencies with uv"
	@echo "  make install-dev    Sync runtime and dev dependencies with uv"
	@echo "  make launch-clusters  Create dev and staging kind clusters"
	@echo "  make cluster-dev      Create kind cluster DEV_CLUSTER=$(DEV_CLUSTER)"
	@echo "  make cluster-staging  Create kind cluster STAGING_CLUSTER=$(STAGING_CLUSTER)"
	@echo "  make cluster-cicd     Create CI/CD management cluster CICD_CLUSTER=$(CICD_CLUSTER)"
	@echo "  make login          Use Pulumi local backend"
	@echo "  make stack-init     Initialize Pulumi stack, default STACK=$(STACK)"
	@echo "  make stack-select   Select Pulumi stack, default STACK=$(STACK)"
	@echo "  make set-secret     Set encrypted secret config for STACK=$(STACK), SERVICE=$(SERVICE), SECRET_KEY=$(SECRET_KEY)"
	@echo "  make set-argocd-admin-password Store the Argo CD admin password hash in CICD_STACK=$(CICD_STACK)"
	@echo "  make preview        Run pulumi preview"
	@echo "  make preview-diff   Run pulumi preview --diff"
	@echo "  make up             Apply with pulumi up --diff --yes"
	@echo "  make destroy        Destroy stack resources"
	@echo "  make compile        Compile Python files"
	@echo "  make test           Run Pulumi mock tests"
	@echo "  make coverage       Run tests with terminal coverage report"
	@echo "  make coverage-html  Run tests and write HTML coverage to htmlcov/"
	@echo "  make generate-gitops Generate Argo CD child applications from services/"
	@echo "  make check-gitops    Fail when generated GitOps applications are stale"
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

cluster-dev:
	@if $(KIND) get clusters | grep -qx "$(DEV_CLUSTER)"; then \
		echo "kind cluster $(DEV_CLUSTER) already exists"; \
	else \
		$(KIND) create cluster --name $(DEV_CLUSTER); \
	fi

cluster-staging:
	@if $(KIND) get clusters | grep -qx "$(STAGING_CLUSTER)"; then \
		echo "kind cluster $(STAGING_CLUSTER) already exists"; \
	else \
		$(KIND) create cluster --name $(STAGING_CLUSTER); \
	fi

cluster-cicd:
	@if $(KIND) get clusters | grep -qx "$(CICD_CLUSTER)"; then \
		echo "kind cluster $(CICD_CLUSTER) already exists"; \
	else \
		$(KIND) create cluster --name $(CICD_CLUSTER); \
	fi

launch-clusters: cluster-dev cluster-staging cluster-cicd
	@echo "kind clusters ready: $(DEV_CLUSTER), $(STAGING_CLUSTER), $(CICD_CLUSTER)"

login:
	pulumi login --local

stack-init:
	$(PULUMI) stack init $(STACK)

stack-select:
	$(PULUMI) stack select $(STACK)

set-secret:
	@if [ -z "$$SECRET_VALUE" ]; then \
		echo "SECRET_VALUE is required. Example: SECRET_VALUE=local-dev-only make set-secret STACK=dev SERVICE=nginx SECRET_KEY=DUMMY_SECRET"; \
		exit 1; \
	fi
	@$(PULUMI) stack select $(STACK) >/dev/null
	@$(PULUMI) config set --secret $(SERVICE):$(SECRET_KEY) "$$SECRET_VALUE"

set-argocd-admin-password:
	@set -euo pipefail; \
		ADMIN_PASSWORD="$${ARGOCD_ADMIN_PASSWORD:-}"; \
		unset ARGOCD_ADMIN_PASSWORD; \
		if [ -z "$$ADMIN_PASSWORD" ]; then \
			read -r -s -p "Argo CD admin password: " ADMIN_PASSWORD; \
			echo; \
		fi; \
		if [ -z "$$ADMIN_PASSWORD" ]; then \
			echo "Argo CD admin password cannot be empty"; \
			exit 1; \
		fi; \
		ADMIN_PASSWORD_HASH="$$(ARGOCD_ADMIN_PASSWORD="$$ADMIN_PASSWORD" $(PYTHON) -c 'import bcrypt, os; print(bcrypt.hashpw(os.environ["ARGOCD_ADMIN_PASSWORD"].encode(), bcrypt.gensalt(rounds=12)).decode().replace("$$2b$$", "$$2a$$", 1))')"; \
		unset ADMIN_PASSWORD; \
		$(PULUMI) stack select $(CICD_STACK) >/dev/null; \
		$(PULUMI) config set --secret argocd:ADMIN_PASSWORD_BCRYPT "$$ADMIN_PASSWORD_HASH"; \
		$(PULUMI) config set --plaintext argocd:ADMIN_PASSWORD_MTIME "$$(date -u +%Y-%m-%dT%H:%M:%SZ)"

preview:
	$(PULUMI) preview $(PULUMI_STACK_ARG)

preview-diff:
	$(PULUMI) preview $(PULUMI_STACK_ARG) --diff

up:
	$(PULUMI) up $(PULUMI_STACK_ARG) --diff --yes

destroy:
	$(PULUMI) destroy $(PULUMI_STACK_ARG) --diff

stack-rm:
	$(PULUMI) stack rm $(STACK)

compile:
	$(PYTHON) -m py_compile __main__.py paas/*.py paas/argocd/__init__.py paas/ingress/__init__.py paas_platform/*.py scripts/*.py services/__init__.py

test:
	$(PYTEST) -q

coverage:
	$(PYTEST) --cov=paas --cov=paas_platform --cov-report=term-missing --cov-fail-under=100

coverage-html:
	$(PYTEST) --cov=paas --cov=paas_platform --cov-report=term-missing --cov-report=html --cov-fail-under=100

generate-gitops:
	$(PYTHON) scripts/generate_gitops.py --cluster $(STACK)

check-gitops:
	$(PYTHON) scripts/generate_gitops.py --all --check

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
