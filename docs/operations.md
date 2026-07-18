# Operations

Use this guide for day-to-day previews and deployments, cluster inspection, local access, rotations, PaaS changes, teardown, and validation.

## Operational rules

1. Always pass `STACK=<name>` to Pulumi Make targets.
2. Always pass `--context` to `kubectl` in a multi-cluster environment.
3. Deploy `cicd` before workload stacks.
4. Destroy workload stacks before `cicd`.
5. GitOps workload changes require commit and push; `make up` is not a Git publisher.
6. Preview every Pulumi-owned change before applying it.

The Makefile's `kube-all` and `port-forward` targets use the currently selected kubectl context. Prefer the explicit commands in this guide.

## Stack lifecycle

### Login and list stacks

```bash
make login
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi stack ls
```

### Initialize once

```bash
make stack-init STACK=cicd
make stack-init STACK=dev
make stack-init STACK=staging
```

### Preview

```bash
make preview-diff STACK=cicd
make preview-diff STACK=dev
make preview-diff STACK=staging
```

### Apply

```bash
make up STACK=cicd
make up STACK=dev
make up STACK=staging
```

Apply only the stack that owns the change. Supplying `STACK` avoids accidentally using the stack most recently selected by a secret-setting command.

### Inspect outputs

```bash
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi stack output --stack cicd
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi stack output --stack dev
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi stack output --stack staging
```

### Refresh after an out-of-band change

```bash
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi refresh --stack dev
make preview-diff STACK=dev
```

Review a refresh before accepting unexpected deletions or ownership changes.

## Which workflow applies?

| Change | Required workflow |
| --- | --- |
| Container image, replicas, env, config, Service, Ingress, probe, resources, NetworkPolicy | Generate, validate, commit, push, watch Argo |
| Add/remove service overlay | Generate, validate, commit, push, allow prune |
| Service secret value or declared secret prerequisite | Set Pulumi config and `make up STACK=<workload>`; also publish declaration changes when names changed |
| Enable/disable Traefik | Edit inventory, preview, `make up STACK=<workload>` |
| Argo chart/admin/repository credential | Edit/set CI/CD config, preview, `make up STACK=cicd` |
| Cluster API server/role registration | Edit inventory, preview, `make up STACK=<workload>` |
| Destination name, registry path, or Git URL/revision | Edit inventory, regenerate affected registries, commit/push the new paths/source, then `make up STACK=<workload>` to update registration/root Applications |
| Shared platform code | Tests, preview every affected stack, then apply deliberately |

## Change GitOps destination or source

Different inventory fields have different owners:

- `destination.server` or `destination.clusterRoleName`: preview and apply the workload stack; no child manifest changes are required while the destination name stays the same.
- `destination.name`: regenerate and push child Applications because they embed the name, then apply the workload stack to update cluster registration.
- `registryPath`: generate the new path, explicitly remove the old generated path from Git, commit/push, then apply the workload stack so the root watches the new directory.
- repository URL/revision: regenerate all child Applications, push the complete tree to the new source, configure CI/CD credentials if needed, then apply every workload stack so all roots switch source.

Example registry path migration:

```bash
# After changing dev.gitops.registryPath to gitops/clusters/dev/apps:
make generate-gitops STACK=dev
git rm -r gitops/clusters/dev/registry
make check-gitops
git add gitops/clusters/dev/apps paas_platform/clusters.py
git commit -m "refactor: move dev GitOps registry"
git push origin master
make preview-diff STACK=dev
make up STACK=dev
```

The example assumes the checked-in `targetRevision: master`. Publish to the configured revision when it differs.

## Release a workload change

Example image update:

This repository watches `master`. Replace the push destination when `targetRevision` is configured differently.

1. Change the image in `service.json` or a cluster overlay.
2. Generate every affected registry.
3. Run checks.
4. Commit and push.
5. Watch Argo CD.

```bash
make generate-gitops STACK=dev
make generate-gitops STACK=staging
make check-gitops
make pre-commit

git add services gitops/clusters
git commit -m "feat: update application image"
git push origin master

kubectl --context kind-cicd -n argocd get applications --watch
```

Use narrower `git add` paths in normal work so unrelated changes are not committed.

## Inspect the platform

### Cluster health

```bash
kubectl --context kind-cicd get nodes
kubectl --context kind-dev get nodes
kubectl --context kind-staging get nodes
```

### Argo CD

```bash
kubectl --context kind-cicd -n argocd get pods
kubectl --context kind-cicd -n argocd get applications
kubectl --context kind-cicd -n argocd describe application registry-dev
kubectl --context kind-cicd -n argocd describe application api-dev
```

