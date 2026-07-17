from typing import Any

import pulumi
import pulumi_kubernetes as k8s

from paas_platform.clusters import CLUSTERS
from paas_platform.resources import create_helm_release, create_namespace, create_provider


def is_argocd_enabled(cluster_name: str) -> bool:
    cluster = CLUSTERS.get(cluster_name, {})
    return cluster.get("paas", {}).get("argocd", {}).get("enabled", False)


def deploy_argocd(cluster_name: str) -> dict[str, Any]:
    if cluster_name not in CLUSTERS:
        raise ValueError(f"Unknown cluster target: {cluster_name}")
    if not is_argocd_enabled(cluster_name):
        return {}

    cluster = CLUSTERS[cluster_name]
    config = cluster["paas"]["argocd"]
    namespace_name = config.get("namespace", "argocd")
    resource_names = config.get("resourceNames", {})
    provider = create_provider("argocd", cluster_name, cluster["context"], resource_names)
    namespace = create_namespace(
        "argocd",
        cluster_name,
        namespace_name,
        cluster["environment"],
        provider,
        resource_names,
    )
    repository_secret = _create_repository_secret(
        cluster_name, namespace, provider, config["repository"]
    )
    release = create_helm_release(
        "argocd",
        cluster_name,
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
    registry = _create_registry_application(
        cluster_name,
        namespace,
        provider,
        config["repository"],
        release,
        repository_secret,
    )
    return {
        "cluster": cluster_name,
        "namespace": namespace.metadata["name"],
        "helmRelease": release.name,
        "registryApplication": registry.metadata["name"],
    }


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
    namespace: k8s.core.v1.Namespace,
    provider: k8s.Provider,
    repository: dict[str, Any],
    release: k8s.helm.v3.Release,
    repository_secret: k8s.core.v1.Secret | None,
) -> k8s.apiextensions.CustomResource:
    dependencies = [release]
    if repository_secret is not None:
        dependencies.append(repository_secret)

    return k8s.apiextensions.CustomResource(
        f"registry-{cluster_name}-application",
        api_version="argoproj.io/v1alpha1",
        kind="Application",
        metadata={"name": "registry", "namespace": namespace.metadata["name"]},
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


__all__ = ["deploy_argocd", "is_argocd_enabled"]
