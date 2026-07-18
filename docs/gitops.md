# GitOps workflow

Use this guide when adding, changing, promoting, removing, or diagnosing a service managed by Argo CD.

## The central rule

Argo CD reads committed Git content from the configured repository and target revision. It cannot see:

- an uncommitted `service.json` change;
- a local overlay;
- generated YAML that has not been committed;
- a local commit that has not been pushed.

For a GitOps-managed workload, `make up STACK=dev` does not publish application changes. The normal workload flow is:

```text
edit declaration → generate → validate → commit → push → Argo reconcile
```

Use `make up STACK=<cluster>` for Pulumi-owned changes such as PaaS, cluster registration, and workload Secrets.

Git examples in this guide use `master` because that is the checked-in `targetRevision`. If the inventory points to another branch/tag/commit, publish to the configured revision instead. A tag or commit target requires updating the configured revision to roll forward.

## How a service selects clusters

The shared declaration alone deploys nowhere:

```text
services/my_app/service.json
```

An overlay is the membership switch:

```text
services/my_app/dev.json      → deploy to dev
services/my_app/staging.json  → deploy to staging
```

In GitOps mode, remove the overlay to opt out. Do not use `"enabled": false`; the current generator selects services by overlay presence.

## Generate Applications

One cluster:

```bash
make generate-gitops STACK=dev
```

All GitOps-enabled clusters are checked by:

```bash
make check-gitops
```

The direct generator equivalents are:

```bash
uv run python scripts/generate_gitops.py --cluster dev
uv run python scripts/generate_gitops.py --all --check
```

The script adds the repository root to `sys.path`, so it can be invoked directly. The Make targets remain the preferred interface.

Generated output lives at:

```text
gitops/clusters/<cluster>/registry/<service>.yaml
```

Generation is deterministic and deletes stale generated files. Never put hand-maintained YAML in a generated registry directory.

## Add a service to one cluster

Create `services/payments/service.json`:

```json
{
  "name": "payments",
  "image": "ghcr.io/example/payments:1.0.0",
  "secrets": ["DATABASE_URL"]
}
```

Create `services/payments/dev.json`:

```json
{
  "env": {
    "APP_ENV": "dev"
  }
}
```

If the service declares Pulumi-backed secrets, create those prerequisites before publishing the Application:

```bash
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi config set \
  --stack dev --secret payments:DATABASE_URL
make up STACK=dev
```

Generate, inspect, and publish:

```bash
make generate-gitops STACK=dev
make check-gitops
make pre-commit
git diff -- services/payments gitops/clusters/dev/registry/payments.yaml
git add services/payments gitops/clusters/dev/registry/payments.yaml
git commit -m "feat: deploy payments to dev"
git push origin master
```

Publishing after the prerequisite exists prevents Argo CD from creating pods that reference a missing Secret.

## Deploy a service to several clusters

Add one overlay per destination:

```text
services/payments/dev.json
services/payments/staging.json
```

Then generate both registries:

```bash
make generate-gitops STACK=dev
make generate-gitops STACK=staging
make check-gitops
```

Configure any Pulumi-backed secret separately for each stack. Values are not shared between environments.

## Promote from dev to staging

Copy only the intended settings into `services/payments/staging.json`. Do not blindly copy environment-specific endpoints or credentials:

```json
{
  "replicas": 2,
  "env": {
    "APP_ENV": "staging"
  }
}
```

Create the staging prerequisite before publishing this secret-backed service:

```bash
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi config set \
  --stack staging --secret payments:DATABASE_URL
make preview-diff STACK=staging
make up STACK=staging
```

Publish the generated staging Application:

```bash
make generate-gitops STACK=staging
make check-gitops
git add services/payments/staging.json gitops/clusters/staging/registry/payments.yaml
git commit -m "feat: promote payments to staging"
git push origin master
```

## Change a service

Changes to `service.json` affect every cluster with an overlay. Regenerate every registry:

```bash
make generate-gitops STACK=dev
make generate-gitops STACK=staging
make check-gitops
```

An overlay change affects only its cluster, but running `make check-gitops` still verifies all generated output.

Typical Git-managed changes include:

- image or chart version;
- replicas;
- environment variables and non-secret ConfigMap data;
- service ports;
- readiness probes;
- resource requests and limits;
- ingress configuration;
- NetworkPolicy;
- Helm values.

Secret values are the exception: change the Pulumi configuration and run the workload stack instead of writing the value to Git.

## Remove a service from one cluster

Removing an overlay is destructive after pruning completes.

```bash
git rm services/payments/staging.json
make generate-gitops STACK=staging
make check-gitops
```

The generator removes `gitops/clusters/staging/registry/payments.yaml`. Commit and push both deletions:

```bash
git add gitops/clusters/staging/registry
git commit -m "feat: remove payments from staging"
git push origin master
```

The root Application prunes the child Application. Its finalizer then prunes the workload resources. If the workload has persistent data, back it up and verify the chart's deletion behavior first.