### Workloads

```bash
kubectl --context kind-dev -n api get deployment,service,ingress,pods
kubectl --context kind-dev -n nginx get deployment,service,networkpolicy,pods
kubectl --context kind-staging -n nginx get deployment,service,networkpolicy,pods
```

### Events and logs

```bash
kubectl --context kind-dev -n api get events --sort-by=.metadata.creationTimestamp
kubectl --context kind-dev -n api logs deployment/api --tail=100
```

## Local access

### Argo CD UI

```bash
kubectl --context kind-cicd -n argocd port-forward service/argocd-server 8080:443
```

Open `https://127.0.0.1:8080`.

### Direct service port-forward

```bash
kubectl --context kind-dev -n nginx port-forward service/nginx 8081:80
```

Open `http://127.0.0.1:8081`.

### Through Traefik

```bash
kubectl --context kind-dev -n traefik port-forward service/traefik 8082:80
curl -H 'Host: api.localhost' http://127.0.0.1:8082/
```

## Force a Git refresh

Use when the configured remote branch contains a commit but the root Application still reports an older revision:

```bash
kubectl --context kind-cicd -n argocd annotate application registry-dev \
  argocd.argoproj.io/refresh=hard --overwrite

kubectl --context kind-cicd -n argocd get applications registry-dev api-dev --watch
```

This changes only the refresh annotation; automated sync performs the reconciliation.

## Rotate a service secret

```bash
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi config set \
  --stack dev --secret nginx:DUMMY_SECRET

make preview-diff STACK=dev
make up STACK=dev
kubectl --context kind-dev -n nginx delete pod \
  -l app.kubernetes.io/name=nginx
kubectl --context kind-dev -n nginx wait \
  --for=condition=Ready pod -l app.kubernetes.io/name=nginx --timeout=120s
```

The current platform exposes Kubernetes Secrets as environment variables, so running pods need a restart to read changed values.

The label-based delete removes all matching replicas at once and may briefly interrupt the service. The lab does not yet provide a Git-managed rolling-restart checksum.

## Rotate the Argo CD administrator

```bash
make set-argocd-admin-password CICD_STACK=cicd
make preview-diff STACK=cicd
make up STACK=cicd
```

## Enable or disable Traefik

Edit the cluster's `paas.ingress` configuration in `paas_platform/clusters.py`.

For staging, copy or centralize the complete Kind-specific values from dev before enabling it; changing only `enabled` would use chart defaults.

```bash
make preview-diff STACK=staging
make up STACK=staging
```

