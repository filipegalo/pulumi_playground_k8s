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
- A dedicated CI/CD PaaS stack with independent workload stacks
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
| `paas/` | Platform-owned service declarations, separate from developer workloads. |
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

Create the three kind clusters used by the platform inventory:

```bash
make launch-clusters
kubectl --context kind-dev get nodes
kubectl --context kind-staging get nodes
kubectl --context kind-cicd get nodes
```

`make launch-clusters` creates `dev`, `staging`, and `cicd` if they do not already exist. Then install dependencies and use the local Pulumi backend:

```bash
make install-dev
make login
```

Initialize each Pulumi stack once. If a stack already exists, skip its init command and select it instead.

```bash
make stack-init STACK=cicd
make stack-init STACK=dev
make stack-init STACK=staging
```

Configure and deploy the CI/CD stack first. It owns only the Argo CD installation and its admin credentials:

```bash
make set-argocd-admin-password
make up STACK=cicd
```

Each workload stack needs its own encrypted service secrets. The checked-in nginx service declares `DUMMY_SECRET` and `DUMMY_SECRET_2`, so set both keys in `dev` and `staging`:

```bash
SECRET_VALUE='<dev-nginx-secret-1>' make set-secret STACK=dev SERVICE=nginx SECRET_KEY=DUMMY_SECRET
SECRET_VALUE='<dev-nginx-secret-2>' make set-secret STACK=dev SERVICE=nginx SECRET_KEY=DUMMY_SECRET_2
SECRET_VALUE='<staging-nginx-secret-1>' make set-secret STACK=staging SERVICE=nginx SECRET_KEY=DUMMY_SECRET
SECRET_VALUE='<staging-nginx-secret-2>' make set-secret STACK=staging SERVICE=nginx SECRET_KEY=DUMMY_SECRET_2
```

Deploy the independent workload stacks after Argo CD is ready:

```bash
make up STACK=dev
make up STACK=staging
```

The Makefile sets `PULUMI_CONFIG_PASSPHRASE=local-dev-only` by default for this disposable local lab stack.

## Create everything from scratch

This section is for a disposable local reset. It destroys Pulumi-managed resources, deletes the kind clusters, recreates the clusters, initializes/selects stacks, writes required secrets, and deploys again.

The previous implementation stored the Argo CD installation in the `dev` Pulumi state. Do not run the new `cicd` stack on top of that state: destroy the old workload stacks first, then recreate all three stacks as shown below. Skip commands for stacks that do not exist yet.

If the kind clusters still exist, destroy the Pulumi resources first:

```bash
make stack-select STACK=staging
make destroy
make stack-select STACK=dev
make destroy
make stack-select STACK=cicd
make destroy
```

Then delete the kind clusters:

```bash
kind delete cluster --name staging
kind delete cluster --name dev
kind delete cluster --name cicd
```

If you already deleted the kind clusters before running `pulumi destroy`, the Pulumi stacks may still contain state for resources that no longer exist. For this disposable lab, remove and recreate the stacks:

```bash
make stack-rm STACK=staging
make stack-rm STACK=dev
make stack-rm STACK=cicd
```

Create the clusters again:

```bash
make launch-clusters
kubectl --context kind-dev get nodes
kubectl --context kind-staging get nodes
kubectl --context kind-cicd get nodes
```

Install dependencies and use the local Pulumi backend:

```bash
make install-dev
make login
```

Initialize the stacks if you removed them, or select them if they already exist:

```bash
make stack-init STACK=cicd
make stack-init STACK=dev
make stack-init STACK=staging
```

Set the Argo CD admin password and deploy the CI/CD stack first:

```bash
make set-argocd-admin-password
make up STACK=cicd
```

Set the required nginx secrets in both stacks:

```bash
SECRET_VALUE='<dev-nginx-secret-1>' make set-secret STACK=dev SERVICE=nginx SECRET_KEY=DUMMY_SECRET
SECRET_VALUE='<dev-nginx-secret-2>' make set-secret STACK=dev SERVICE=nginx SECRET_KEY=DUMMY_SECRET_2
SECRET_VALUE='<staging-nginx-secret-1>' make set-secret STACK=staging SERVICE=nginx SECRET_KEY=DUMMY_SECRET
SECRET_VALUE='<staging-nginx-secret-2>' make set-secret STACK=staging SERVICE=nginx SECRET_KEY=DUMMY_SECRET_2
```

Deploy each workload stack independently:

```bash
make up STACK=dev
make up STACK=staging
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
| `cicd` | `kind-cicd` | `platform` |

### Separate CI/CD and workload stacks

Argo CD is a platform service declared under `paas/argocd`, not a developer service under `services/`. The `cicd` stack owns the Argo CD Helm release and admin credentials. Each workload stack owns only its registration, root Application, namespaces, and secret prerequisites.

```python
"cicd": {
    "name": "cicd",
    "context": "kind-cicd",
    "environment": "platform",
    "paas": {
        "argocd": {
            "enabled": True,
            "namespace": "argocd",
            "adminPassword": {
                "configNamespace": "argocd",
                "hashConfigKey": "ADMIN_PASSWORD_BCRYPT",
                "mtimeConfigKey": "ADMIN_PASSWORD_MTIME",
            },
            "repository": {
                "url": "https://github.com/example/platform.git",
                "targetRevision": "main",
            },
        },
    },
},
"dev": {
    "name": "dev",
    "context": "kind-dev",
    "environment": "dev",
    "gitops": {
        "enabled": True,
        "cicdCluster": "cicd",
        "destination": {
            "name": "dev",
            "server": "https://dev-control-plane:6443",
            "clusterRoleName": "cluster-admin",
        },
        "registryPath": "gitops/clusters/dev/registry",
    },
}
```

Set `gitops.enabled` to `False`, or omit `gitops`, to deploy that environment's services directly with Pulumi. The ownership boundary is:

```text
cicd stack
└── kind-cicd: Argo CD Helm release and admin password

dev stack
├── kind-dev: optional PaaS, service prerequisites, and argocd-manager access
└── kind-cicd: dev registration and registry-dev Application

