# Architecture

Use this guide to understand why the platform has separate stacks and clusters, which system owns each resource, and how Argo CD reaches workload clusters.

## Design goals

The repository models five boundaries:

1. CI/CD management is independent from application environments.
2. PaaS components are separate from developer services.
3. Pulumi owns bootstrap infrastructure and secret material.
4. Argo CD owns Git-declared workload resources.
5. A service opts into a cluster by adding that cluster's overlay file.

## Cluster and stack matrix

| Stack | Kubernetes context | Environment | Pulumi-owned PaaS | GitOps responsibility |
| --- | --- | --- | --- | --- |
| `cicd` | `kind-cicd` | `platform` | Argo CD | Hosts every root and child Application |
| `dev` | `kind-dev` | `dev` | Traefik by default | Registers `dev` and creates `registry-dev` |
| `staging` | `kind-staging` | `staging` | Traefik disabled by default | Registers `staging` and creates `registry-staging` |

A Pulumi stack is an ownership and state boundary. It is not the same thing as the currently selected `kubectl` context. The `dev` stack deliberately creates resources in both `kind-dev` and `kind-cicd` by using explicit Pulumi Kubernetes providers.

## End-to-end flow

```text
services/api/service.json
        +
services/api/dev.json
        │
        ▼
scripts/generate_gitops.py
        │
        ▼
gitops/clusters/dev/registry/api.yaml
        │ commit + push
        ▼
registry-dev Application (kind-cicd)
        │
        ▼
api-dev Application (kind-cicd)
        │ destination: registered cluster "dev"
        ▼
Deployment / Service / ConfigMap / Ingress (kind-dev)
```

The generated files are derived artifacts. Change the source declaration or overlay and regenerate; do not edit a generated child Application manually.

## Resource ownership

### CI/CD stack owns

- The `argocd` namespace in `kind-cicd`.
- The Argo CD Helm release.
- The configured Argo CD administrator bcrypt hash and modification time.
- The optional Argo CD repository Secret for private Git access.

### Each workload stack owns

In its workload cluster:

- Optional PaaS components, currently Traefik.
- The `argocd-manager` ServiceAccount.
- Its ClusterRoleBinding and service-account token.
- Namespaces and Kubernetes Secrets required by GitOps workloads.

In the CI/CD cluster:

- The Argo CD cluster-registration Secret.
- Its `registry-<cluster>` root Application.

### Argo CD owns

- Generated child Applications such as `api-dev` and `nginx-staging`.
- Container workload Deployments, Services, ConfigMaps, Ingresses, and NetworkPolicies.
- Resources rendered from developer Helm charts by child Applications.
- Automated synchronization, self-healing, and pruning of those resources.

Pulumi does not deploy the workload resources while `gitops.enabled` is true. It only creates prerequisite Secrets and the bootstrap resources that allow Argo CD to do so.

## Platform-owned and developer-owned configuration

| Platform-owned | Developer-owned |
| --- | --- |
| `paas_platform/clusters.py` | `services/<name>/service.json` |
| `paas/` PaaS implementations | `services/<name>/<cluster>.json` |
| Shared service defaults | Image, chart, ports, probes, and resources |
| Cluster registration and RBAC | Runtime environment and ConfigMap values |
| GitOps generator and chart | Names of required runtime secrets |
| Pulumi test infrastructure | Cluster membership through overlay presence |

## App-of-apps organization

Root Applications coexist in the `argocd` namespace, so their names are cluster-specific:

| Root Application | Git directory | Child examples | Destination |
| --- | --- | --- | --- |
| `registry-dev` | `gitops/clusters/dev/registry` | `api-dev`, `nginx-dev` | Registered cluster `dev` |
| `registry-staging` | `gitops/clusters/staging/registry` | `nginx-staging` | Registered cluster `staging` |

The root Application deploys child Application custom resources into `kind-cicd`. Each child Application then deploys its workload to the registered destination cluster.

