from typing import Any

from paas_platform.defaults import service_config
from paas_platform.resources import (
    create_namespace,
    create_provider,
    create_secret,
    secret_config_names,
)
from paas_platform.targets import default_namespace, target_config


def deploy_gitops_prerequisites(services: list[dict[str, Any]]) -> dict[str, Any]:
    """Provision secret material that must not be committed to the GitOps repository."""
    prerequisites: dict[str, Any] = {}

    for service in services:
        base_config = service_config(service)
        for target in base_config.get("targetClusters", []):
            cluster = target_config(base_config["name"], target)
            resolved_service = service_config(
                service,
                cluster["environment"],
                cluster,
            )
            secrets = secret_config_names(resolved_service, cluster)
            if not secrets:
                continue

            service_name = resolved_service["name"]
            cluster_name = cluster["name"]
            resource_names = cluster.get("resourceNames", {})
            namespace_name = cluster.get(
                "namespace",
                default_namespace(service_name, cluster["environment"]),
            )
            provider = create_provider(
                f"{service_name}-gitops",
                cluster_name,
                cluster["context"],
                resource_names,
            )
            namespace = create_namespace(
                service_name,
                cluster_name,
                namespace_name,
                cluster["environment"],
                provider,
                resource_names,
            )
            secret = create_secret(
                service_name,
                cluster_name,
                namespace,
                {},
                provider,
                secrets,
                resource_names,
            )
            prerequisites[service_name] = {
                "cluster": cluster_name,
                "namespace": namespace.metadata["name"],
                "secret": secret.metadata["name"] if secret else None,
            }

    return prerequisites


__all__ = ["deploy_gitops_prerequisites"]
