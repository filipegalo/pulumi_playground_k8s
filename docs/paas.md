# PaaS components

Use this guide to operate platform-owned components under `paas/`. These components are installed directly by Pulumi and are separate from developer services under `services/`.

## Component lifecycle

PaaS discovery combines:

1. A base declaration at `paas/<component>/service.json`.
2. A per-cluster configuration at `CLUSTERS[<cluster>]["paas"][<component>]`.
3. An explicit deployment handler in `__main__.py`.

Setting `enabled: false` prevents the component from being loaded. Adding only a `service.json` does not implement a new component; code, dispatch, tests, and documentation are also required.

## Current inventory

| Component | Stack | Default state | Deployment engine |
| --- | --- | --- | --- |
| Argo CD | `cicd` | Enabled | Pulumi Helm Release |
| Traefik | `dev` | Enabled | Pulumi Helm Release |
| Traefik | `staging` | Disabled | Not deployed |

Neither component is a child Argo CD Application.

## Argo CD

### Configuration

Argo CD belongs to the CI/CD inventory:

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
                "targetRevision": "master",
            },
        },
    },
}
```

The base component uses the official `argo-cd` chart repository and release name `argocd`. The current inventory does not pin an Argo CD chart version; add a tested `helm.version` before reproducibility matters.

### Initial administrator password

```bash
make set-argocd-admin-password CICD_STACK=cicd
make preview-diff STACK=cicd
make up STACK=cicd
```

The target prompts without echoing the password, creates a bcrypt hash locally, stores the hash as a Pulumi secret, and stores the modification timestamp as plaintext configuration.

For automation, inject the password through a protected environment variable:

```bash
env ARGOCD_ADMIN_PASSWORD="$PLATFORM_BOOTSTRAP_PASSWORD" \
  make set-argocd-admin-password CICD_STACK=cicd
```

### Rotate the administrator password

Run the same command with a new password, then apply the CI/CD stack:

```bash
make set-argocd-admin-password CICD_STACK=cicd
make up STACK=cicd
```

The username remains `admin`.

### Access the UI

```bash
kubectl --context kind-cicd -n argocd port-forward service/argocd-server 8080:443
```

Open `https://127.0.0.1:8080`.

### Verify Argo CD

```bash
kubectl --context kind-cicd -n argocd get pods
kubectl --context kind-cicd -n argocd get applications
kubectl --context kind-cicd -n argocd get secret \
  -l argocd.argoproj.io/secret-type=cluster
```

### Repository access

Public repositories require only `url` and `targetRevision`. Private Git repositories add credential-key mappings; Pulumi creates an Argo CD repository Secret without writing credential values into inventory or generated manifests.

See [GitOps workflow](gitops.md#private-git-repository-over-https) and [Secrets and credentials](secrets.md#private-git-credentials).

### Disable or remove Argo CD safely

Argo CD has finalizers on root and child Applications. Destroy workload stacks before disabling or destroying the CI/CD stack so they can remove their root Applications and cluster registrations.

Before any destroy, select the local backend and confirm the stacks are the disposable lab:

```bash
make login
PULUMI_CONFIG_PASSPHRASE=local-dev-only pulumi stack ls
```

Recommended order:

1. Remove or migrate GitOps-managed workloads.
2. Destroy `staging` and `dev` workload stacks.
3. Confirm root and child Applications are gone.
4. Disable Argo CD or destroy `cicd`.

```bash
make destroy STACK=staging
make destroy STACK=dev
kubectl --context kind-cicd -n argocd get applications
make destroy STACK=cicd
```

Removing finalizers manually can orphan resources and is a destructive last resort.

## Traefik ingress controller

### Why Traefik

Traefik is a maintained ingress controller. The project intentionally does not use ingress-nginx, which Kubernetes retired in March 2026.

### Current dev configuration

```python
"paas": {
    "ingress": {
        "enabled": True,
        "namespace": "traefik",
        "helm": {
            "values": {
                "providers": {
                    "kubernetesCRD": {"enabled": False},
                    "kubernetesGateway": {"enabled": False},
                    "kubernetesIngress": {
                        "enabled": True,
                        "ingressClass": "traefik",
                        "publishedService": {"enabled": False},
                        "ingressEndpoint": {"ip": "127.0.0.1"},
                    },
                },
                "gateway": {"enabled": False},
                "ingressClass": {
                    "enabled": True,
                    "isDefaultClass": False,
                    "name": "traefik",
                },
                "service": {
                    "spec": {
                        "type": "NodePort",
                    },
                },
            },
        },
    },
}
```

The base component pins Traefik chart `40.2.0`, release `traefik`, from `https://traefik.github.io/charts`.

The configuration intentionally:

- enables the Kubernetes Ingress provider;
- creates a non-default `traefik` IngressClass;
- disables the CRD and Gateway providers;
- exposes the controller as NodePort inside Kind;
- writes `127.0.0.1` into Ingress status so Argo CD can evaluate Ingress health.

The status IP is not traffic exposure. Docker Desktop does not automatically map the Kind NodePort to the host.

### Enable Traefik

Set `enabled: true` and include the complete Kind-specific Helm values. Staging currently contains only the disabled flag; simply changing that flag to true would use chart defaults rather than the tested dev configuration.

After copying or centralizing the full configuration:

```bash
make preview-diff STACK=staging
make up STACK=staging
```

Applications that should use this controller must explicitly set:

```json
{
  "ingress": {
    "enabled": true,
    "className": "traefik"
  }
}
```

Regenerate and publish those service changes through GitOps.

### Verify Traefik

```bash
kubectl --context kind-dev -n traefik get pods,service
kubectl --context kind-dev get ingressclass traefik
kubectl --context kind-dev -n api get ingress api
```

The API Ingress should show class `traefik` and status address `127.0.0.1` after reconciliation.

### Access an application

```bash
kubectl --context kind-dev -n traefik port-forward service/traefik 8080:80
curl -H 'Host: api.localhost' http://127.0.0.1:8080/
```

### Disable Traefik safely

Disabling the Helm release while application Ingresses remain leaves those Ingresses without a controller and may leave Argo Applications `Progressing`.

Recommended sequence:

1. Disable or remove application Ingress declarations for that cluster.
2. Regenerate the registry.
3. Commit and push the service and generated changes.
4. Wait until Argo CD prunes the Ingresses.
5. Set `paas.ingress.enabled` to false.
6. Preview and apply the workload stack.

```bash
make generate-gitops STACK=dev
make check-gitops
# Commit and push the generated GitOps changes before continuing.

kubectl --context kind-dev get ingress --all-namespaces
make preview-diff STACK=dev
make up STACK=dev
```

## Add another PaaS component

A new component requires:

1. `paas/<name>/service.json`.
2. An implementation that validates enablement and creates its resources.
3. A cluster inventory entry.
4. Dispatch from `__main__.py`.
5. Inclusion in Python compilation if it is a nested module.
6. Tests for enabled, disabled, and invalid configurations.
7. Operator documentation.

See [Contributing](contributing.md#add-a-paas-component).

## Related documentation

- [Architecture](architecture.md)
- [Operations](operations.md)
- [Secrets and credentials](secrets.md)
- [Troubleshooting](troubleshooting.md)
