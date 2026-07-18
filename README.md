# Pulumi Playground K8s

[![Logic Tests](https://github.com/filipegalo/pulumi_playground_k8s/actions/workflows/logic-tests.yml/badge.svg)](https://github.com/filipegalo/pulumi_playground_k8s/actions/workflows/logic-tests.yml)

A local Kubernetes platform playground built with Pulumi, Kind, Argo CD, and Traefik. It separates a CI/CD management cluster from workload clusters and models the ownership boundaries of a small PaaS.

## What it models

- A dedicated `cicd` cluster that runs Argo CD.
- Independent `dev`, `staging`, and future workload clusters.
- Platform-owned PaaS components under `paas/`.
- Developer-owned workload declarations under `services/`.
- Argo CD app-of-apps deployment through one `registry-<cluster>` root Application per workload cluster.
- Pulumi-managed cluster registration, namespaces, and secret prerequisites.
- Optional per-cluster Traefik ingress.
- Public or private Git repositories.
- Generated GitOps manifests checked locally and in CI.

## Architecture at a glance

```text
Pulumi stack: cicd
└── kind-cicd
    └── Argo CD

Pulumi stack: dev
├── kind-dev
│   ├── optional PaaS (Traefik)
│   ├── Argo CD service account and cluster access
│   └── workload Secrets that must not be committed to Git
└── kind-cicd
    ├── dev cluster registration
    └── registry-dev Application
        ├── api-dev Application
        └── nginx-dev Application

Pulumi stack: staging
├── kind-staging
│   ├── optional PaaS
│   ├── Argo CD service account and cluster access
│   └── workload Secrets
└── kind-cicd
    ├── staging cluster registration
    └── registry-staging Application
        └── nginx-staging Application
```

Argo CD uses the Kind-internal API addresses such as `https://dev-control-plane:6443`. A host kubeconfig address such as `https://127.0.0.1:<port>` is not reachable from a pod in the CI/CD cluster.

### Ownership

| Owner | Source | Responsibilities |
| --- | --- | --- |
| Platform | `paas_platform/`, `paas/`, `paas_platform/clusters.py` | Cluster inventory, PaaS components, defaults, providers, GitOps registration, and secret prerequisites |
| Developer | `services/<name>/service.json`, `services/<name>/<cluster>.json` | Image or chart, runtime settings, target clusters, ports, ingress, resources, and secret names |
| Generator | `scripts/generate_gitops.py` | Deterministic Argo CD child Application manifests |
| Argo CD | `gitops/` | Workload reconciliation, pruning, and self-healing |

Argo CD and Traefik are installed directly by Pulumi as PaaS components. They are not child Applications inside `registry-<cluster>`.

## Repository layout

| Path | Purpose |
| --- | --- |
| `paas_platform/` | Reusable platform logic, defaults, labels, resource builders, and cluster inventory |
| `paas/argocd/` | Argo CD PaaS component and workload-cluster registration |
| `paas/ingress/` | Optional Traefik PaaS component |
| `services/` | Developer service declarations and cluster overlays |
| `gitops/charts/service/` | Shared Helm chart for container services |
| `gitops/clusters/<cluster>/registry/` | Generated Argo CD child Applications |
| `scripts/generate_gitops.py` | GitOps manifest generator and drift checker |
| `tests/` | Pulumi mock tests |
| `.github/workflows/logic-tests.yml` | GitOps drift, compilation, and coverage checks |
| `Pulumi.<stack>.yaml` | Local lab stack configuration |

## Documentation

Use the guide that matches what you are doing:

| Scenario | Guide |
| --- | --- |
| First installation or a completely clean rebuild | [Getting started](docs/getting-started.md) |
| Understand stack, cluster, PaaS, and GitOps ownership | [Architecture](docs/architecture.md) |
| Add, update, remove, or move a service between clusters | [GitOps workflow](docs/gitops.md) |
| Configure containers, Helm charts, ingress, probes, resources, or NetworkPolicy | [Service configuration](docs/services.md) |
| Enable, disable, or operate Argo CD and Traefik | [PaaS components](docs/paas.md) |
| Deploy stacks, inspect clusters, expose services, rotate credentials, or enable PaaS | [Operations](docs/operations.md) |
| Manage service secrets, Argo CD passwords, and private repository credentials | [Secrets and credentials](docs/secrets.md) |
| Diagnose Pulumi, Argo CD, GitOps, cluster connectivity, or ingress failures | [Troubleshooting](docs/troubleshooting.md) |
| Extend platform fields, clusters, charts, or PaaS components | [Contributing](docs/contributing.md) |

## Prerequisites

- `kind`
- `kubectl`
- `uv`
- Pulumi CLI
- Python 3.14, as pinned by `.python-version`
- Docker or another Kind-compatible container runtime

## Quickstart

Install dependencies, select the local Pulumi backend, and create all three Kind clusters:

```bash
make install-dev
make login
make launch-clusters

kubectl --context kind-cicd get nodes
kubectl --context kind-dev get nodes
kubectl --context kind-staging get nodes
```

Initialize each Pulumi stack once. If one already exists, use `make stack-select STACK=<name>` instead.

```bash
make stack-init STACK=cicd
make stack-init STACK=dev
make stack-init STACK=staging
```

Ensure the repository URL in `paas_platform/clusters.py` points to the Git repository Argo CD should watch. Configure the Argo CD administrator and deploy the CI/CD stack first:

```bash
make set-argocd-admin-password
make up STACK=cicd
```

Set the example nginx secrets for each workload stack:

```bash
SECRET_VALUE='dev-example-one' make set-secret STACK=dev SERVICE=nginx SECRET_KEY=DUMMY_SECRET
SECRET_VALUE='dev-example-two' make set-secret STACK=dev SERVICE=nginx SECRET_KEY=DUMMY_SECRET_2
SECRET_VALUE='staging-example-one' make set-secret STACK=staging SERVICE=nginx SECRET_KEY=DUMMY_SECRET
SECRET_VALUE='staging-example-two' make set-secret STACK=staging SERVICE=nginx SECRET_KEY=DUMMY_SECRET_2
```

Confirm that the committed child Applications match the service declarations, then deploy the workload stacks:

```bash
make check-gitops
make up STACK=dev
make up STACK=staging
```

Inspect the result with explicit contexts:

```bash
kubectl --context kind-cicd -n argocd get applications
kubectl --context kind-dev -n api get all
kubectl --context kind-dev -n nginx get all
kubectl --context kind-staging -n nginx get all
```

For a disposable clean installation, including teardown commands and recovery when clusters have already been deleted, follow [Getting started](docs/getting-started.md).

## Add a service

Create `services/my_app/service.json`:

```json
{
  "name": "my-app",
  "image": "ghcr.io/example/my-app:1.0.0"
}
```

Add `services/my_app/dev.json` for the dev cluster:

```json
{
  "env": {
    "APP_ENV": "dev"
  }
}
```

If the declaration includes Pulumi-backed secret names, configure those values and run `make up STACK=dev` before publishing the child Application. See [Secrets and credentials](docs/secrets.md#add-a-secret-to-an-existing-service).

Generate and validate the child Application:

The commands below assume the checked-in `targetRevision: master`. If you configure another branch, push or merge the change into that revision instead.

```bash
make generate-gitops STACK=dev
make check-gitops
make pre-commit
git add services/my_app gitops/clusters/dev/registry/my-app.yaml
git commit -m "feat: deploy my-app to dev"
git push origin master
```

Argo CD reads only committed and pushed Git content. `make up STACK=dev` is also required when Pulumi-owned prerequisites changed or when the workload cluster has not been registered yet.

The overlay controls membership. Without `services/my_app/dev.json`, the service is not generated or deployed to `dev`. Removing that overlay and regenerating removes the child Application; automated pruning removes its Argo-managed resources. If the service used Pulumi-backed secrets, reconcile the workload stack after pruning to remove those prerequisites.

See [GitOps workflow](docs/gitops.md) for updates, removals, multi-cluster deployment, Helm services, direct-Pulumi mode, and reconciliation behavior.

## Optional PaaS components

PaaS components are enabled independently in `paas_platform/clusters.py`:

```python
"paas": {
    "ingress": {
        "enabled": True,
    },
}
```

The checked-in inventory has:

- Argo CD enabled only on `cicd`.
- Traefik enabled on `dev`.
- Traefik disabled on `staging`.

The abbreviated snippet is enough only when the cluster already retains the complete Helm configuration, as dev does. Before enabling staging, copy or centralize dev's Kind-specific values; changing staging's lone disabled flag would use chart defaults.

Apply a PaaS toggle with the stack that owns that cluster:

```bash
make up STACK=dev
```

See [PaaS components](docs/paas.md#current-dev-configuration) for the complete Traefik configuration, enablement caveat, and verification steps.

## Local access

Argo CD:

```bash
kubectl --context kind-cicd -n argocd port-forward service/argocd-server 8080:443
```

Then open `https://127.0.0.1:8080` and sign in as `admin` with the password configured by `make set-argocd-admin-password`.

The API through Traefik:

```bash
kubectl --context kind-dev -n traefik port-forward service/traefik 8081:80
curl -H 'Host: api.localhost' http://127.0.0.1:8081/
```

The `127.0.0.1` value published in Ingress status is for Argo CD health evaluation. It does not expose a Kind NodePort through Docker Desktop; port forwarding is still required.

## Validation

```bash
make test          # Pulumi mock tests
make coverage      # 100% platform-logic coverage gate
make check-gitops  # generated child Applications match declarations
make compile       # Python compilation
make pre-commit    # all repository hooks
```

`make validate STACK=dev` additionally runs a live Pulumi preview and therefore requires the corresponding Kind cluster and stack configuration.

## Safety boundaries

This repository is a disposable local lab:

- The Makefile uses the known passphrase `local-dev-only`.
- Checked-in Pulumi stack files must contain only lab values.
- The Argo CD workload identity is bound to `cluster-admin` for simplicity.
- GitOps uses automated pruning and self-healing.
- Removing an overlay can delete the service resources managed by its child Application.
- Use a secret manager, restricted RBAC, protected branches, pinned chart versions, and encrypted Kubernetes storage for production-like environments.
