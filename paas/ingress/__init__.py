from typing import Any

from paas_platform.clusters import CLUSTERS
from paas_platform.resources import (
    create_helm_release,
    create_namespace,
    create_provider,
)


def is_ingress_enabled(cluster_name: str) -> bool:
    cluster = CLUSTERS.get(cluster_name, {})
    return cluster.get("paas", {}).get("ingress", {}).get("enabled", False)


def deploy_ingress_controller(cluster_name: str) -> dict[str, Any]:
    if cluster_name not in CLUSTERS:
        raise ValueError(f"Unknown cluster target: {cluster_name}")
    if not is_ingress_enabled(cluster_name):
        return {}

    cluster = CLUSTERS[cluster_name]
    config = cluster["paas"]["ingress"]
    namespace_name = config.get("namespace", "traefik")
    resource_names = config.get("resourceNames", {})
    provider = create_provider(
        "ingress",
        cluster_name,
        cluster["context"],
        resource_names,
    )
    namespace = create_namespace(
        "ingress",
        cluster_name,
        namespace_name,
        cluster["environment"],
        provider,
        resource_names,
    )
    release = create_helm_release(
        "ingress",
        cluster_name,
        namespace,
        provider,
        {
            "chart": "traefik",
            "repository": "https://traefik.github.io/charts",
            "releaseName": "traefik",
            "version": "40.2.0",
            **config.get("helm", {}),
        },
        resource_names,
    )
    return {
        "cluster": cluster_name,
        "namespace": namespace.metadata["name"],
        "helmRelease": release.name,
    }


__all__ = ["deploy_ingress_controller", "is_ingress_enabled"]
