# Pulumi Playground K8s

[![Logic Tests](https://github.com/filipegalo/pulumi_playground_k8s/actions/workflows/logic-tests.yml/badge.svg)](https://github.com/filipegalo/pulumi_playground_k8s/actions/workflows/logic-tests.yml)

A small Pulumi + Kubernetes playground for modeling a PaaS-style service platform on kind.

## Contents

- [What this is](#what-this-is)
- [What you get](#what-you-get)
- [Repository layout](#repository-layout)
- [Prerequisites](#prerequisites)
- [Quickstart](#quickstart)
- [Create everything from scratch](#create-everything-from-scratch)
- [Inspect the deployment](#inspect-the-deployment)
- [Core concepts](#core-concepts)
- [Platform-owned vs developer-owned](#platform-owned-vs-developer-owned)
- [Adding a service](#adding-a-service)
- [Service configuration reference](#service-configuration-reference)
- [Secrets](#secrets)
- [Testing and quality](#testing-and-quality)
- [Common commands](#common-commands)
- [Troubleshooting](#troubleshooting)

## What this is

Pulumi Playground K8s is a Pulumi + Kubernetes playground that models a tiny PaaS-style platform. Platform code owns cluster targeting and Kubernetes resource creation; developers add applications through compact service declarations under `services/`.

## What you get

- Auto-discovered service declarations from `services/*/service.json` plus stack-specific overlays such as `dev.json` and `staging.json`
- Cluster targeting from a platform-owned inventory
- Namespace defaults based on service name
- Kubernetes Deployments, Services, optional Ingress, and optional NetworkPolicy
- ConfigMaps and Secrets for runtime configuration
- Pulumi mock tests that do not connect to Kubernetes
- 100% coverage gate for platform logic
- Local pre-commit hooks
- GitHub Actions workflow for platform logic changes

## Repository layout

| Path | Purpose |
| --- | --- |
| `paas_platform/` | Reusable PaaS deployment primitives, defaults, labels, cluster inventory, and Kubernetes resource builders. |
| `services/` | Developer-owned service declarations. Shared config lives at `services/<service>/service.json`; stack overlays live next to it, such as `dev.json` and `staging.json`. |
| `tests/` | Pulumi mock tests for platform behavior. |
| `.github/workflows/` | CI workflow for compile and coverage checks. |
| `Makefile` | Common local commands for Pulumi, Kubernetes inspection, tests, coverage, and hooks. |
| `Pulumi.yaml` | Pulumi project metadata and Python runtime configuration. |
| `Pulumi.dev.yaml` | Local `dev` stack config, including encrypted example secret values. |
| `Pulumi.staging.yaml` | Local `staging` stack config, including encrypted example secret values. |
| `pyproject.toml` | Python package metadata, runtime dependencies, and dev dependencies. |
| `uv.lock` | Locked Python dependency graph managed by `uv`. |

## Prerequisites

- `kind`
- `kubectl`
- `uv`
- Pulumi CLI
- Python 3.14, as pinned by `.python-version`

Useful upstream docs:

- [Install Pulumi](https://www.pulumi.com/docs/iac/download-install/)
- [Pulumi Kubernetes getting started](https://www.pulumi.com/docs/iac/get-started/kubernetes/)

## Quickstart

Create the two kind clusters used by the platform inventory:

```bash
make launch-clusters
kubectl --context kind-dev get nodes
kubectl --context kind-staging get nodes
```

`make launch-clusters` creates `dev` and `staging` if they do not already exist. Then install dependencies and use the local Pulumi backend:

```bash
make install-dev
make login
```

Initialize each Pulumi stack once. If a stack already exists, skip its init command and select it instead.

```bash
make stack-init STACK=dev
make stack-init STACK=staging
```

Each stack needs its own encrypted secret values. The checked-in nginx service declares `DUMMY_SECRET` and `DUMMY_SECRET_2`, so set both keys in each stack:

```bash
SECRET_VALUE='<dev-nginx-secret-1>' make set-secret STACK=dev SERVICE=nginx SECRET_KEY=DUMMY_SECRET
SECRET_VALUE='<dev-nginx-secret-2>' make set-secret STACK=dev SERVICE=nginx SECRET_KEY=DUMMY_SECRET_2
SECRET_VALUE='<staging-nginx-secret-1>' make set-secret STACK=staging SERVICE=nginx SECRET_KEY=DUMMY_SECRET
SECRET_VALUE='<staging-nginx-secret-2>' make set-secret STACK=staging SERVICE=nginx SECRET_KEY=DUMMY_SECRET_2
```

Deploy dev:

```bash
make stack-select STACK=dev
make preview-diff
make up
```

Deploy staging:

```bash
make stack-select STACK=staging
make preview-diff
make up
```

The equivalent raw commands are:

```bash
kind create cluster --name dev
kind create cluster --name staging
uv sync
pulumi login --local
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi stack init dev
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi stack init staging
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi stack select dev
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi config set --secret nginx:DUMMY_SECRET '<dev-nginx-secret-1>'
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi config set --secret nginx:DUMMY_SECRET_2 '<dev-nginx-secret-2>'
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi stack select staging
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi config set --secret nginx:DUMMY_SECRET '<staging-nginx-secret-1>'
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi config set --secret nginx:DUMMY_SECRET_2 '<staging-nginx-secret-2>'
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi stack select dev
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi preview --diff
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi up --diff --yes
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi stack select staging
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi preview --diff
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi up --diff --yes
```

The Makefile sets `PULUMI_CONFIG_PASSPHRASE=local-dev-only` by default for this disposable local lab stack.

## Create everything from scratch

This section is for a disposable local reset. It destroys Pulumi-managed resources, deletes the kind clusters, recreates the clusters, initializes/selects stacks, writes required secrets, and deploys again.

If the kind clusters still exist, destroy the Pulumi resources first:

```bash
make stack-select STACK=staging
make destroy
make stack-select STACK=dev
make destroy
```

Then delete the kind clusters:

```bash
kind delete cluster --name staging
kind delete cluster --name dev
```

If you already deleted the kind clusters before running `pulumi destroy`, the Pulumi stacks may still contain state for resources that no longer exist. For this disposable lab, remove and recreate the stacks:

```bash
make stack-rm STACK=staging
make stack-rm STACK=dev
```

Create the clusters again:

```bash
make launch-clusters
kubectl --context kind-dev get nodes
kubectl --context kind-staging get nodes
```

Install dependencies and use the local Pulumi backend:

```bash
make install-dev
make login
```

Initialize the stacks if you removed them, or select them if they already exist:

```bash
make stack-init STACK=dev
make stack-init STACK=staging
```

Set the required nginx secrets in both stacks:

```bash
SECRET_VALUE='<dev-nginx-secret-1>' make set-secret STACK=dev SERVICE=nginx SECRET_KEY=DUMMY_SECRET
SECRET_VALUE='<dev-nginx-secret-2>' make set-secret STACK=dev SERVICE=nginx SECRET_KEY=DUMMY_SECRET_2
SECRET_VALUE='<staging-nginx-secret-1>' make set-secret STACK=staging SERVICE=nginx SECRET_KEY=DUMMY_SECRET
SECRET_VALUE='<staging-nginx-secret-2>' make set-secret STACK=staging SERVICE=nginx SECRET_KEY=DUMMY_SECRET_2
```

Deploy dev:

```bash
make stack-select STACK=dev
make preview-diff
make up
```

Deploy staging:

```bash
make stack-select STACK=staging
make preview-diff
make up
```

## Inspect the deployment

Use the Makefile:

```bash
make kube-all
make port-forward
```

By default, those commands inspect `NAMESPACE=nginx`, forward `svc/nginx`, and expose it on `http://localhost:8080`.

Raw `kubectl` equivalents:

```bash
kubectl -n nginx get all
kubectl -n nginx port-forward svc/nginx 8080:80
```

For another service:

```bash
make kube-all NAMESPACE=api
make port-forward NAMESPACE=api SERVICE=api LOCAL_PORT=8080 SERVICE_PORT=8080
```

For nginx on staging:

```bash
kubectl --context kind-staging -n nginx get all
kubectl --context kind-staging -n nginx port-forward svc/nginx 8081:80
```

## Core concepts

### Pulumi project and stack

`Pulumi.yaml` defines the Pulumi project: name, description, runtime, and project-level metadata. A stack is one configured instance of that project, such as `dev`.

`Pulumi.dev.yaml` stores the checked-in `dev` stack configuration for local learning. It contains encrypted example secrets for the `nginx` service.

### Local backend and passphrase

`make login` runs `pulumi login --local`, so Pulumi state is stored in your local Pulumi home, usually `~/.pulumi`.

`PULUMI_CONFIG_PASSPHRASE` is required because Pulumi encrypts stack secrets. The Makefile defaults it to `local-dev-only` for this playground. Use a real secret-management approach for anything shared or production-like.

### Cluster inventory

Clusters are platform-owned in `paas_platform/clusters.py`. A service selects cluster names, but it does not own kube contexts.

| Cluster | Kube context | Environment |
| --- | --- | --- |
| `dev` | `kind-dev` | `dev` |
| `staging` | `kind-staging` | `staging` |

### Service declarations

`services/__init__.py` auto-discovers shared service declarations from `services/*/service.json` and combines them with the overlay file matching the selected Pulumi stack. `__main__.py` deploys each discovered service with `paas_platform.deploy_service`.

Each shared declaration starts with a service name and image:

```json
{
  "name": "my-app",
  "image": "ghcr.io/example/my-app:latest"
}
```

An overlay filename selects the target cluster. For example, `services/my_app/dev.json` deploys the service to the `dev` cluster when the selected Pulumi stack is `dev`:

```json
{
  "env": {
    "APP_ENV": "dev"
  }
}
```

### Namespace naming

If a target does not set `namespace`, the platform uses:

```text
<service-name>
```

For example, `my-app` on the `dev` cluster becomes `my-app`.

### Platform defaults and service overrides

Defaults resolve in this order:

```text
platform service defaults < environment defaults < service config < stack overlay
```

Platform defaults live in `paas_platform/defaults.py`. They include port `80`, one replica, ClusterIP Service behavior, Ingress disabled, readiness probe enabled, NetworkPolicy disabled, and CPU/memory requests and limits.

## Platform-owned vs developer-owned

| Platform-owned | Developer-owned |
| --- | --- |
| `paas_platform/` | `services/*/service.json` and `services/*/<stack>.json` |
| Cluster inventory | Service name and image |
| Default behavior | Stack-specific service overlays |
| Deployment logic | Service-level and stack-level overrides |
| Tests | Runtime config names |
| CI | Secret names, not secret values |

## Adding a service

Create `services/my_app/service.json`:

```json
{
  "name": "my-app",
  "image": "ghcr.io/example/my-app:latest"
}
```

Then create `services/my_app/dev.json`:

```json
{
  "env": {
    "APP_ENV": "dev"
  }
}
```

Service declarations are auto-discovered by combining `service.json` with the overlay matching the selected stack. Run `make stack-select STACK=dev`, then `make preview-diff` to see the resources Pulumi would create, and `make up` to apply them.

Current examples:

| Service | What it shows |
| --- | --- |
| `services/nginx/service.json` | Basic web workload with Pulumi-backed secrets and NetworkPolicy enabled. It has both `dev.json` and `staging.json` overlays. |
| `services/api/service.json` | Custom service/container ports, ConfigMap-backed config, and Ingress. |
| `services/worker/service.json` | Deployment-only workload with Kubernetes Service and readiness probe disabled. |

## Service configuration reference

### Basic fields

```json
{
  "name": "api",
  "image": "httpd:2.4-alpine",
  "env": {
    "SERVICE_ROLE": "api"
  }
}
```

- `name` becomes the Kubernetes resource name.
- `image` becomes the container image.
- `env` adds literal container environment variables.

### Stack overlays

Overlay files are named after cluster targets. For example, `dev.json` deploys to the `dev` cluster and `staging.json` deploys to the `staging` cluster.

```json
{
  "env": {
    "APP_ENV": "dev"
  }
}
```

Overlays can override service settings for one stack, including `namespace`, `replicas`, `image`, `env`, `config`, `secrets`, `service`, `ingress`, `readinessProbe`, `resources`, and `networkPolicy`.

### Ports

```json
{
  "port": 8080,
  "containerPort": 80
}
```

`port` is the Kubernetes Service port. `containerPort` is the container port. If `containerPort` is omitted, it defaults to `port`.

### Replicas

```json
{
  "replicas": 2
}
```

The platform default is one replica for `dev` and two replicas for `staging`.

### Kubernetes service

Services are enabled by default as `ClusterIP`:

```json
{
  "service": {
    "type": "ClusterIP"
  }
}
```

Deployment-only workloads can disable the Kubernetes Service:

```json
{
  "service": {
    "enabled": false
  }
}
```

Custom Service ports are supported:

```json
{
  "service": {
    "ports": [
      {
        "name": "http",
        "port": 9000,
        "targetPort": 80
      }
    ]
  }
}
```

### Ingress

Ingress is disabled by default:

```json
{
  "ingress": {
    "enabled": true,
    "host": "api.localhost",
    "annotations": {
      "pulumi.com/skipAwait": "true"
    }
  }
}
```

The platform also supports `className`, `path`, `pathType`, and `servicePort`. Ingress requires the Kubernetes Service to be enabled.

The checked-in API example declares `api.localhost`, but local Ingress only works if your kind cluster has an ingress controller installed and configured.

### Readiness probe

Readiness probes are enabled by default:

```json
{
  "readinessProbe": {
    "enabled": true,
    "path": "/",
    "initialDelaySeconds": 3,
    "periodSeconds": 5
  }
}
```

Disable the probe for workloads that do not serve HTTP:

```json
{
  "readinessProbe": {
    "enabled": false
  }
}
```

### Resources

```json
{
  "resources": {
    "requests": {
      "cpu": "50m",
      "memory": "64Mi"
    },
    "limits": {
      "cpu": "250m",
      "memory": "256Mi"
    }
  }
}
```

Resource dictionaries are deep-merged with platform and environment defaults, so a service can override only one value.

### ConfigMaps

Non-secret runtime config goes in `config`. If present, the platform creates a Kubernetes ConfigMap and attaches it to the Deployment with `envFrom`.

```json
{
  "config": {
    "LOG_LEVEL": "info",
    "FEATURE_FLAG": "platform-examples"
  }
}
```

### Secrets

Service files declare secret names only:

```json
{
  "secrets": ["DATABASE_URL"]
}
```

Secret values live in encrypted Pulumi stack config. If `secrets` is present, the platform creates a Kubernetes Secret and attaches it to the Deployment with `envFrom`.

Set a local stack secret with:

```bash
SECRET_VALUE='<api-database-url>' make set-secret STACK=dev SERVICE=api SECRET_KEY=DATABASE_URL
```

Do not commit secret values to service declarations.

## Secrets

Secrets are split between developer declarations and stack config:

- `services/*/service.json` declares the names the service expects.
- `services/*/<stack>.json` declares stack-specific runtime settings.
- Pulumi stack config stores the encrypted values for each environment.
- Kubernetes Secret resources are created from Pulumi stack config at deployment time.

Use one stack per environment. For example, the `dev` stack stores dev secrets and the `staging` stack stores staging secrets under the same service/key names.

## Testing and quality

Run the Pulumi mock tests:

```bash
make test
```

Run tests with the 100% coverage gate:

```bash
make coverage
```

Run compile, coverage, and Pulumi preview:

```bash
make validate
```

Install and run local pre-commit hooks:

```bash
make pre-commit-install
make pre-commit
```

The GitHub Actions workflow in `.github/workflows/logic-tests.yml` runs compile and 100% coverage checks for pull requests and pushes that change platform logic. Changes only under `services/**` are ignored by that workflow.

## Common commands

| Command | What it does |
| --- | --- |
| `make launch-clusters` | Create the `dev` and `staging` kind clusters if missing. |
| `make cluster-dev` | Create the `dev` kind cluster if missing. |
| `make cluster-staging` | Create the `staging` kind cluster if missing. |
| `make install-dev` | Install runtime and dev dependencies with `uv sync`. |
| `make stack-init STACK=dev` | Initialize a Pulumi stack. Run once per stack. |
| `make stack-select STACK=dev` | Select the Pulumi stack whose overlay files should deploy. |
| `make stack-rm STACK=dev` | Remove a disposable local Pulumi stack. |
| `make set-secret STACK=dev SERVICE=nginx SECRET_KEY=DUMMY_SECRET` | Set one encrypted Pulumi secret from `SECRET_VALUE`. |
| `make preview-diff` | Run `pulumi preview --diff`. |
| `make up` | Apply changes with `pulumi up --diff --yes`. |
| `make destroy` | Destroy stack resources with `pulumi destroy --diff`. |
| `make kube-all` | List resources in `NAMESPACE`, default `nginx`. |
| `make port-forward` | Forward `LOCAL_PORT` to `SERVICE`, default `nginx` on `8080:80`. |
| `make test` | Run Pulumi mock tests. |
| `make coverage` | Run tests with terminal coverage and `--cov-fail-under=100`. |
| `make validate` | Compile Python, run coverage, and run `preview --diff`. |
| `make pre-commit-install` | Install `.githooks/pre-commit` through `core.hooksPath`. |
| `make pre-commit` | Run pre-commit hooks against all files. |

## Troubleshooting

### Missing passphrase

If Pulumi asks for a config passphrase or cannot decrypt secrets, use the Makefile commands or export the local lab passphrase:

```bash
export PULUMI_CONFIG_PASSPHRASE=local-dev-only
```

### No stack selected

Initialize the stack once if it does not already exist:

```bash
make stack-init STACK=dev
make stack-init STACK=staging
```

Then select the stack you want to deploy:

```bash
make stack-select STACK=dev
make stack-select STACK=staging
```

Raw equivalent:

```bash
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi stack init dev
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi stack init staging
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi stack select dev
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi stack select staging
```

### kind context not found

The `dev` cluster target expects kube context `kind-dev`. Check your contexts:

```bash
kubectl config get-contexts
```

Create or switch to a matching kind cluster before running Pulumi.

```bash
make launch-clusters
```

### Kubernetes resource already exists

If `pulumi preview` or `pulumi up` reports that namespaces, Deployments, Services, or other resources already exist, the live kind cluster has resources that are not tracked in the selected Pulumi stack. This can happen after a partial failed update, a stack reset, or a resource-name refactor.

For a disposable kind lab, the simplest recovery is to delete the affected namespaces and run `make up` again:

```bash
kubectl --context kind-dev delete namespace api nginx worker
make up
```

For non-disposable environments, import the existing Kubernetes resources into Pulumi state instead of deleting them.

### Pulumi waits for LoadBalancer IP

Plain kind clusters do not allocate external IPs for `LoadBalancer` Services by default. If Pulumi is stuck on `Attempting to allocate IP address to Service`, stop the update and avoid `LoadBalancer` for local kind clusters unless you have installed a load balancer integration such as MetalLB or cloud-provider-kind.

This playground defaults both `dev` and `staging` Services to `ClusterIP`. If a previous update is still marked in progress after stopping it, clear the Pulumi lock with:

```bash
pulumi cancel
```

### Ingress does not work locally

The `api.localhost` Ingress declaration only creates Kubernetes Ingress resources. A local kind cluster still needs an ingress controller, and Pulumi may need `pulumi.com/skipAwait` for local controller behavior.

For a quick local check, use `make port-forward` instead of Ingress.

### Secret value missing

If a service declares a secret name, Pulumi requires a matching stack config entry:

```bash
SECRET_VALUE='<api-database-url>' make set-secret STACK=dev SERVICE=api SECRET_KEY=DATABASE_URL
```

The config key format is `<service>:<secret-name>`.

### Pre-commit hook installation with core.hooksPath

`make pre-commit-install` configures Git to use `.githooks`:

```bash
git config core.hooksPath .githooks
```

If hooks do not run, check the current setting:

```bash
git config core.hooksPath
```
