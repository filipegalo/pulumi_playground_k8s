import base64
import json
from typing import Any

import pulumi
import pulumi_kubernetes as k8s

from paas_platform.clusters import CLUSTERS
from paas_platform.resources import create_helm_release, create_namespace, create_provider


def is_argocd_enabled(cluster_name: str) -> bool:
    cluster = CLUSTERS.get(cluster_name, {})
    return cluster.get("paas", {}).get("argocd", {}).get("enabled", False)


def destination_config(cluster_name: str) -> dict[str, Any]:
    config = CLUSTERS[cluster_name]["paas"]["argocd"]
    destination = config.get("destination", {"server": "https://kubernetes.default.svc"})
    if destination.get("server") == "https://kubernetes.default.svc":
        return destination
    required = ("name", "server", "clusterRoleName")
    missing = [key for key in required if not destination.get(key)]
    if missing:
        raise ValueError(
            f"Remote Argo CD destination for {cluster_name} is missing: "
            + ", ".join(missing)
        )
    return destination


def deploy_argocd(cluster_name: str) -> dict[str, Any]:
    if cluster_name not in CLUSTERS:
        raise ValueError(f"Unknown cluster target: {cluster_name}")
    if not is_argocd_enabled(cluster_name):
        return {}

    workload_cluster = CLUSTERS[cluster_name]
    config = workload_cluster["paas"]["argocd"]
    management_cluster_name = config.get("managementCluster", cluster_name)
    if management_cluster_name not in CLUSTERS:
        raise ValueError(f"Unknown Argo CD management cluster: {management_cluster_name}")
    management_cluster = CLUSTERS[management_cluster_name]
    namespace_name = config.get("namespace", "argocd")
    resource_names = config.get("resourceNames", {})
    provider = create_provider(
        "argocd",
        management_cluster_name,
        management_cluster["context"],
        resource_names,
    )
    namespace = create_namespace(
        "argocd",
        management_cluster_name,
        namespace_name,
        management_cluster["environment"],
        provider,
        resource_names,
    )
    repository_secret = _create_repository_secret(
        cluster_name, namespace, provider, config["repository"]
    )
    release = create_helm_release(
        "argocd",
        management_cluster_name,
        namespace,
        provider,
        {
            "chart": "argo-cd",
            "repository": "https://argoproj.github.io/argo-helm/",
            "releaseName": "argocd",
            **config.get("helm", {}),
        },
        resource_names,
    )
    destination = destination_config(cluster_name)
    cluster_secret = _register_workload_cluster(
        cluster_name,
        workload_cluster,
        destination,
        namespace,
        provider,
        release,
    )
    registry = _create_registry_application(
        cluster_name,
        management_cluster_name,
        namespace,
        provider,
        config["repository"],
        release,
        repository_secret,
        cluster_secret,
    )
    return {
        "cluster": cluster_name,
        "managementCluster": management_cluster_name,
        "destination": destination,
        "namespace": namespace.metadata["name"],
        "helmRelease": release.name,
        "registryApplication": registry.metadata["name"],
    }


def _register_workload_cluster(
    cluster_name: str,
    workload_cluster: dict[str, Any],
    destination: dict[str, Any] | None,
    argocd_namespace: k8s.core.v1.Namespace,
    management_provider: k8s.Provider,
    release: k8s.helm.v3.Release,
) -> k8s.core.v1.Secret | None:
    if not destination or destination.get("server") == "https://kubernetes.default.svc":
        return None

    workload_provider = create_provider(
        "argocd-workload",
        cluster_name,
        workload_cluster["context"],
        {},
    )
    service_account = k8s.core.v1.ServiceAccount(
        f"argocd-{cluster_name}-manager-service-account",
        metadata={"name": "argocd-manager", "namespace": "kube-system"},
        opts=pulumi.ResourceOptions(provider=workload_provider),
    )
    binding = k8s.rbac.v1.ClusterRoleBinding(
        f"argocd-{cluster_name}-manager-binding",
        metadata={"name": "argocd-manager-role-binding"},
        role_ref={
            "apiGroup": "rbac.authorization.k8s.io",
            "kind": "ClusterRole",
            "name": destination["clusterRoleName"],
        },
        subjects=[
            {
                "kind": "ServiceAccount",
                "name": service_account.metadata["name"],
                "namespace": service_account.metadata["namespace"],
            }
        ],
        opts=pulumi.ResourceOptions(
            provider=workload_provider,
            depends_on=[service_account],
        ),
    )
    token_secret = k8s.core.v1.Secret(
        f"argocd-{cluster_name}-manager-token",
        metadata={
            "name": "argocd-manager-token",
            "namespace": "kube-system",
            "annotations": {
                "kubernetes.io/service-account.name": service_account.metadata["name"],
                "pulumi.com/waitFor": "jsonpath={.data.token}",
            },
        },
        type="kubernetes.io/service-account-token",
        opts=pulumi.ResourceOptions(
            provider=workload_provider,
            depends_on=[service_account, binding],
        ),
    )
    registration_config = pulumi.Output.secret(
        token_secret.data.apply(_registration_config)
    )
    return k8s.core.v1.Secret(
        f"argocd-{cluster_name}-cluster-secret",
        metadata={
            "name": f"cluster-{cluster_name}",
            "namespace": argocd_namespace.metadata["name"],
            "labels": {"argocd.argoproj.io/secret-type": "cluster"},
        },
        string_data={
            "name": destination["name"],
            "server": destination["server"],
            "config": registration_config,
        },
        type="Opaque",
        opts=pulumi.ResourceOptions(
            provider=management_provider,
            depends_on=[argocd_namespace, release, token_secret],
        ),
    )


