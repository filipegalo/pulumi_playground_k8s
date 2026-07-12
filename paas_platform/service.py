from typing import Any

from .container import (
    env_from as _env_from,
    readiness_probe_spec as _readiness_probe,
)
from .defaults import service_config as _service_config
from .labels import metadata_labels as _metadata_labels
from .labels import selector_labels as _selector_labels
from .resources import (
    create_config_map,
    create_deployment,
    create_ingress,
    create_namespace,
    create_network_policy,
    create_provider,
    create_secret,
    create_service,
    merged_runtime_config as _merged_runtime_config,
    network_policy_ports as _network_policy_ports,
    secret_config_names as _secret_config_names,
)
from .targets import default_namespace as _default_namespace
from .targets import target_config as _target_config


def deploy_service(service: dict[str, Any]) -> list[dict[str, Any]]:
    base_service_config = _service_config(service)
    outputs = []

    for target in base_service_config.get("targetClusters", []):
        target_config = _target_config(base_service_config["name"], target)
        if not target_config.get("enabled", True):
            continue

        service_config = _service_config(
            service,
            target_config["environment"],
            target_config,
        )
        outputs.append(_deploy_to_cluster(service_config, target_config))

    return outputs


def _deploy_to_cluster(service: dict[str, Any], cluster: dict[str, Any]) -> dict[str, Any]:
    service_name = service["name"]
    cluster_name = cluster["name"]
    context = cluster["context"]
    environment = cluster["environment"]
    namespace_name = cluster.get("namespace", _default_namespace(service_name, environment))
    resource_names = cluster.get("resourceNames", {})
    selector_labels = _selector_labels(service_name)
    metadata_labels = _metadata_labels(service_name, environment)

    provider = create_provider(service_name, cluster_name, context, resource_names)
    namespace = create_namespace(
        service_name,
        cluster_name,
        namespace_name,
        environment,
        provider,
        resource_names,
    )
    config_map = create_config_map(
        service_name,
        cluster_name,
        namespace,
        metadata_labels,
        provider,
        _merged_runtime_config(service, cluster, "config"),
        resource_names,
    )
    secret = create_secret(
        service_name,
        cluster_name,
        namespace,
        metadata_labels,
        provider,
        _secret_config_names(service, cluster),
        resource_names,
    )
    deployment = create_deployment(
        service_name,
        cluster_name,
        namespace,
        metadata_labels,
        selector_labels,
        provider,
        service,
        cluster,
        config_map,
        secret,
        resource_names,
    )

    service_resource = None
    service_resource_config = service["service"]
    if service_resource_config["enabled"]:
        service_resource = create_service(
            service_name,
            cluster_name,
            namespace,
            deployment,
            selector_labels,
            metadata_labels,
            provider,
            service,
            service_resource_config,
            resource_names,
        )

    ingress_resource = None
    ingress_config = service["ingress"]
    if ingress_config["enabled"]:
        if service_resource is None:
            raise ValueError(f"{service_name} enables ingress but disables service")
        ingress_resource = create_ingress(
            service_name,
            cluster_name,
            namespace,
            service_resource,
            provider,
            service,
            ingress_config,
            resource_names,
        )

    network_policy_resource = None
    network_policy_config = service["networkPolicy"]
    if network_policy_config["enabled"]:
        network_policy_resource = create_network_policy(
            service_name,
            cluster_name,
            namespace,
            deployment,
            selector_labels,
            metadata_labels,
            provider,
            service,
            network_policy_config,
            resource_names,
        )

    return {
        "cluster": cluster_name,
        "context": context,
        "environment": environment,
        "namespace": namespace.metadata["name"],
        "deployment": deployment.metadata["name"],
        "configMap": config_map.metadata["name"] if config_map else None,
        "secret": secret.metadata["name"] if secret else None,
        "service": service_resource.metadata["name"] if service_resource else None,
        "ingress": ingress_resource.metadata["name"] if ingress_resource else None,
        "networkPolicy": (
            network_policy_resource.metadata["name"] if network_policy_resource else None
        ),
    }
