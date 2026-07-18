# Troubleshooting

Use this guide by symptom. Commands use explicit Pulumi stacks and Kubernetes contexts so diagnostics do not accidentally target another environment.

## Generator fails with `ModuleNotFoundError: paas`

### Cause

Python was invoked without the repository root on its import path, usually with an older version of the generator or from the wrong checkout.

### Diagnose

```bash
pwd
uv run python scripts/generate_gitops.py --cluster dev
```

The current script inserts its repository root into `sys.path`, and the Makefile exports `PYTHONPATH=.`.

### Repair

Run from the repository root and prefer:

```bash
make generate-gitops STACK=dev
```

If it still fails, confirm the current branch contains `paas/__init__.py` and `scripts/generate_gitops.py`.

## Generated GitOps check fails

### Symptom

```text
GitOps registry is stale; run make generate-gitops
```

### Cause

A service declaration, overlay, default, cluster destination, or generator changed without regenerating child Applications.

### Repair

```bash
make generate-gitops STACK=dev
make generate-gitops STACK=staging
make check-gitops
git diff -- gitops/clusters
```

Commit generated changes together with their source changes.

## YAML hook rejects Helm templates

Helm templates contain Go-template expressions that are not valid standalone YAML. The pre-commit configuration intentionally excludes `gitops/charts/*/templates/` from generic `check-yaml` validation.

If the hook reports those files, verify `.pre-commit-config.yaml` still contains:

```yaml
exclude: ^gitops/charts/[^/]+/templates/
```

Do not make a template syntactically valid as plain YAML by breaking its Helm logic.

## Service is not deployed to a cluster

### Common cause: overlay is missing

List the service directory:

```bash
find services/my_app -maxdepth 1 -type f -print
```

`service.json` alone deploys nowhere. Dev requires `services/my_app/dev.json`; staging requires `services/my_app/staging.json`.

After adding the overlay:

```bash
make generate-gitops STACK=dev
make check-gitops
```

Commit and push the overlay and generated Application.

### `enabled: false` did not disable a GitOps service

The generator currently selects a service by overlay presence and does not honor `enabled: false`. Remove the cluster overlay, regenerate, commit, and push.

## Service remains deployed after overlay deletion

Deleting the overlay locally is only the first step.

### Diagnose

```bash
make check-gitops
git status --short
kubectl --context kind-cicd -n argocd get applications
```

### Repair

```bash
make generate-gitops STACK=dev
make check-gitops
git add services/my_app gitops/clusters/dev/registry
git commit -m "feat: remove my-app from dev"
git push origin master
```

Then refresh and watch the parent:

```bash
kubectl --context kind-cicd -n argocd annotate application registry-dev \
  argocd.argoproj.io/refresh=hard --overwrite
kubectl --context kind-cicd -n argocd get applications --watch
```

Automated pruning and the child finalizer remove the workload resources.

If the removed service declared Pulumi-backed secrets, wait for Argo pruning to finish and then reconcile the workload stack to remove the now-orphaned prerequisites:

```bash
make preview-diff STACK=dev
make up STACK=dev
```

That cleanup may delete the service namespace after the workload is gone; review the preview.

## Argo CD still reports an old Git revision

### Diagnose local and remote Git

The following command checks the repository's current `master` target. Substitute the configured branch when `targetRevision` differs.

```bash
git rev-parse HEAD
git ls-remote origin refs/heads/master
```

If the SHAs differ, push the intended commit to the configured target revision.

### Diagnose the root Application

```bash
kubectl --context kind-cicd -n argocd get application registry-dev \
  -o custom-columns='NAME:.metadata.name,REVISION:.status.sync.revision,RECONCILED:.status.reconciledAt'
```

### Request a hard refresh

```bash
kubectl --context kind-cicd -n argocd annotate application registry-dev \
  argocd.argoproj.io/refresh=hard --overwrite
```

Refresh the root rather than only the child when generated child Application values changed.

## Application is `Synced` but `Progressing`

`Synced` means desired and live manifests match. `Progressing` means at least one resource has not met Argo CD's health criteria.

### Identify the resource

```bash
kubectl --context kind-cicd -n argocd get application api-dev -o yaml
kubectl --context kind-dev -n api get all
kubectl --context kind-dev -n api get ingress api -o yaml
```

Common causes:

- Deployment rollout or readiness probe is incomplete.
- A Job has not completed.
- Ingress status has no address.
- The child Application still embeds old values because the parent registry is stale.

Inspect events:

```bash
kubectl --context kind-dev -n api get events --sort-by=.metadata.creationTimestamp
```

## Ingress has an empty address

### Diagnose