staging stack
├── kind-staging: optional PaaS, service prerequisites, and argocd-manager access
└── kind-cicd: staging registration and registry-staging Application
```

Deploy `cicd` before the workload stacks because they create Argo CD custom resources in `kind-cicd`. The registration uses the Kind-internal API endpoint because a host kubeconfig endpoint such as `127.0.0.1:<port>` is unreachable from Argo CD pods.

Root Applications need unique names because they coexist in the same `argocd` namespace. `registry-dev` reads `gitops/clusters/dev/registry`; `registry-staging` reads `gitops/clusters/staging/registry`. Their child Applications deploy to the corresponding registered cluster.

Developers do not write child Application YAML manually. Continue adding or changing `services/<name>/service.json` and `services/<name>/<cluster>.json`, then regenerate the derived registries:

```bash
make generate-gitops STACK=dev
make generate-gitops STACK=staging
```

`make check-gitops` and the pre-commit hook fail when committed child Applications no longer match the service declarations. Pulumi creates only namespaces and Secrets required by GitOps workloads; Argo CD owns the workloads themselves.

Each workload stack creates an `argocd-manager` service account and token in its workload cluster and an encrypted Argo CD cluster Secret in the CI/CD cluster. This playground binds `cluster-admin`; production installations should set `destination.clusterRoleName` to a constrained role.

#### Optional ingress controller

The ingress controller is another PaaS component under `paas/ingress`, outside developer-owned `services/`. It uses the maintained Traefik Helm chart. Enable or disable it independently for each workload cluster:

```python
"paas": {
    "ingress": {
        "enabled": True,
        "namespace": "traefik",
        "helm": {
            "values": {
                "providers": {
                    "kubernetesIngress": {
                        "enabled": True,
                        "ingressClass": "traefik",
                        "publishedService": {"enabled": False},
                        "ingressEndpoint": {"ip": "127.0.0.1"},
                    },
                },
                "service": {"spec": {"type": "NodePort"}},
            },
        },
    },
}
```

The checked-in inventory enables it for `dev` and disables it for `staging`. Change `enabled` and apply the corresponding workload stack:

```bash
make up STACK=dev
```

Application Ingresses explicitly use `className: traefik`. For this Kind playground, Traefik publishes `127.0.0.1` into Ingress status so Argo CD can evaluate the resource as healthy. NodePort does not automatically expose the service through Docker Desktop; use port forwarding for local access:

```bash
kubectl --context kind-dev -n traefik port-forward service/traefik 8080:80
curl -H 'Host: api.localhost' http://127.0.0.1:8080/
```

Ingress NGINX is intentionally not used because Kubernetes retired it in March 2026 and it no longer receives security fixes.

#### Initial Argo CD admin password

The password belongs only to the `cicd` Pulumi stack:

```bash
make set-argocd-admin-password
make up STACK=cicd
```

The command prompts without echoing the password, creates a salted bcrypt hash locally, and stores that hash under `argocd:ADMIN_PASSWORD_BCRYPT` as an encrypted Pulumi secret. The plaintext password is not written to the stack, shell history, or Git. For automation, it can instead read `ARGOCD_ADMIN_PASSWORD` from the environment. It also records `argocd:ADMIN_PASSWORD_MTIME`. Run the same command again with a new password, followed by `make up STACK=cicd`, to rotate it. The login username remains `admin`.

#### Public and private Git repositories

A public repository is configured once under `cicd.paas.argocd`; each workload's `gitops.registryPath` selects its own app-of-apps directory:

```python
"repository": {
    "url": "https://github.com/example/platform.git",
    "targetRevision": "main",
}
```

For a private HTTPS or SSH repository, add a credential mapping. The values below are Pulumi configuration key names, not credentials:

```python
"repository": {
    "url": "https://git.example.com/platform/repository.git",
    "targetRevision": "main",
    "credentials": {
        "secretName": "registry-repository",
        "configNamespace": "argocd",
        "usernameConfigKey": "GIT_USERNAME",
        "passwordConfigKey": "GIT_PASSWORD",
        # Use this instead of username/password for SSH repositories:
        # "sshPrivateKeyConfigKey": "GIT_SSH_KEY",
    },
}
```

Store those values encrypted in the `cicd` Pulumi stack:

```bash
pulumi config set --stack cicd --secret argocd:GIT_USERNAME <username>
pulumi config set --stack cicd --secret argocd:GIT_PASSWORD <token-or-password>
# SSH alternative:
pulumi config set --stack cicd --secret argocd:GIT_SSH_KEY <private-key-value>
```

Pulumi creates the correctly labelled Argo CD repository Secret in the `argocd` namespace. No repository credential is written into cluster inventory or GitOps manifests.

### Service declarations

`services/__init__.py` auto-discovers shared service declarations from `services/*/service.json` and combines them with the overlay file matching the selected Pulumi stack. On GitOps-enabled workload stacks, the generator turns those declarations into child Applications; targets without GitOps continue to deploy through `paas_platform.deploy_service`.

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
| `paas_platform/` and `paas/` | `services/*/service.json` and `services/*/<stack>.json` |
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
| `services/litmus/service.json` | Helm chart workload for Litmus ChaosCenter with local-kind values in `dev.json`. |

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

Overlays can override service settings for one stack, including `namespace`, `type`, `replicas`, `image`, `env`, `config`, `secrets`, `service`, `ingress`, `readinessProbe`, `resources`, `networkPolicy`, and `helm`.

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

### Helm chart services

Set `type` to `helm` when a service should be deployed from a Helm chart instead of the platform's generated Deployment and Service resources.

```json
{
  "name": "chaos",
  "type": "helm",
  "helm": {
    "chart": "litmus",
    "repository": "https://litmuschaos.github.io/litmus-helm/",
    "values": {
      "portal": {
        "frontend": {
          "service": {
            "type": "ClusterIP"
          }
        }
      }
    }
  }
}
```

Stack overlays can set the namespace and deep-merge chart values. The checked-in Litmus dev overlay installs ChaosCenter into the `litmus` namespace and uses the local-cluster values from the Helm install guide:

```json
{
  "namespace": "litmus",
  "helm": {
    "values": {
      "portal": {
        "frontend": {
          "service": {
            "type": "NodePort"
          }
        },
        "server": {
          "graphqlServer": {
            "genericEnv": {
              "CHAOS_CENTER_UI_ENDPOINT": "http://chaos-litmus-frontend-service.litmus.svc.cluster.local:9091"
            }
          }
        }
      }
    }
  }
}
```

Supported Helm options include `chart`, `repository`, `repositoryOpts`, `releaseName`, `values`, `version`, `timeout`, `skipAwait`, `skipCrds`, `dependencyUpdate`, `atomic`, and the other Pulumi Helm release flags exposed in `paas_platform/resources.py`.

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
    "className": "traefik"
  }
}
```

The platform also supports `className`, `path`, `pathType`, and `servicePort`. Ingress requires the Kubernetes Service to be enabled.

The checked-in API example declares `api.localhost` and selects the optional Traefik PaaS controller configured for `dev`.

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

The GitHub Actions workflow in `.github/workflows/logic-tests.yml` checks that generated GitOps applications are current, compiles Python, and enforces 100% coverage. Changes to service declarations trigger the workflow, so CI fails when `make generate-gitops` was not run before pushing.

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
| `make set-argocd-admin-password` | Prompt for the admin password and store its hash in `CICD_STACK`, default `cicd`. |
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
make stack-init STACK=cicd
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

Confirm that the controller is enabled for the workload cluster and that its pods, IngressClass, and application Ingress are ready:

```bash
kubectl --context kind-dev -n traefik get pods
kubectl --context kind-dev get ingressclass traefik
kubectl --context kind-dev -n api get ingress api
```

Kind does not automatically expose the Traefik NodePort through Docker Desktop. Forward the controller Service and send the configured host header:

```bash
kubectl --context kind-dev -n traefik port-forward service/traefik 8080:80
curl -H 'Host: api.localhost' http://127.0.0.1:8080/
```

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
