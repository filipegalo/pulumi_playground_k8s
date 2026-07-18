# Getting started

Use this guide for a first installation, an existing local installation, or a complete disposable rebuild.

## Prerequisites

Install:

- Docker or another Kind-compatible container runtime
- `kind`
- `kubectl`
- Pulumi CLI
- `uv`
- Python 3.14, as pinned by `.python-version`

Confirm the tools are available:

```bash
kind version
kubectl version --client
pulumi version
uv --version
```

## Understand the three stacks

| Pulumi stack | Primary cluster | Purpose |
| --- | --- | --- |
| `cicd` | `kind-cicd` | Argo CD, its administrator configuration, and optional repository credentials |
| `dev` | `kind-dev` plus registration resources in `kind-cicd` | Dev PaaS, workload secret prerequisites, cluster registration, and `registry-dev` |
| `staging` | `kind-staging` plus registration resources in `kind-cicd` | Staging PaaS, workload secret prerequisites, cluster registration, and `registry-staging` |

Deploy `cicd` first. The workload stacks create Argo CD custom resources and therefore require the Argo CD CRDs to exist.

## First installation

### 1. Install project dependencies

```bash
make install-dev
make login
```

`make login` selects Pulumi's local backend. Local backend state is normally stored under `~/.pulumi`.

### 2. Create all Kind clusters

```bash
make launch-clusters
```

Verify every context explicitly:

```bash
kubectl --context kind-cicd get nodes
kubectl --context kind-dev get nodes
kubectl --context kind-staging get nodes
```

`make launch-clusters` is idempotent: it skips clusters that already exist.

### 3. Initialize the Pulumi stacks

Run each command once for a new local backend:

```bash
make stack-init STACK=cicd
make stack-init STACK=dev
make stack-init STACK=staging
```

If Pulumi reports that a stack already exists, select it instead:

```bash
make stack-select STACK=cicd
make stack-select STACK=dev
make stack-select STACK=staging
```

The Makefile passes `--stack` whenever `STACK` is supplied on the command line. Prefer `STACK=<name>` on every Pulumi operation instead of depending on the currently selected stack.

### 4. Check the Git repository configuration

Argo CD reads its root and child Applications from the repository configured at `CLUSTERS["cicd"]["paas"]["argocd"]["repository"]` in `paas_platform/clusters.py`.

For a fork or a different repository, update:

```python
"repository": {
    "url": "https://github.com/your-org/your-repository.git",
    "targetRevision": "master",
},
```

The target revision must contain the committed `gitops/` directory. Configuration that exists only in the local working tree is invisible to Argo CD.

For a private repository, configure its credential mappings and `cicd` Pulumi keys before the first `make up STACK=cicd`; follow [Private Git repository over HTTPS](gitops.md#private-git-repository-over-https) or [SSH](gitops.md#private-git-repository-over-ssh).

### 5. Configure and deploy Argo CD

Set the initial administrator password:

```bash
make set-argocd-admin-password
```

For automation, inject the password from the automation's secret store rather than writing a literal into the command:

```bash
env ARGOCD_ADMIN_PASSWORD="$PLATFORM_BOOTSTRAP_PASSWORD" \
  make set-argocd-admin-password
```

Preview and deploy the CI/CD stack:

```bash
make preview-diff STACK=cicd
make up STACK=cicd
```

Wait for Argo CD:

```bash
kubectl --context kind-cicd -n argocd rollout status deployment/argocd-server
kubectl --context kind-cicd -n argocd get pods
```

### 6. Configure workload secrets

The nginx example declares two required secret names. Each workload stack needs its own values:

```bash
SECRET_VALUE='dev-example-one' make set-secret STACK=dev SERVICE=nginx SECRET_KEY=DUMMY_SECRET
SECRET_VALUE='dev-example-two' make set-secret STACK=dev SERVICE=nginx SECRET_KEY=DUMMY_SECRET_2
SECRET_VALUE='staging-example-one' make set-secret STACK=staging SERVICE=nginx SECRET_KEY=DUMMY_SECRET
SECRET_VALUE='staging-example-two' make set-secret STACK=staging SERVICE=nginx SECRET_KEY=DUMMY_SECRET_2
```

These are disposable examples. See [Secrets and credentials](secrets.md) before using non-lab values.

### 7. Validate generated GitOps content

The repository already contains the generated Applications for its checked-in overlays. Verify them:

```bash
make check-gitops
```

If the check reports drift, regenerate both workload registries:

```bash
make generate-gitops STACK=dev
make generate-gitops STACK=staging
make check-gitops
```

Generated changes must be committed and pushed to the configured repository before Argo CD can see them.

### 8. Deploy workload stacks

```bash
make preview-diff STACK=dev
make up STACK=dev

make preview-diff STACK=staging
make up STACK=staging
```

The workload stack does not deploy container workloads directly while GitOps is enabled. It installs optional PaaS, creates secret prerequisites, registers the workload cluster in Argo CD, and creates the root `registry-<cluster>` Application.

### 9. Verify reconciliation

Inspect all Applications from the CI/CD cluster:

```bash
kubectl --context kind-cicd -n argocd get applications
```

Expected Applications for the checked-in overlays:

- `registry-dev`
- `api-dev`
- `nginx-dev`
- `registry-staging`
- `nginx-staging`

Inspect the workload resources:

```bash
kubectl --context kind-dev -n api get deployment,service,ingress
kubectl --context kind-dev -n nginx get deployment,service,networkpolicy
kubectl --context kind-staging -n nginx get deployment,service,networkpolicy
```

## Access the platform

### Argo CD UI

```bash
kubectl --context kind-cicd -n argocd port-forward service/argocd-server 8080:443
```

Open `https://127.0.0.1:8080`. Use username `admin` and the password supplied to `make set-argocd-admin-password`.

### API through Traefik

Traefik is enabled on `dev` by default:

```bash
kubectl --context kind-dev -n traefik port-forward service/traefik 8081:80
curl -H 'Host: api.localhost' http://127.0.0.1:8081/
```

### Service port-forward without ingress

```bash
kubectl --context kind-dev -n nginx port-forward service/nginx 8082:80
```

Then open `http://127.0.0.1:8082`.

## Existing local installation

When clusters and backend stacks already exist:

```bash
make install-dev
make login
make check-gitops
make preview-diff STACK=cicd
make preview-diff STACK=dev
make preview-diff STACK=staging
```

Apply only the stacks that own the change. A normal workload-only Git change does not require `make up`; it requires generation, commit, push, and Argo CD reconciliation. See [GitOps workflow](gitops.md).

## Completely rebuild the disposable lab

Use the canonical [full teardown runbook](operations.md#full-teardown), which covers both cases:

- clusters still exist and resources can be destroyed normally;
- clusters were deleted first and disposable state must be abandoned with `--force`.

That runbook begins by selecting and verifying the local backend, preserves the tracked stack configuration files, and explains the destructive consequences. After it completes, repeat [First installation](#first-installation).

## Next steps

- [Architecture](architecture.md)
- [GitOps workflow](gitops.md)
- [Operations](operations.md)
- [Troubleshooting](troubleshooting.md)