```bash
kubectl --context kind-dev -n api get ingress api \
  -o custom-columns='NAME:.metadata.name,CLASS:.spec.ingressClassName,ADDRESS:.status.loadBalancer.ingress[0].ip'

kubectl --context kind-dev get ingressclass
kubectl --context kind-dev -n traefik get pods,service
```

For the checked-in API, expected values are class `traefik` and address `127.0.0.1`.

### Common causes

- The live child Application still has an old `className`.
- Traefik is disabled or not ready.
- The application selected another IngressClass.
- The Kind-specific `ingressEndpoint.ip` values were not copied when enabling Traefik on another cluster.

Repair the declaration/inventory, apply Pulumi-owned Traefik changes, regenerate workload GitOps changes, and refresh the root Application.

## Traefik is running but local traffic fails

The controller Service is NodePort inside Kind, but Docker Desktop does not automatically expose that NodePort to the host. The Ingress status address is not a host mapping.

Use port forwarding and the configured Host header:

```bash
kubectl --context kind-dev -n traefik port-forward service/traefik 8080:80
curl -H 'Host: api.localhost' http://127.0.0.1:8080/
```

If that fails, inspect controller logs:

```bash
kubectl --context kind-dev -n traefik logs deployment/traefik --tail=200
```

## Argo CD cannot connect to a workload cluster

### Symptoms

- Cluster status is unknown/unavailable.
- Child Applications cannot compare or sync.
- Logs mention `https://dev-control-plane:6443` connection or TLS errors.

### Diagnose registration

```bash
kubectl --context kind-cicd -n argocd get secret \
  -l argocd.argoproj.io/secret-type=cluster

kubectl --context kind-dev -n kube-system get serviceaccount argocd-manager
kubectl --context kind-dev -n kube-system get secret argocd-manager-token
```

Confirm the workload API itself is healthy:

```bash
kubectl --context kind-dev get --raw=/readyz
```

Inspect controller errors:

```bash
kubectl --context kind-cicd -n argocd logs \
  statefulset/argocd-application-controller --tail=200
```

### Causes

- The workload cluster was recreated and the token/CA registration is stale.
- Clusters do not share the expected Kind container network.
- The destination uses a host-only `127.0.0.1:<port>` endpoint.
- DNS cannot resolve `<cluster>-control-plane`.
- The workload API certificate does not match the configured server.

### Repair after cluster recreation

```bash
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi refresh --stack dev
make preview-diff STACK=dev
make up STACK=dev
```

Refresh first because `pulumi up` does not automatically discover every resource deleted with an out-of-band cluster recreation. The update then recreates the service-account token and refreshes the Argo CD cluster Secret.

## Workload stack fails because Argo CD CRDs are missing

### Cause

`dev` or `staging` was deployed before the `cicd` stack installed Argo CD.

### Repair

```bash
make up STACK=cicd
kubectl --context kind-cicd -n argocd rollout status deployment/argocd-server
make up STACK=dev
make up STACK=staging
```

## Repository authentication fails

### Inspect repository Secrets

```bash
kubectl --context kind-cicd -n argocd get secret \
  -l argocd.argoproj.io/secret-type=repository
```

### Inspect repo-server logs

```bash
kubectl --context kind-cicd -n argocd logs deployment/argocd-repo-server --tail=200
```

Check:

- repository URL scheme matches HTTPS or SSH credentials;
- every mapped Pulumi key is set in `cicd`;
- the token can read the configured repository and revision;
- the SSH server's host key is trusted;
- `make up STACK=cicd` ran after credential changes.

## Private Helm repository options are rejected

### Symptom

```text
uses private Helm repository options; configure that repository in Argo CD instead
```

### Cause

The GitOps generator does not provision private Helm repository credentials. It accepts only a repository URL in the service declaration.

### Repair

Configure the private Helm repository in Argo CD using an operationally managed repository Secret, then keep only the repository URL/chart/version/values in the service declaration. Never put Helm repository credentials in `helm.values`.

## Required service secret is missing

### Symptom

Pulumi reports a missing configuration variable such as `nginx:DUMMY_SECRET`.

### Repair

```bash
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi config set \
  --stack dev --secret nginx:DUMMY_SECRET
make up STACK=dev
```

Repeat for every declared key. Dev and staging use separate stack values.

## Argo administrator configuration is missing

### Symptoms

```text
Missing required configuration variable 'argocd:ADMIN_PASSWORD_BCRYPT'
```

or:

```text
Missing required configuration variable 'argocd:ADMIN_PASSWORD_MTIME'
```

### Repair

```bash
make set-argocd-admin-password CICD_STACK=cicd
make up STACK=cicd
```

Do not set the mtime as a secret manually. The Make target correctly uses `--plaintext` for it.

## Pulumi says a value “looks like a secret”

Pulumi uses key-name heuristics. For the Argo password modification time, explicitly use plaintext:

