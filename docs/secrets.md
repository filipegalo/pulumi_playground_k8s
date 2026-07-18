# Secrets and credentials

Use this guide for service runtime secrets, the Argo CD administrator password, and private Git repository credentials.

## Secret classes

| Secret class | Configuration stack | Runtime destination | Owner |
| --- | --- | --- | --- |
| Service runtime values | Workload stack such as `dev` | Kubernetes Secret in the service namespace | Pulumi |
| Argo CD administrator bcrypt hash | `cicd` | Argo CD chart Secret | Pulumi |
| Private Git credentials | `cicd` | Argo CD repository Secret | Pulumi |
| Workload registration token | Workload stack | Service-account token in workload cluster and cluster Secret in `kind-cicd` | Pulumi |

Secret values do not belong in service declarations, overlays, Helm values, generated GitOps files, environment maps, or ConfigMaps.

## Local-lab security boundary

The repository uses:

```text
PULUMI_CONFIG_PASSPHRASE=local-dev-only
```

This is convenient for a disposable lab, but it is a known passphrase. Anyone with the repository can decrypt Pulumi ciphertext written with it. Checked-in stack files must therefore contain only disposable example values.

Pulumi encryption here protects against accidental plaintext display; it does not provide repository confidentiality. For anything shared or production-like:

- do not use the checked-in passphrase;
- use an appropriate Pulumi secrets provider or external secret manager;
- do not commit environment-specific secret configuration files;
- enable Kubernetes Secret encryption at rest;
- restrict access to Pulumi state and cluster Secrets;
- rotate credentials after suspected exposure.

Kubernetes Secrets are base64-encoded by default, not automatically encrypted at rest.

## Service runtime secrets

### Declare secret names

For example, `services/orders/service.json` can declare:

```json
{
  "name": "orders",
  "image": "ghcr.io/example/orders:1.0.0",
  "secrets": [
    "DATABASE_URL",
    "API_TOKEN"
  ]
}
```

The Pulumi key format is:

```text
<service-name>:<secret-name>
```

For this example:

```text
orders:DATABASE_URL
orders:API_TOKEN
```

### Set a secret with the Makefile

```bash
SECRET_VALUE='local-database-url' \
  make set-secret STACK=dev SERVICE=orders SECRET_KEY=DATABASE_URL
```

The value may be visible to local process inspection while the command runs and is supplied in the shell environment. For an interactive prompt that avoids shell history and the environment variable:

```bash
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi config set \
  --stack dev --secret orders:DATABASE_URL
```

Repeat for every declared key and every target stack. Dev and staging values are independent.

### Create or update the Kubernetes Secret

```bash
make preview-diff STACK=dev
make up STACK=dev
```

On GitOps-enabled stacks, Pulumi creates the namespace and a Kubernetes Secret named after the service. The generated child Application sets `existingSecret` so the Argo-managed Deployment consumes it through `envFrom`.

### Rotate a service secret

1. Set the new Pulumi value.
2. Apply the workload stack.
3. Restart workloads that read the value as an environment variable.
4. Verify the application.
5. Revoke the old credential at its source.

```bash
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi config set \
  --stack dev --secret orders:DATABASE_URL

make up STACK=dev
kubectl --context kind-dev -n orders delete pod \
  -l app.kubernetes.io/name=orders
kubectl --context kind-dev -n orders wait \
  --for=condition=Ready pod -l app.kubernetes.io/name=orders --timeout=120s
```

Updating a Kubernetes Secret does not change environment variables inside already-running containers. Deleting the selected pods lets the Deployment recreate them with the new environment without adding persistent drift to the Argo-managed Deployment. This restart is required unless the application reads mounted/API data dynamically. The current platform uses `envFrom`.

The label-based delete removes all matching replicas at once and can cause a brief interruption. A production platform should provide a Git-managed checksum or controlled rolling-restart mechanism.

### Add a secret to an existing service

1. Add the secret name to `service.json` or the cluster overlay.
2. Set the Pulumi value for every affected stack.
3. Run `make up STACK=<cluster>` to create/update the Secret.
4. Regenerate, commit, and push the child Application so it references the Secret.

Create the Pulumi prerequisite before publishing a workload that requires it.

### Remove a secret

When other declared secrets remain:

1. Remove the name from the service declaration.
2. Regenerate, commit, and push the declaration/generated changes.
3. Remove the Pulumi configuration value.
4. Preview and apply the workload stack so the Kubernetes Secret loses that key.
5. Recreate the pods so the removed environment variable disappears.

Example:

```bash
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi config rm \
  --stack dev orders:DATABASE_URL
make preview-diff STACK=dev
make up STACK=dev
kubectl --context kind-dev -n orders delete pod \
  -l app.kubernetes.io/name=orders
kubectl --context kind-dev -n orders wait \
  --for=condition=Ready pod -l app.kubernetes.io/name=orders --timeout=120s
```

The generated Deployment still references the same `existingSecret` while other keys remain, so there may be no Argo rollout from the declaration change itself.

The label-based pod deletion can briefly interrupt the service; schedule it accordingly.