All root and child Applications use:

- automated sync;
- pruning;
- self-healing;
- `CreateNamespace=true`;
- a finalizer so removing an Application prunes its managed resources.

## How the CI/CD cluster reaches workload clusters

A Kind kubeconfig normally exposes an API server to the host as `https://127.0.0.1:<random-port>`. Inside an Argo CD pod, `127.0.0.1` refers to that pod, not the host, so that address cannot register a workload cluster.

The inventory instead uses Kind control-plane container DNS:

```python
"server": "https://dev-control-plane:6443"
```

Kind clusters created by the Makefile share Kind's container network. From `kind-cicd`, the control-plane container names `dev-control-plane` and `staging-control-plane` are resolvable and reachable. Registration also copies the workload cluster's CA certificate and a service-account bearer token into an Argo CD cluster Secret.

If clusters are created on different container networks, those internal names will not work. The networking and TLS requirements are:

- Argo CD pods can resolve the workload control-plane name.
- TCP port `6443` is reachable between the container networks.
- The server name is covered by the workload API server certificate.
- The registration Secret contains the matching CA data and a valid token.

See [Troubleshooting](troubleshooting.md#argo-cd-cannot-connect-to-a-workload-cluster) for diagnostics.

## PaaS components

PaaS inventory lives under each cluster's `paas` mapping. A component is loaded only when `enabled` is true.

### Argo CD

Argo CD belongs to the `cicd` stack and is installed directly as a Pulumi Helm release. It cannot manage its own initial installation because the controller and CRDs do not exist yet.

### Traefik

Traefik belongs to the workload stack where it is enabled and is installed directly as a Pulumi Helm release. Keeping ingress bootstrap outside the service registry means it can exist before workload Applications reconcile.

Traefik is not an Argo CD Application in the current design. A future PaaS app-of-apps layer could move post-bootstrap PaaS into Argo CD, but it would require an explicit ownership migration.

## Direct-Pulumi mode

If a cluster's `gitops.enabled` is false or its `gitops` block is absent, `__main__.py` calls the platform service deployer directly. Pulumi then owns the Deployment, Service, ConfigMap, Secret, Ingress, NetworkPolicy, or Helm release.

Do not switch an existing environment between GitOps and direct mode without a migration plan. Otherwise both engines may believe they own the same object, or the old owner may prune resources created by the new owner.

A safe ownership handoff generally requires:

1. Stop automated reconciliation by the old owner.
2. Decide whether resources will be imported, recreated, or briefly unavailable.
3. Remove or detach the old owner's state without accidental pruning.
4. Apply the new owner and verify matching resource names.
5. Re-enable reconciliation.

## Defaults and merge order

Resolved service configuration follows:

```text
platform defaults < environment defaults < service.json < cluster overlay
```

Mappings deep-merge. Lists and scalar values replace the earlier value. The cluster overlay can override only the fields explicitly allowed by `TARGET_SERVICE_OVERRIDE_KEYS` in `paas_platform/defaults.py`.

## Security model and local-lab limitations

This is intentionally a local learning environment:

- The Pulumi passphrase is the known value `local-dev-only`.
- Checked-in encrypted values are not confidential from someone who has the repository.
- Argo CD workload access uses `cluster-admin`.
- Cluster registration uses a long-lived service-account token.
- Kubernetes Secret encryption at rest is not configured by this repository.
- Traefik publishes `127.0.0.1` as status for Argo health; this is not production traffic routing.
- No external load balancer, DNS controller, certificate manager, image-pull secret abstraction, or production secret manager is installed.

For a production-like design, use restricted RBAC, a real secrets provider, protected Git revisions, auditable credential rotation, encrypted Kubernetes storage, network controls, and an appropriate ingress/load-balancer implementation.

## Related documentation

- [Getting started](getting-started.md)
- [GitOps workflow](gitops.md)
- [PaaS components](paas.md)
- [Secrets and credentials](secrets.md)
