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


def is_gitops_enabled(cluster_name: str) -> bool:
    cluster = CLUSTERS.get(cluster_name, {})
    return cluster.get("gitops", {}).get("enabled", False)


def destination_config(cluster_name: str) -> dict[str, Any]:
    config = CLUSTERS[cluster_name]["gitops"]
    destination = config.get("destination", {})
    required = ("name", "server", "clusterRoleName")
    missing = [key for key in required if not destination.get(key)]
    if missing:
        raise ValueError(
            f"Remote Argo CD destination for {cluster_name} is missing: "
            + ", ".join(missing)
        )
    return destination


def repository_config(cluster_name: str) -> dict[str, Any]:
    gitops = CLUSTERS[cluster_name]["gitops"]
    cicd_cluster_name = gitops.get("cicdCluster", "cicd")
    repository = CLUSTERS[cicd_cluster_name]["paas"]["argocd"]["repository"]
    return {
        **repository,
        "registryPath": gitops["registryPath"],
    }


def _admin_password_values(config: dict[str, Any]) -> dict[str, Any]:
    password_config = config.get("adminPassword")
    if not password_config:
        return {}

    pulumi_config = pulumi.Config(
        password_config.get("configNamespace", "argocd")
    )
    return {
        "configs": {
            "secret": {
                "argocdServerAdminPassword": pulumi_config.require_secret(
                    password_config.get(
                        "hashConfigKey", "ADMIN_PASSWORD_BCRYPT"
                    )
                ),
                "argocdServerAdminPasswordMtime": pulumi_config.require(
                    password_config.get(
                        "mtimeConfigKey", "ADMIN_PASSWORD_MTIME"
                    )
                ),
            }
        }
    }


def _argocd_helm_config(config: dict[str, Any]) -> dict[str, Any]:
    configured_helm = config.get("helm", {})
    values = dict(configured_helm.get("values", {}))
    admin_values = _admin_password_values(config)
    if admin_values:
        configured_configs = dict(values.get("configs", {}))
        configured_secret = dict(configured_configs.get("secret", {}))
        configured_configs = {
            **configured_configs,
            "secret": {
                **configured_secret,
                **admin_values["configs"]["secret"],
            },
        }
        values = {**values, "configs": configured_configs}

    return {
        "chart": "argo-cd",
        "repository": "https://argoproj.github.io/argo-helm/",
        "releaseName": "argocd",
        **configured_helm,
        "values": values,
    }


def deploy_argocd(cluster_name: str) -> dict[str, Any]:
    if cluster_name not in CLUSTERS:
        raise ValueError(f"Unknown cluster target: {cluster_name}")
    if not is_argocd_enabled(cluster_name):
        return {}

    management_cluster = CLUSTERS[cluster_name]
    config = management_cluster["paas"]["argocd"]
    namespace_name = config.get("namespace", "argocd")
    resource_names = config.get("resourceNames", {})
    provider = create_provider(
        "argocd",
        cluster_name,
        management_cluster["context"],
        resource_names,
    )
    namespace = create_namespace(
        "argocd",
        cluster_name,
        namespace_name,
        management_cluster["environment"],
        provider,
        resource_names,
    )
    repository_secret = _create_repository_secret(
        cluster_name,
        namespace.metadata["name"],
        provider,
        config["repository"],
    )
    release = create_helm_release(
        "argocd",
        cluster_name,
        namespace,
        provider,
        _argocd_helm_config(config),
        resource_names,
    )
    return {
        "cluster": cluster_name,
        "namespace": namespace.metadata["name"],
        "helmRelease": release.name,
        "repositorySecret": (
            repository_secret.metadata["name"] if repository_secret else None
        ),
    }


def deploy_argocd_workload(cluster_name: str) -> dict[str, Any]:
    if cluster_name not in CLUSTERS:
        raise ValueError(f"Unknown cluster target: {cluster_name}")
    if not is_gitops_enabled(cluster_name):
        return {}

    workload_cluster = CLUSTERS[cluster_name]
    config = workload_cluster["gitops"]
    cicd_cluster_name = config.get("cicdCluster", "cicd")
    if cicd_cluster_name not in CLUSTERS:
        raise ValueError(f"Unknown CI/CD cluster: {cicd_cluster_name}")
    if not is_argocd_enabled(cicd_cluster_name):
        raise ValueError(f"Argo CD is not enabled on CI/CD cluster: {cicd_cluster_name}")

    cicd_cluster = CLUSTERS[cicd_cluster_name]
    argocd_config = cicd_cluster["paas"]["argocd"]
    namespace_name = argocd_config.get("namespace", "argocd")
    provider = create_provider(
        "argocd",
        cicd_cluster_name,
        cicd_cluster["context"],
        config.get("resourceNames", {}),
    )
    destination = destination_config(cluster_name)
    cluster_secret = _register_workload_cluster(
        cluster_name,
        workload_cluster,
        destination,
        namespace_name,
        provider,
    )
    registry = _create_registry_application(
        cluster_name,
        cicd_cluster_name,
        namespace_name,
        provider,
        {
            **config,
            "repository": repository_config(cluster_name),
        },
        cluster_secret,
    )
    return {
        "cluster": cluster_name,
        "cicdCluster": cicd_cluster_name,
        "destination": destination,
        "registryApplication": registry.metadata["name"],
    }


def _register_workload_cluster(
    cluster_name: str,
    workload_cluster: dict[str, Any],
    destination: dict[str, Any],
    argocd_namespace: Any,
    management_provider: k8s.Provider,
) -> k8s.core.v1.Secret:
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
            "namespace": argocd_namespace,
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
            depends_on=[token_secret],
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
    namespace: Any,
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
            "namespace": namespace,
            "labels": {"argocd.argoproj.io/secret-type": "repository"},
        },
        string_data=string_data,
        type="Opaque",
        opts=pulumi.ResourceOptions(provider=provider),
    )


def _create_registry_application(
    cluster_name: str,
    management_cluster_name: str,
    namespace: Any,
    provider: k8s.Provider,
    config: dict[str, Any],
    cluster_secret: k8s.core.v1.Secret,
) -> k8s.apiextensions.CustomResource:
    repository = config["repository"]

    return k8s.apiextensions.CustomResource(
        f"registry-{cluster_name}-{management_cluster_name}-application",
        api_version="argoproj.io/v1alpha1",
        kind="Application",
        metadata={
            "name": config.get("registryApplicationName", f"registry-{cluster_name}"),
            "namespace": namespace,
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
                "namespace": namespace,
            },
            "syncPolicy": {
                "automated": {"prune": True, "selfHeal": True},
                "syncOptions": ["CreateNamespace=true"],
            },
        },
        opts=pulumi.ResourceOptions(provider=provider, depends_on=[cluster_secret]),
    )


__all__ = [
    "deploy_argocd",
    "deploy_argocd_workload",
    "destination_config",
    "is_argocd_enabled",
    "is_gitops_enabled",
    "repository_config",
]
