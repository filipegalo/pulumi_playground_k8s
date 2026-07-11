# Pulumi + kind Lab

This is a tiny Pulumi-powered PaaS baseline for learning how to deploy developer services to one or more Kubernetes clusters.

The example service deploys:

- a namespace named from the service and cluster environment, such as `nginx-dev`
- an NGINX Deployment
- a ClusterIP Service by default
- no Ingress by default

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

Inspect the result:

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
  "image": "ghcr.io/example/api:latest",
  "port": 8080,
  "replicas": 2,
  "ingress": {
    "enabled": true,
    "host": "api.localhost"
  },
  "targetClusters": ["local"]
}
```