```bash
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi config set \
  --stack cicd --plaintext argocd:ADMIN_PASSWORD_MTIME \
  '2026-07-18T00:00:00Z'
```

Normally, rerun `make set-argocd-admin-password` so the hash and mtime stay consistent.

## Pulumi passphrase or decryption failure

Use the Make targets, which set the local lab passphrase, or export it for raw commands:

```bash
export PULUMI_CONFIG_PASSPHRASE=local-dev-only
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi stack ls
```

If a stack file was encrypted with another passphrase/provider, the known lab passphrase cannot decrypt it. Restore the correct secrets provider or recreate disposable configuration values.

## No Pulumi stack is selected

Avoid relying on selection:

```bash
make preview-diff STACK=dev
make up STACK=dev
```

For a new backend stack:

```bash
make stack-init STACK=dev
```

For an existing one:

```bash
make stack-select STACK=dev
```

## Wrong Kubernetes context

### Diagnose

```bash
kubectl config current-context
kubectl config get-contexts
kind get clusters
```

### Repair

Use explicit contexts rather than changing the global default:

```bash
kubectl --context kind-dev get nodes
kubectl --context kind-cicd -n argocd get applications
```

Overriding `DEV_CLUSTER`, `STAGING_CLUSTER`, or `CICD_CLUSTER` in Make changes only the created Kind name; it does not rewrite the inventory contexts or internal API endpoints.

## Kubernetes resource already exists

### Cause

A live resource exists but is not tracked by the selected Pulumi stack or Argo Application. This can follow a partial update, state loss, manual creation, or ownership migration.

### Diagnose ownership before deleting anything

```bash
kubectl --context kind-dev -n api get deployment api -o yaml
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi stack --stack dev
kubectl --context kind-cicd -n argocd get application api-dev -o yaml
```

### Repair

For a real environment, import or reconcile the resource with the intended owner. For this disposable lab, prefer the complete teardown/rebuild procedure in [Operations](operations.md#full-teardown) over ad-hoc namespace deletion.

## Pulumi update is locked or interrupted

Confirm no update process is still running, then:

```bash
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi cancel --stack dev
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi refresh --stack dev
make preview-diff STACK=dev
```

Do not run a contextless `pulumi cancel`; it can target the wrong selected stack.

## Pulumi repeatedly previews the same diff

Controllers may add defaults, status, labels, or other live fields. First determine whether the diff is desired-state drift or controller-owned normalization:

```bash
make preview-diff STACK=dev
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi refresh --stack dev
make preview-diff STACK=dev
```

Fix the desired resource inputs when possible. Add ignore rules only for fields proven to be controller-owned; broad ignores can hide real drift.

## LoadBalancer waits forever on Kind

Plain Kind does not allocate cloud LoadBalancer addresses.

Use `ClusterIP`, NodePort plus an explicit host mapping, port-forwarding, MetalLB, or cloud-provider-kind. The checked-in application Services use `ClusterIP`; Traefik uses NodePort and port-forwarding for host access.

## NetworkPolicy blocks traffic

### Diagnose

```bash
kubectl --context kind-dev -n nginx get networkpolicy nginx -o yaml
kubectl --context kind-dev -n nginx get pods --show-labels
```

Enabling the default policy with no ingress peers denies all ingress. Restricted egress can also block DNS.

For Traefik access, allow the `traefik` namespace and application port. Review the exact selector semantics in [Service configuration](services.md#networkpolicy).

## Readiness probe fails

### Diagnose

```bash
kubectl --context kind-dev -n api describe pod -l app.kubernetes.io/name=api
kubectl --context kind-dev -n api logs deployment/api --tail=200
```

Confirm:

- the container listens on `containerPort`;
- the HTTP path returns success;
- the initial delay is long enough;
- NetworkPolicy is not blocking kubelet traffic in the environment.

Disable the HTTP readiness probe for workers that do not expose HTTP.

## Application deletion is stuck on a finalizer

The finalizer asks Argo CD to delete managed resources before removing the Application. A disconnected workload cluster can block that cleanup.

First restore connectivity and let Argo prune normally. Removing the finalizer manually abandons managed resources and should be a last resort only after accepting orphaned resources.

## Clusters were deleted before Pulumi destroy

Pulumi providers cannot delete resources from unavailable API servers. For this disposable lab, remove stale backend state while preserving tracked configuration:

```bash
make login
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi stack ls
```

Confirm the backend and stack are the intended disposable lab, then:

```bash
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi stack rm \
  dev --force --yes --preserve-config
```

Repeat for the other affected stacks. `--force` abandons state; do not use it as a normal cleanup method.

## Related documentation

- [Getting started](getting-started.md)
- [GitOps workflow](gitops.md)
- [Operations](operations.md)
- [PaaS components](paas.md)
