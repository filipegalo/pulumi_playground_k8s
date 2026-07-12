# Pulumi Playground K8s

[![Logic Tests](https://github.com/filipegalo/pulumi_playground_k8s/actions/workflows/logic-tests.yml/badge.svg)](https://github.com/filipegalo/pulumi_playground_k8s/actions/workflows/logic-tests.yml)

A small Pulumi + Kubernetes playground for modeling a PaaS-style service platform on kind.

## Contents

- [What this is](#what-this-is)
- [What you get](#what-you-get)
- [Repository layout](#repository-layout)
- [Prerequisites](#prerequisites)
- [Quickstart](#quickstart)
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

- Auto-discovered service declarations from `services/*/service.json`
- Cluster targeting from a platform-owned inventory
- Namespace defaults based on service name and cluster environment
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
| `services/` | Developer-owned service declarations. Each service lives at `services/<service>/service.json`. |
| `tests/` | Pulumi mock tests for platform behavior. |
| `.github/workflows/` | CI workflow for compile and coverage checks. |
| `Makefile` | Common local commands for Pulumi, Kubernetes inspection, tests, coverage, and hooks. |
| `Pulumi.yaml` | Pulumi project metadata and Python runtime configuration. |
| `Pulumi.dev.yaml` | Local `dev` stack config, including encrypted example secret values. |
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

Verify your Kubernetes context first:

```bash
kubectl config current-context
kubectl get nodes
```

Then use the Makefile shortcuts:

```bash
make install-dev
make login
make stack-select
make preview-diff
make up
```

The equivalent raw commands are:

```bash
uv sync
pulumi login --local
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi stack select dev
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi preview --diff
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi up --diff
```

The Makefile sets `PULUMI_CONFIG_PASSPHRASE=local-dev-only` by default for this disposable local lab stack.

## Inspect the deployment

Use the Makefile:

```bash
make kube-all
make port-forward
```

By default, those commands inspect `NAMESPACE=nginx-dev`, forward `svc/nginx`, and expose it on `http://localhost:8080`.

Raw `kubectl` equivalents:

```bash
kubectl -n nginx-dev get all
kubectl -n nginx-dev port-forward svc/nginx 8080:80
```

For another service:

```bash
make kube-all NAMESPACE=api-dev
make port-forward NAMESPACE=api-dev SERVICE=api LOCAL_PORT=8080 SERVICE_PORT=8080
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
| `local` | `kind-local` | `dev` |
| `future-cluster` | `some-other-context` | `staging` |

Targets can be disabled, which lets a service declaration describe a future target without deploying it yet.

### Service declarations

`services/__init__.py` auto-discovers service declarations from `services/*/service.json`. `__main__.py` deploys each discovered service with `paas_platform.deploy_service`.

Each declaration starts with a service name, image, and target clusters:

```json
{
  "name": "my-app",
  "image": "ghcr.io/example/my-app:latest",
  "targetClusters": ["local"]
}
```

### Namespace naming

If a target does not set `namespace`, the platform uses:

```text
<service-name>-<cluster-environment>
```

For example, `my-app` on the `local` dev cluster becomes `my-app-dev`.

### Platform defaults and service overrides

Defaults resolve in this order:

```text
platform service defaults < environment defaults < service overrides < target cluster overrides
```

Platform defaults live in `paas_platform/defaults.py`. They include port `80`, one replica, ClusterIP Service behavior, Ingress disabled, readiness probe enabled, NetworkPolicy disabled, and CPU/memory requests and limits.

## Platform-owned vs developer-owned

| Platform-owned | Developer-owned |
| --- | --- |
| `paas_platform/` | `services/*/service.json` |
| Cluster inventory | Service name and image |
| Default behavior | Target cluster selection |
| Deployment logic | Service-level overrides |
| Tests | Runtime config names |
| CI | Secret names, not secret values |

## Adding a service

Create `services/my_app/service.json`:

```json
{
  "name": "my-app",
  "image": "ghcr.io/example/my-app:latest",
  "targetClusters": ["local"]
}
```

Service declarations are auto-discovered from `services/*/service.json`. Run `make preview-diff` to see the resources Pulumi would create, then `make up` to apply them.

Current examples:

| Service | What it shows |
| --- | --- |
| `services/nginx/service.json` | Basic web workload with env vars, Pulumi-backed secrets, and NetworkPolicy enabled. |
| `services/api/service.json` | Custom service/container ports, ConfigMap-backed config, Ingress, and a disabled future target. |
| `services/worker/service.json` | Deployment-only workload with Kubernetes Service and readiness probe disabled. |

## Service configuration reference

### Basic fields

```json
{
  "name": "api",
  "image": "httpd:2.4-alpine",
  "env": {
    "APP_ENV": "dev"
  },
  "targetClusters": ["local"]
}
```

- `name` becomes the Kubernetes resource name.
- `image` becomes the container image.
- `env` adds literal container environment variables.

### Target clusters

Targets can be strings or objects:

```json
{
  "targetClusters": [
    "local",
    {
      "name": "future-cluster",
      "enabled": false
    }
  ]
}
```

Object targets can override service settings for one cluster, including `namespace`, `replicas`, `image`, `env`, `config`, `secrets`, `service`, `ingress`, `readinessProbe`, `resources`, and `networkPolicy`.

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
SECRET_VALUE='postgres://dev.example' make set-secret ENV=dev SERVICE=api SECRET_KEY=DATABASE_URL
```

Do not commit secret values to service declarations.

## Secrets

Secrets are split between developer declarations and stack config:

- `services/*/service.json` declares the names the service expects.
- Pulumi stack config stores the encrypted values for each environment.
- Kubernetes Secret resources are created from Pulumi stack config at deployment time.

For multiple environments, prefer one stack per environment. For example, a `dev` stack stores dev secrets and a future `staging` stack stores staging secrets under the same service/key names.

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
| `make install-dev` | Install runtime and dev dependencies with `uv sync`. |
| `make preview-diff` | Run `pulumi preview --diff`. |
| `make up` | Apply changes with `pulumi up --diff`. |
| `make destroy` | Destroy stack resources with `pulumi destroy --diff`. |
| `make kube-all` | List resources in `NAMESPACE`, default `nginx-dev`. |
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

Select the local `dev` stack:

```bash
make stack-select
```

Raw equivalent:

```bash
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi stack select dev
```

### kind context not found

The `local` cluster target expects kube context `kind-local`. Check your contexts:

```bash
kubectl config get-contexts
```

Create or switch to a matching kind cluster before running Pulumi.

### Ingress does not work locally

The `api.localhost` Ingress declaration only creates Kubernetes Ingress resources. A local kind cluster still needs an ingress controller, and Pulumi may need `pulumi.com/skipAwait` for local controller behavior.

For a quick local check, use `make port-forward` instead of Ingress.

### Secret value missing

If a service declares a secret name, Pulumi requires a matching stack config entry:

```bash
SECRET_VALUE='value-for-local-dev' make set-secret ENV=dev SERVICE=api SECRET_KEY=DATABASE_URL
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