def _registration_config(data: dict[str, str]) -> str:
    return json.dumps(
        {
            "bearerToken": base64.b64decode(data["token"]).decode(),
            "tlsClientConfig": {
                "insecure": False,
                "caData": data["ca.crt"],
            },
        }
    )


def _create_repository_secret(
    cluster_name: str,
    namespace: k8s.core.v1.Namespace,
    provider: k8s.Provider,
    repository: dict[str, Any],
) -> k8s.core.v1.Secret | None:
    credentials = repository.get("credentials")
    if not credentials:
        return None

    secret_config = pulumi.Config(credentials.get("configNamespace", "argocd"))
    string_data: dict[str, Any] = {"type": "git", "url": repository["url"]}
    for field, config_key_name in (
        ("username", "usernameConfigKey"),
        ("password", "passwordConfigKey"),
        ("sshPrivateKey", "sshPrivateKeyConfigKey"),
    ):
        if config_key_name in credentials:
            string_data[field] = secret_config.require_secret(
                credentials[config_key_name]
            )

    return k8s.core.v1.Secret(
        f"argocd-{cluster_name}-repository-secret",
        metadata={
            "name": credentials.get("secretName", "registry-repository"),
            "namespace": namespace.metadata["name"],
            "labels": {"argocd.argoproj.io/secret-type": "repository"},
        },
        string_data=string_data,
        type="Opaque",
        opts=pulumi.ResourceOptions(provider=provider, depends_on=[namespace]),
    )


def _create_registry_application(
    cluster_name: str,
    management_cluster_name: str,
    namespace: k8s.core.v1.Namespace,
    provider: k8s.Provider,
    repository: dict[str, Any],
    release: k8s.helm.v3.Release,
    repository_secret: k8s.core.v1.Secret | None,
    cluster_secret: k8s.core.v1.Secret | None,
) -> k8s.apiextensions.CustomResource:
    dependencies = [release]
    if repository_secret is not None:
        dependencies.append(repository_secret)
    if cluster_secret is not None:
        dependencies.append(cluster_secret)

    return k8s.apiextensions.CustomResource(
        f"registry-{cluster_name}-{management_cluster_name}-application",
        api_version="argoproj.io/v1alpha1",
        kind="Application",
        metadata={
            "name": "registry",
            "namespace": namespace.metadata["name"],
            "finalizers": ["resources-finalizer.argocd.argoproj.io"],
        },
        spec={
            "project": repository.get("project", "default"),
            "source": {
                "repoURL": repository["url"],
                "targetRevision": repository.get("targetRevision", "HEAD"),
                "path": repository["registryPath"],
            },
            "destination": {
                "server": "https://kubernetes.default.svc",
                "namespace": namespace.metadata["name"],
            },
            "syncPolicy": {
                "automated": {"prune": True, "selfHeal": True},
                "syncOptions": ["CreateNamespace=true"],
            },
        },
        opts=pulumi.ResourceOptions(provider=provider, depends_on=dependencies),
    )


__all__ = ["deploy_argocd", "destination_config", "is_argocd_enabled"]