When disabling, remove application Ingresses first and wait for GitOps pruning. See [PaaS components](paas.md#disable-traefik-safely).

## Add or remove a target environment

### Add

1. Create the Kubernetes cluster/context.
2. Add a static `CLUSTERS` entry.
3. Configure its internal API destination and registry path.
4. Add service overlays.
5. Initialize/configure the Pulumi stack.
6. Generate and push its registry.
7. Deploy its workload stack.

See [GitOps workflow](gitops.md#add-a-workload-cluster).

### Remove

1. Remove service overlays and publish regenerated deletions.
2. Wait for Argo to prune child Applications and workloads.
3. Destroy the workload Pulumi stack while both clusters remain reachable.
4. Remove the inventory entry and generated registry in a reviewed change.
5. Delete the workload cluster.

Do not delete the cluster first; finalizers and Pulumi providers need to reach it during normal cleanup.

## Recreate one workload cluster

For a disposable cluster:

Select the local backend and verify the disposable stack before destroying anything:

```bash
make login
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi stack ls
```

1. Remove its GitOps workloads or destroy its workload stack while reachable.
2. Delete and recreate the Kind cluster.
3. Run the workload stack again.

Example for dev:

```bash
make destroy STACK=dev
kind delete cluster --name dev
make cluster-dev
kubectl --context kind-dev get nodes
make up STACK=dev
```

The update creates a new service-account token, replaces the Argo CD registration Secret, recreates secret prerequisites and PaaS, and restores `registry-dev`.

## Recreate the CI/CD cluster

Destroy workload stacks first because they own registration and root Application resources in `kind-cicd`:

First run `make login` and verify the disposable stack list as shown in [Full teardown](#full-teardown).

```bash
make destroy STACK=staging
make destroy STACK=dev
make destroy STACK=cicd
kind delete cluster --name cicd
make cluster-cicd
make up STACK=cicd
make up STACK=dev
make up STACK=staging
```

The final two commands restore workload registrations and root Applications.

## Full teardown

This runbook is destructive. First select the local backend and confirm that the listed stacks are the disposable lab stacks you intend to remove:

```bash
make login
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi stack ls
```

Stop if the backend, organization/project names, or stack list are not the expected local lab.

### Normal teardown while clusters exist

```bash
make destroy STACK=staging
make destroy STACK=dev
make destroy STACK=cicd

kind delete cluster --name staging
kind delete cluster --name dev
kind delete cluster --name cicd
```

If you also want to remove the backend stacks, preserve the tracked configuration files:

```bash
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi stack rm \
  staging --yes --preserve-config

PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi stack rm \
  dev --yes --preserve-config

PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi stack rm \
  cicd --yes --preserve-config
```

Do not use `make stack-rm` for this tracked-config reset; that target does not pass `--preserve-config`.

### Clusters were deleted first

For this disposable lab only, abandon stale resource state while preserving stack configuration:

```bash
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi stack rm \
  staging --force --yes --preserve-config

PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi stack rm \
  dev --force --yes --preserve-config

PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi stack rm \
  cicd --force --yes --preserve-config
```

`--force` abandons Pulumi's knowledge of resources without deleting them. Never use it for a real environment unless orphaning is explicitly intended.

## Interrupted Pulumi update

First confirm that no update is still running. Then cancel the specific stack, refresh, and preview:

```bash
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi cancel --stack dev
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi refresh --stack dev
make preview-diff STACK=dev
```

## Test and validation commands

```bash
make compile
make test
make coverage
make check-gitops
make pre-commit
make validate STACK=dev
```

`make validate STACK=dev` runs compilation, 100% mock-test coverage, and a live Pulumi preview. It needs local cluster access and valid stack configuration.

Install the local hooks once:

```bash
make pre-commit-install
```

## CI scope

`.github/workflows/logic-tests.yml` runs on relevant changes and performs:

- generated GitOps drift checking;
- Python compilation;
- Pulumi mock tests with 100% platform-logic coverage.

It does not currently perform:

- a live Kind deployment;
- Helm rendering against every external chart;
- end-to-end traffic tests;
- security or vulnerability scanning;
- container image building or scanning.

## Command reference

| Command | Purpose |
| --- | --- |
| `make setup` | Alias for runtime-only `make install` |
| `make install` | Install runtime dependencies with `uv sync --no-dev` |
| `make install-dev` | Install runtime and development dependencies |
| `make login` | Select the local Pulumi backend |
| `make launch-clusters` | Create `dev`, `staging`, and `cicd` Kind clusters if missing |
| `make cluster-dev` | Create only the dev cluster |
| `make cluster-staging` | Create only the staging cluster |
| `make cluster-cicd` | Create only the CI/CD cluster |
| `make stack-init STACK=dev` | Initialize one backend stack |
| `make stack-select STACK=dev` | Select a stack for raw commands |
| `make stack-rm STACK=dev` | Remove a backend stack, but does not preserve tracked config; use the full teardown command instead |
| `make preview STACK=dev` | Preview one stack |
| `make preview-diff STACK=dev` | Preview one stack with a detailed diff |
| `make up STACK=dev` | Apply one stack non-interactively |
| `make destroy STACK=dev` | Destroy one stack's resources |
| `make set-secret ...` | Store one service secret in a workload stack |
| `make set-argocd-admin-password` | Store the Argo administrator hash and mtime in `cicd` |
| `make compile` | Compile all Python entry points/modules |
| `make test` | Run Pulumi mock tests |
| `make coverage` | Run tests with terminal coverage and a 100% gate |
| `make coverage-html` | Run the coverage gate and write `htmlcov/` |
| `make generate-gitops STACK=dev` | Regenerate one workload registry |
| `make check-gitops` | Verify every generated registry |
| `make pre-commit-install` | Install the repository hook through `core.hooksPath` |
| `make pre-commit` | Run all repository hooks |
| `make validate STACK=dev` | Compile, run coverage, and run a live preview |
| `make kube-context` | Print the current kubectl context; does not accept a context parameter |
| `make kube-nodes` | List nodes in the current kubectl context |
| `make kube-all NAMESPACE=nginx` | List namespace resources in the current kubectl context |
| `make port-forward ...` | Forward a Service from the current kubectl context |
| `make clean` | Remove Python, test, coverage, uv, and generated cache directories |

The kube helpers are convenient only after deliberately selecting a context. In scripts and documentation, prefer `kubectl --context ...`.

## Related documentation

- [Getting started](getting-started.md)
- [GitOps workflow](gitops.md)
- [PaaS components](paas.md)
- [Troubleshooting](troubleshooting.md)
