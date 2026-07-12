# Pulumi + kind Lab

This is a tiny Pulumi-powered PaaS baseline for learning how to deploy developer services to one or more Kubernetes clusters.

The example services deploy:

- a namespace named from the service and cluster environment, such as `nginx-dev`
- simple Deployments for `nginx`, `api`, and `worker`
- optional ConfigMap and Secret resources when a service declares runtime config
- a ClusterIP Service by default
- optional Ingress when a service opts in

## Prerequisites

- `kind` cluster running
- `kubectl` configured for your cluster
- Python 3 and uv
- Pulumi CLI

Official docs:

- [Install Pulumi](https://www.pulumi.com/docs/iac/download-install/)
- [Pulumi Kubernetes getting started](https://www.pulumi.com/docs/iac/get-started/kubernetes/)

## First Run

Check your Kubernetes context:

```bash
kubectl config current-context
kubectl get nodes
```

Use Pulumi's local backend while learning:

```bash
pulumi login --local
export PULUMI_CONFIG_PASSPHRASE=local-dev-only
pulumi stack select dev
uv sync
pulumi preview
pulumi up
```

Or use the Makefile shortcuts:

```bash
make setup
make install-dev
make login
make stack-select
make preview-diff
make up
```

Pulumi mock tests run without connecting to Kubernetes:

```bash
make install-dev
make pre-commit-install
make test
make coverage
```

For an HTML coverage report:

```bash
make coverage-html
```

This repository already has a `dev` stack initialized for local learning. The passphrase above is only for this disposable local lab stack; use a real secret-management approach for anything shared or production-like.

Inspect the default NGINX result:

```bash
kubectl -n nginx-dev get all
kubectl -n nginx-dev port-forward svc/nginx 8080:80
```

Or:

```bash
make kube-all
make port-forward
```

Then open `http://localhost:8080`.

The API example also exposes an Ingress declaration for `api.localhost` when your local cluster has an ingress controller installed.

## Mental Model

- `Pulumi.yaml` defines the project.
- A stack is one instance of the project, like `dev`.
- `__main__.py` invokes each service declaration.
- `paas_platform/service.py` is the reusable PaaS deployment primitive.
- `paas_platform/clusters.py` is the platform-owned cluster inventory.
- `services/` contains developer-owned service declarations.
- `pulumi preview` shows the diff.
- `pulumi up` applies the diff.
- Pulumi state remembers what it created so it can update or destroy it later.

## Adding A Service

The checked-in examples live under `services/`:

- `services/nginx/service.json` keeps the original NGINX service with env vars, Pulumi-backed secrets, and a default ClusterIP Service.
- `services/api/service.json` runs `httpd:2.4-alpine`, exposes service port `8080` to container port `80`, sets simple env vars, creates a ConfigMap from non-secret config, enables Ingress at `api.localhost`, skips Pulumi's load-balancer await for local kind, and includes a disabled `future-cluster` target to show how a declaration can prepare for another cluster without deploying there yet.
- `services/worker/service.json` runs `registry.k8s.io/pause:3.10` as a deployment-only workload with its Kubernetes Service disabled and readiness probe disabled.

Create `services/my_app/service.json`:

```json
{
  "name": "my-app",
  "image": "ghcr.io/example/my-app:latest",
  "targetClusters": ["local", "future-cluster"]
}
```

Service declarations are auto-discovered from `services/*/service.json`.

Clusters are defined by the platform in `paas_platform/clusters.py`. A service selects target cluster names; it does not own kube contexts. If no namespace is provided for a target, the platform uses:

```text
<service-name>-<cluster-environment>
```

For example, `my-app` on a `dev` cluster becomes `my-app-dev`.

Most settings are service defaults in `paas_platform/service.py`: port `80`, replicas `1`, ClusterIP service enabled, ingress disabled, readiness probe enabled, and small CPU/memory requests. Services only override them when needed:

```json
{
  "name": "api",
  "image": "httpd:2.4-alpine",
  "port": 8080,
  "containerPort": 80,
  "replicas": 2,
  "env": {
    "APP_ENV": "dev"
  },
  "ingress": {
    "enabled": true,
    "host": "api.localhost",
    "annotations": {
      "pulumi.com/skipAwait": "true"
    }
  },
  "targetClusters": [
    "local",
    {
      "name": "future-cluster",
      "enabled": false
    }
  ]
}
```

Deployment-only workloads can disable the Kubernetes Service:

```json
{
  "name": "worker",
  "image": "registry.k8s.io/pause:3.10",
  "service": {
    "enabled": false
  },
  "readinessProbe": {
    "enabled": false
  },
  "targetClusters": ["local"]
}
```

Services can also expose runtime config as environment variables. Non-secret values go in `config` and are backed by a Kubernetes ConfigMap. Secret names go in `secrets` and are backed by a Kubernetes Secret populated from encrypted Pulumi stack config. The Deployment consumes both with `envFrom`:

```json
{
  "name": "api",
  "image": "httpd:2.4-alpine",
  "config": {
    "LOG_LEVEL": "info"
  },
  "secrets": [
    "DATABASE_URL"
  ],
  "targetClusters": ["local"]
}
```

Do not commit secret values to service declarations. Each Pulumi stack owns the secret values for its environment:

```bash
SECRET_VALUE='postgres://dev.example' make set-secret ENV=dev SERVICE=api SECRET_KEY=DATABASE_URL
```

For multiple environments, prefer one stack per environment. For example, the `dev` stack deploys to dev clusters and stores dev secrets, while a future `staging` stack deploys to staging clusters and stores staging secrets under the same service/key names.
