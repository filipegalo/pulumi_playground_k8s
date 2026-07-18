# Contributing

Use this guide when changing platform code, adding a configuration field, creating a PaaS component, or adding a cluster/environment.

## Development workflow

1. Write or update a test that demonstrates the required behavior.
2. Run it and confirm the new assertion fails for the expected reason.
3. Implement the smallest coherent change.
4. Regenerate derived GitOps content when inputs change.
5. Run compilation, coverage, GitOps drift, and pre-commit checks.
6. Preview every affected Pulumi stack.
7. Review the complete diff for credentials and unrelated files.
8. Commit with a conventional message.

```bash
make test
make coverage
make check-gitops
make compile
make pre-commit
make preview-diff STACK=dev
```

The coverage gate is 100% for `paas` and `paas_platform`. CI uses mocks; a live preview or Kind test remains a separate local verification.

## Code map

| File/directory | Responsibility |
| --- | --- |
| `__main__.py` | Stack entry point and PaaS/service dispatch |
| `paas/__init__.py` | Enabled PaaS discovery |
| `paas/argocd/` | Argo installation, repository credentials, cluster registration, root apps |
| `paas/ingress/` | Traefik installation |
| `paas/gitops.py` | Pulumi-owned workload Secret prerequisites |
| `paas_platform/clusters.py` | Static cluster, environment, PaaS, and GitOps inventory |
| `paas_platform/defaults.py` | Defaults, merge behavior, and allowed overlay fields |
| `paas_platform/service.py` | Direct-Pulumi service orchestration |
| `paas_platform/resources.py` | Kubernetes and Helm resource builders |
| `paas_platform/container.py` | Container environment and readiness probe shape |
| `paas_platform/targets.py` | Cluster resolution and namespace default |
| `services/__init__.py` | Service discovery by overlay presence |
| `scripts/generate_gitops.py` | Child Application generation and stale-file pruning |
| `gitops/charts/service/` | Argo-managed container workload chart |
| `tests/test_pulumi_mocks.py` | Mocked resource behavior, generation, and coverage |

## Add a service configuration field

A field used by both direct and GitOps modes must be implemented twice consistently.

Checklist:

1. Add a default, if appropriate, in `paas_platform/defaults.py`.
2. Add it to `TARGET_SERVICE_OVERRIDE_KEYS` if cluster overlays may override it.
3. Implement direct-Pulumi behavior in the relevant platform resource/container builder.
4. Add the value to `scripts/generate_gitops.py`.
5. Add or update the shared chart value and template under `gitops/charts/service/`.
6. Add tests for defaults, overrides, direct resources, generated values, and validation failures.
7. Regenerate checked-in child Applications.
8. Document the field in `docs/services.md` and any operational consequences.

Verify parity explicitly. A field implemented only in Pulumi will appear to work in direct mode but do nothing for current GitOps-enabled clusters.

## Add a container resource type

For a new optional resource such as a PodDisruptionBudget:

1. Define a configuration shape and safe default.
2. Add a Pulumi builder and include it in service outputs/dependencies.
3. Add a Helm chart template guarded by the same enablement rule.
4. Generate the resolved values.
5. Test both disabled and enabled paths.
6. Document lifecycle and ownership.

Do not place secrets in generated Helm values.

## Add a PaaS component

Adding `paas/<component>/service.json` alone is not enough because dispatch is explicit.

Checklist:

1. Add the base declaration:

   ```json
   {
     "name": "example",
     "type": "helm",
     "helm": {
       "chart": "example",
       "repository": "https://charts.example.com",
       "releaseName": "example",
       "version": "1.2.3"
     }
   }
   ```

2. Add `paas/<component>/__init__.py` with:
   - per-cluster enablement;
   - unknown-cluster validation;
   - disabled no-op behavior;
   - provider, namespace, and resource creation;
   - stable outputs.
3. Add the component to a cluster's `paas` inventory with `enabled` true or false.
4. Dispatch it from `__main__.py`.
5. Add nested modules to the Makefile compilation target.
6. Test base discovery, enabled deployment, disabled behavior, exact Helm inputs, and outputs.
7. Pin and validate external chart versions.
8. Document enablement, upgrade, verification, local access, and safe removal.

Decide deliberately whether the component must be bootstrap-Pulumi-owned or could become an Argo-managed PaaS Application. Avoid dual ownership.

## Add a workload cluster/environment

1. Create a cluster/context or make its endpoint available.
2. Add a `CLUSTERS` entry with a unique name, context, and environment.
3. Add environment defaults if it differs from dev/staging.
4. For GitOps, add:
   - `enabled: true`;
   - `cicdCluster`;
   - a unique destination name;
   - an in-cluster reachable API server;
   - a role name;
   - a unique registry path.
5. Add overlays for services intended for that environment.
6. Initialize/configure a same-named Pulumi stack.
7. Generate the registry and add generator/tests expectations.
8. Deploy the stack after `cicd`.
9. Verify cluster registration and child Applications.

The Makefile has explicit Kind shortcuts only for `dev`, `staging`, and `cicd`. Add a new target if a new local cluster should be first-class.

## Change Argo CD cluster access

The current registration creates a long-lived token and binds `argocd-manager` to the configured ClusterRole, currently `cluster-admin`.

Changes to authentication or RBAC should test:

- service account and binding shape;
- token readiness;
- CA preservation;
- Pulumi secret propagation;
- cluster Secret labels and fields;
- reachability from the management cluster;
- permissions required for all generated resource types.

Prefer least privilege for anything beyond the local lab.

## Change GitOps generation

Generated registry files are checked artifacts.

When modifying the generator:

```bash
make generate-gitops STACK=dev
make generate-gitops STACK=staging
make check-gitops
git diff -- gitops/clusters
```

The generator must remain deterministic and must remove stale generated files. Tests should cover both container and Helm Application sources and every new value.

## Helm template validation

Go-templated files are excluded from generic `check-yaml`. Compiling Python and comparing generated Applications does not render the chart.

For chart changes, add a Helm render/schema smoke test when Helm is available, and render representative values for enabled/disabled combinations. External chart upgrades should be pinned and previewed against a live disposable cluster.

## Tests and CI

### Local

```bash
make test
make coverage
make pre-commit
make validate STACK=dev
```

### CI

The workflow checks:

- GitOps generation freshness;
- Python compilation;
- 100% Pulumi mock coverage.

It is not a live cluster integration or end-to-end test. If a change depends on controller behavior, perform a Kind deployment and record the verification commands in the commit/PR description.

The local coverage hook's file filter and the CI path filter are separate. CI includes `paas/**`; always run `make coverage` locally for PaaS changes even if the local hook does not trigger it automatically.

## Security review before commit

Check:

- no plaintext credentials, tokens, keys, kubeconfigs, or real stack values;
- no secrets embedded in Helm values, Applications, ConfigMaps, or environment maps;
- no permissions broader than required;
- external versions are pinned where reproducibility/security matters;
- error messages do not print secret values;
- generated output contains only names/references, not values.

The local passphrase is public. Pulumi ciphertext in tracked stack files must be treated as decryptable lab data.

## Commit scope

Use conventional messages such as:

```text
feat: add optional PaaS component
fix: refresh workload registration
docs: reorganize platform runbooks
test: cover GitOps Helm generation
```

Stage explicit paths. Avoid `git add .` when local stack files or unrelated changes may be present.

## Related documentation

- [Architecture](architecture.md)
- [Service configuration](services.md)
- [GitOps workflow](gitops.md)
- [Operations](operations.md)