After Argo has removed the workload, reconcile Pulumi so it can remove service-specific Secret prerequisites that are no longer declared:

```bash
make preview-diff STACK=staging
make up STACK=staging
```

For a secret-backed service, this may also delete the prerequisite namespace. Waiting for Argo to prune the workload first avoids deleting a live application namespace underneath it.

## Remove a service entirely

Remove every overlay and the base declaration, regenerate all affected registries, and publish the result:

```bash
git rm services/payments/dev.json services/payments/staging.json
make generate-gitops STACK=dev
make generate-gitops STACK=staging
git rm services/payments/service.json
make check-gitops
git add gitops/clusters/dev/registry gitops/clusters/staging/registry
git commit -m "feat: remove payments service"
git push origin master
```

Adjust the paths to the overlays that actually exist.

After every affected child Application has been pruned, preview and apply each affected workload stack to clean up Pulumi-owned Secret prerequisites:

```bash
make preview-diff STACK=dev
make up STACK=dev
make preview-diff STACK=staging
make up STACK=staging
```

## Container and Helm child Applications

### Container services

Container services use the shared chart at `gitops/charts/service`. The generator embeds resolved values in the child Application.

### Helm services

For `"type": "helm"`, the child Application points directly at the external Helm repository:

```json
{
  "name": "metrics",
  "type": "helm",
  "helm": {
    "chart": "example-chart",
    "repository": "https://charts.example.com",
    "version": "1.2.3",
    "releaseName": "metrics",
    "values": {}
  }
}
```

Pin `version`; without one, the generator uses `*`.

GitOps Helm Applications currently carry only repository, chart, version, release name, and values. Pulumi-specific Helm release flags are not transferred. Private Helm repository options other than `repo` are rejected; configure private Helm repositories directly in Argo CD before using them.

## Root and child reconciliation

Inspect the roots and children:

```bash
kubectl --context kind-cicd -n argocd get applications
```

Inspect exact revisions:

```bash
kubectl --context kind-cicd -n argocd get application registry-dev \
  -o custom-columns='NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status,REVISION:.status.sync.revision,RECONCILED:.status.reconciledAt'

kubectl --context kind-cicd -n argocd get application api-dev \
  -o custom-columns='NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status,REVISION:.status.sync.revision,RECONCILED:.status.reconciledAt'
```

If a pushed commit has not been observed, request a hard refresh of the root:

```bash
kubectl --context kind-cicd -n argocd annotate application registry-dev \
  argocd.argoproj.io/refresh=hard --overwrite
```

Watch the root and child:

```bash
kubectl --context kind-cicd -n argocd get applications registry-dev api-dev --watch
```

### Status meanings

| Status | Meaning | First check |
| --- | --- | --- |
| `Synced` | Live desired resources match Git | Check health separately |
| `OutOfSync` | Git and live state differ | Application conditions and diff |
| `Healthy` | Argo's health checks pass | No action normally required |
| `Progressing` | A resource is waiting to become healthy | Deployment rollout, Job, or Ingress status |
| `Degraded` | A resource reports failure | Pods, events, probes, and controller logs |
| `Missing` | A desired resource is absent | Sync operation and destination access |

`Synced` and `Progressing` together is valid: manifests match Git, but one live resource has not met Argo's health criteria.

## Public Git repository

Configure the repository once under the CI/CD inventory:

```python
"repository": {
    "url": "https://github.com/example/platform.git",
    "targetRevision": "master",
},
```

No repository Secret is created when `credentials` is absent.

When changing the public URL or revision:

1. Regenerate every workload registry because container children embed the source.
2. Commit and push the complete GitOps tree to the new source/revision.
3. Preview and apply every workload stack so its `registry-<cluster>` root Application points at the new source.

```bash
make generate-gitops STACK=dev
make generate-gitops STACK=staging
make check-gitops
# Commit and push before updating the live roots.
make preview-diff STACK=dev
make up STACK=dev
make preview-diff STACK=staging
make up STACK=staging
```

## Private Git repository over HTTPS

Add credential key mappings to the inventory. These are Pulumi configuration key names, not credential values:

```python
"repository": {
    "url": "https://git.example.com/platform/repository.git",
    "targetRevision": "main",
    "credentials": {
        "secretName": "registry-repository",
        "configNamespace": "argocd",
        "usernameConfigKey": "GIT_USERNAME",
        "passwordConfigKey": "GIT_PASSWORD",
    },
},
```

If the URL or revision changed, regenerate first because container child Applications embed both values:

```bash
make generate-gitops STACK=dev
make generate-gitops STACK=staging
make check-gitops
```

Commit the inventory and generated Applications, then push them to the new repository and configured revision before switching the live root Applications. Ensure that repository contains the entire platform GitOps tree.

Set the values in the `cicd` stack. Omitting the value makes Pulumi prompt without putting it in shell history:

```bash
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi config set \
  --stack cicd --secret argocd:GIT_USERNAME

PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi config set \
  --stack cicd --secret argocd:GIT_PASSWORD

make up STACK=cicd
```

After a URL/revision change has been pushed, apply every workload stack so its root Application switches to the new source:

```bash
make preview-diff STACK=dev
make up STACK=dev
make preview-diff STACK=staging
make up STACK=staging
```

A credential-only rotation for the same URL and revision requires only the `cicd` update. Because the repository tracks `Pulumi.cicd.yaml` and uses a known local passphrase, these commands are suitable only for disposable credentials unless you first move runtime configuration to a protected secrets provider/file policy.

## Private Git repository over SSH

Use an SSH repository URL and map `sshPrivateKeyConfigKey`:

```python
"repository": {
    "url": "git@git.example.com:platform/repository.git",
    "targetRevision": "main",
    "credentials": {
        "secretName": "registry-repository",
        "configNamespace": "argocd",
        "sshPrivateKeyConfigKey": "GIT_SSH_KEY",
    },
},
```

If the SSH URL or revision changed, regenerate every workload registry, commit the inventory and generated files, and push them to that repository/revision before switching the live root Applications. A key-only rotation for the same source does not require regeneration.

Pulumi accepts a multiline value from standard input:

```bash
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi config set \
  --stack cicd --secret argocd:GIT_SSH_KEY < /path/to/id_ed25519

make up STACK=cicd
```

After an SSH URL/revision change has been pushed, run `make up STACK=dev` and `make up STACK=staging` so both root Applications switch source. A key-only rotation needs only `make up STACK=cicd`.

SSH host-key trust is an operational responsibility not automated by this repository. The tracked local stack configuration and known passphrase are appropriate only for disposable credentials.

## Add a workload cluster

The inventory is static; clusters are not auto-discovered.

1. Create a Kind cluster, for example `qa`:

   ```bash
   kind create cluster --name qa
   kubectl --context kind-qa get nodes
   ```

2. Add `qa` to `CLUSTERS` with context `kind-qa`, environment defaults, a `gitops` block, `cicdCluster: cicd`, an internal API address such as `https://qa-control-plane:6443`, and a unique registry path.
3. Add service overlays such as `services/nginx/qa.json`.
4. Initialize and configure the `qa` Pulumi stack.
5. Generate `gitops/clusters/qa/registry`.
6. Commit and push the inventory, overlays, and generated Applications.
7. Deploy `make up STACK=qa` to register it and create `registry-qa`.

Adding a new environment default or Makefile cluster shortcut is a separate platform-code change.

## Direct-Pulumi mode

When `gitops.enabled` is false or omitted for a cluster, services are deployed directly by Pulumi. In that mode, a target with `enabled: false` is skipped by `deploy_service`.

### Safe example: a new direct-only environment

Add an inventory entry without `gitops`:

```python
"sandbox": {
    "name": "sandbox",
    "context": "kind-sandbox",
    "environment": "dev",
},
```

Create the cluster and an overlay:

```bash
kind create cluster --name sandbox
kubectl --context kind-sandbox get nodes
```

```json
{
  "env": {
    "APP_ENV": "sandbox"
  }
}
```

Save that JSON as `services/nginx/sandbox.json`, initialize the stack, configure its declared secrets, and deploy:

```bash
make stack-init STACK=sandbox
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi config set \
  --stack sandbox --secret nginx:DUMMY_SECRET
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi config set \
  --stack sandbox --secret nginx:DUMMY_SECRET_2
make preview-diff STACK=sandbox
make up STACK=sandbox
kubectl --context kind-sandbox -n nginx get all
```

No child Application is generated. Pulumi owns the workload resources and their lifecycle.

### Migrate an existing GitOps environment to direct mode

The supported simple approach has downtime:

1. Remove each cluster overlay temporarily.
2. Regenerate, commit, and push so Argo prunes the child Applications and workloads.
3. Confirm the root has no remaining children.
4. Restore the overlays and set `gitops.enabled` false or remove the `gitops` block.
5. Commit the ownership change.
6. Preview the stack; it should create the workload resources directly and stop declaring registration/root resources.
7. Apply and verify.

### Migrate direct mode to GitOps

The simple approach also has downtime:

1. Remove the overlays while direct mode is still active.
2. Preview and apply so Pulumi deletes the directly managed workloads.
3. Restore the overlays and add the complete `gitops` configuration.
4. Generate, commit, and push the child Applications.
5. Preview and apply the workload stack to create registration, prerequisites, and the root Application.
6. Watch Argo recreate the workloads.

Do not let Pulumi and Argo manage the same names concurrently. A zero-downtime ownership handoff requires a deliberate import/state/finalizer design that this repository does not automate. See [Architecture](architecture.md#direct-pulumi-mode).

## Related documentation

- [Service configuration](services.md)
- [Operations](operations.md)
- [Secrets and credentials](secrets.md)
- [Troubleshooting](troubleshooting.md)