When removing the last declared secret on a GitOps-enabled stack, publish the GitOps change first and wait until the Deployment no longer references `existingSecret`. The current prerequisite implementation then stops declaring both the Secret and its Pulumi-owned namespace. The next `make up STACK=<cluster>` can delete that namespace and every workload resource inside it; Argo CD later recreates the namespace and application, causing disruption. Updating GitOps first prevents a missing-secret reference but does not prevent the namespace deletion.

For a disposable lab, remove the Pulumi key, schedule the disruption, apply the workload stack, and watch Argo recreate the application. For an environment that must preserve the namespace, do not apply that last-secret cleanup until you perform an ownership migration or change the platform implementation so namespace lifecycle is independent from secret prerequisites.

## Argo CD administrator password

### Set the initial password

```bash
make set-argocd-admin-password CICD_STACK=cicd
make up STACK=cicd
```

The Make target:

1. reads the password without echoing it;
2. computes a salted bcrypt hash locally;
3. stores `argocd:ADMIN_PASSWORD_BCRYPT` as an encrypted Pulumi secret;
4. stores `argocd:ADMIN_PASSWORD_MTIME` as plaintext configuration.

Argo CD needs the modification time to notice password changes. It is intentionally plaintext; trying to set it without `--plaintext` can make Pulumi reject it because the key name looks secret-like.

The plaintext password is not stored. The bcrypt hash can still be attacked offline if exposed and the password is weak, so use a strong disposable value and protect non-lab state.

### Non-interactive setup

Have the automation platform provide `PLATFORM_BOOTSTRAP_PASSWORD` from its secret store:

```bash
env ARGOCD_ADMIN_PASSWORD="$PLATFORM_BOOTSTRAP_PASSWORD" \
  make set-argocd-admin-password CICD_STACK=cicd
```

Do not replace the variable reference with a literal password in a recorded shell command. Environment injection is intended for a protected CI/automation runner; locally, prefer the interactive Make target.

The Make target unsets the plaintext variable before writing Pulumi configuration.

### Rotate the password

```bash
make set-argocd-admin-password CICD_STACK=cicd
make preview-diff STACK=cicd
make up STACK=cicd
```

Then sign in as `admin` with the new password.

## Private Git credentials

The inventory maps repository credential fields to Pulumi configuration keys:

The lab's `Pulumi.cicd.yaml` is tracked and its encryption passphrase is public. Use only disposable credentials with that setup. Before storing a real repository credential, move CI/CD runtime configuration to an untracked/protected file and a real Pulumi secrets provider.

```python
"credentials": {
    "secretName": "registry-repository",
    "configNamespace": "argocd",
    "usernameConfigKey": "GIT_USERNAME",
    "passwordConfigKey": "GIT_PASSWORD",
}
```

### HTTPS credentials

Set values interactively:

```bash
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi config set \
  --stack cicd --secret argocd:GIT_USERNAME

PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi config set \
  --stack cicd --secret argocd:GIT_PASSWORD

make up STACK=cicd
```

Use a scoped token rather than a reusable personal password when the Git provider supports it.

### SSH private key

Configure `sshPrivateKeyConfigKey: GIT_SSH_KEY`, then pipe the multiline key to Pulumi:

```bash
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi config set \
  --stack cicd --secret argocd:GIT_SSH_KEY < /path/to/id_ed25519

make up STACK=cicd
```

Do not paste a private key into a service file or generated Application. Host-key trust for a self-hosted SSH server is not automated by this repository.

### Rotate repository credentials

1. Create the replacement token/key in the Git provider.
2. Update the Pulumi value.
3. Apply `cicd`.
4. Confirm Argo CD can refresh the repository.
5. Revoke the previous credential.

```bash
kubectl --context kind-cicd -n argocd get secret \
  -l argocd.argoproj.io/secret-type=repository

kubectl --context kind-cicd -n argocd annotate application registry-dev \
  argocd.argoproj.io/refresh=hard --overwrite
```

## Workload cluster credentials

Each workload stack creates:

- an `argocd-manager` ServiceAccount in `kube-system`;
- a ClusterRoleBinding, currently to `cluster-admin`;
- a service-account token Secret;
- an Argo CD cluster Secret containing the token and CA data.

Inspect names, not data:

```bash
kubectl --context kind-cicd -n argocd get secret \
  -l argocd.argoproj.io/secret-type=cluster

kubectl --context kind-dev -n kube-system get serviceaccount argocd-manager
```

Recreating a workload cluster invalidates the old registration. After the documented destroy/recreate flow, run its workload stack again to create a new token and cluster Secret.

If the cluster was recreated outside the documented destroy flow, refresh its stack before applying so Pulumi discovers resources that disappeared with the old cluster:

```bash
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi refresh --stack dev
make preview-diff STACK=dev
make up STACK=dev
```

## Respond to an exposed secret

1. Revoke or rotate the credential at its source immediately.
2. Remove the exposed value from the current working tree and unpushed commits.
3. If it was pushed, assume it remains in Git history and caches.
4. Set the replacement in the correct Pulumi stack.
5. Apply the owning stack.
6. Restart consumers if necessary.
7. Review other secrets created or used by the same identity.

Rewriting Git history is not a substitute for revocation.

## Related documentation

- [Architecture](architecture.md)
- [GitOps workflow](gitops.md)
- [Operations](operations.md)
- [Troubleshooting](troubleshooting.md)
