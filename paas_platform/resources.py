from typing import Any

import pulumi
import pulumi_kubernetes as k8s

from .clusters import PLATFORM_LABELS
from .container import container_spec


def create_provider(
    service_name: str,
    cluster_name: str,
    context: str,
    resource_names: dict[str, str],
) -> k8s.Provider:
    return k8s.Provider(
        resource_names.get("provider", f"{service_name}-{cluster_name}-provider"),
        context=context,
    )


def create_namespace(
    service_name: str,
    cluster_name: str,
    namespace_name: str,
    environment: str,
    provider: k8s.Provider,
    resource_names: dict[str, str],
) -> k8s.core.v1.Namespace:
    return k8s.core.v1.Namespace(
        resource_names.get("namespace", f"{service_name}-{cluster_name}-namespace"),
        metadata={
            "name": namespace_name,
            "labels": {
                **PLATFORM_LABELS,
                "paas.openai.com/environment": environment,
            },
        },
        opts=pulumi.ResourceOptions(provider=provider),
    )


def create_config_map(
    service_name: str,
    cluster_name: str,
    namespace: k8s.core.v1.Namespace,
    metadata_labels: dict[str, str],
    provider: k8s.Provider,
    config: dict[str, str],
    resource_names: dict[str, str],
) -> k8s.core.v1.ConfigMap | None:
    if not config:
        return None

    return k8s.core.v1.ConfigMap(
        resource_names.get("configMap", f"{service_name}-{cluster_name}-config-map"),
        metadata={
            "name": service_name,
            "namespace": namespace.metadata["name"],
            "labels": metadata_labels,
        },
        data=config,
        opts=pulumi.ResourceOptions(provider=provider),
    )


def create_secret(
    service_name: str,
    cluster_name: str,
    namespace: k8s.core.v1.Namespace,
    metadata_labels: dict[str, str],
    provider: k8s.Provider,
    secrets: list[str],
    resource_names: dict[str, str],
) -> k8s.core.v1.Secret | None:
    if not secrets:
        return None

    service_config = pulumi.Config(service_name)
    return k8s.core.v1.Secret(
        resource_names.get("secret", f"{service_name}-{cluster_name}-secret"),
        metadata={
            "name": service_name,
            "namespace": namespace.metadata["name"],
            "labels": metadata_labels,
        },
        string_data={
            secret_name: service_config.require_secret(secret_name)
            for secret_name in secrets
        },
        type="Opaque",
        opts=pulumi.ResourceOptions(provider=provider),
    )


def create_deployment(
    service_name: str,
    cluster_name: str,
    namespace: k8s.core.v1.Namespace,
    metadata_labels: dict[str, str],
    selector_labels: dict[str, str],
    provider: k8s.Provider,
    service: dict[str, Any],
    cluster: dict[str, Any],
    config_map: k8s.core.v1.ConfigMap | None,
    secret: k8s.core.v1.Secret | None,
    resource_names: dict[str, str],
) -> k8s.apps.v1.Deployment:
    return k8s.apps.v1.Deployment(
        resource_names.get("deployment", f"{service_name}-{cluster_name}-deployment"),
        metadata={
            "name": service_name,
            "namespace": namespace.metadata["name"],
            "labels": metadata_labels,
        },
        spec={
            "replicas": cluster.get("replicas", service.get("replicas", 1)),
            "selector": {
                "matchLabels": selector_labels,
            },
            "template": {
                "metadata": {
                    "labels": metadata_labels,
                },
                "spec": {
                    "containers": [container_spec(service, cluster, config_map, secret)],
                },
            },
        },
        opts=pulumi.ResourceOptions(
            provider=provider,
            depends_on=[
                resource
                for resource in [config_map, secret]
                if resource is not None
            ],
        ),
    )


def create_service(
    service_name: str,
    cluster_name: str,
    namespace: k8s.core.v1.Namespace,
    deployment: k8s.apps.v1.Deployment,
    selector_labels: dict[str, str],
    metadata_labels: dict[str, str],
    provider: k8s.Provider,
    service: dict[str, Any],
    service_config: dict[str, Any],
    resource_names: dict[str, str],
) -> k8s.core.v1.Service:
    return k8s.core.v1.Service(
        resource_names.get("service", f"{service_name}-{cluster_name}-service"),
        metadata={
            "name": service_name,
            "namespace": namespace.metadata["name"],
            "labels": metadata_labels,
        },
        spec={
            "type": service_config.get("type", "ClusterIP"),
            "selector": selector_labels,
            "ports": service_config.get(
                "ports",
                [
                    {
                        "name": "http",
                        "port": service.get("port", 80),
                        "targetPort": service.get("containerPort", service.get("port", 80)),
                    },
                ],
            ),
        },
        opts=pulumi.ResourceOptions(provider=provider, depends_on=[deployment]),
    )


def create_ingress(
    service_name: str,
    cluster_name: str,
    namespace: k8s.core.v1.Namespace,
    service_resource: k8s.core.v1.Service,
    provider: k8s.Provider,
    service: dict[str, Any],
    ingress_config: dict[str, Any],
    resource_names: dict[str, str],
) -> k8s.networking.v1.Ingress:
    service_port = ingress_config.get("servicePort", service.get("port", 80))
    host = ingress_config.get("host") or f"{service_name}.{cluster_name}.localhost"

    return k8s.networking.v1.Ingress(
        resource_names.get("ingress", f"{service_name}-{cluster_name}-ingress"),
        metadata={
            "name": service_name,
            "namespace": namespace.metadata["name"],
            "annotations": ingress_config.get("annotations", {}),
        },
        spec={
            "ingressClassName": ingress_config.get("className"),
            "rules": [
                {
                    "host": host,
                    "http": {
                        "paths": [
                            {
                                "path": ingress_config.get("path", "/"),
                                "pathType": ingress_config.get("pathType", "Prefix"),
                                "backend": {
                                    "service": {
                                        "name": service_resource.metadata["name"],
                                        "port": {
                                            "number": service_port,
                                        },
                                    },
                                },
                            },
                        ],
                    },
                },
            ],
        },
        opts=pulumi.ResourceOptions(provider=provider, depends_on=[service_resource]),
    )


def create_network_policy(
    service_name: str,
    cluster_name: str,
    namespace: k8s.core.v1.Namespace,
    deployment: k8s.apps.v1.Deployment,
    selector_labels: dict[str, str],
    metadata_labels: dict[str, str],
    provider: k8s.Provider,
    service: dict[str, Any],
    network_policy_config: dict[str, Any],
    resource_names: dict[str, str],
) -> k8s.networking.v1.NetworkPolicy:
    spec = network_policy_spec(service, network_policy_config, selector_labels)

    return k8s.networking.v1.NetworkPolicy(
        resource_names.get("networkPolicy", f"{service_name}-{cluster_name}-network-policy"),
        metadata={
            "name": service_name,
            "namespace": namespace.metadata["name"],
            "labels": metadata_labels,
        },
        spec=spec,
        opts=pulumi.ResourceOptions(provider=provider, depends_on=[deployment]),
    )


def network_policy_spec(
    service: dict[str, Any],
    network_policy_config: dict[str, Any],
    selector_labels: dict[str, str],
) -> dict[str, Any]:
    ingress_config = network_policy_config["ingress"]
    egress_config = network_policy_config["egress"]
    ingress_rules = network_policy_ingress_rules(service, ingress_config)
    egress_rules = network_policy_egress_rules(egress_config)
    policy_types = []

    spec: dict[str, Any] = {
        "podSelector": {
            "matchLabels": selector_labels,
        },
    }

    if ingress_rules is not None:
        policy_types.append("Ingress")
        spec["ingress"] = ingress_rules

    if egress_rules is not None:
        policy_types.append("Egress")
        spec["egress"] = egress_rules

    if policy_types:
        spec["policyTypes"] = policy_types

    return spec


def network_policy_ingress_rules(
    service: dict[str, Any],
    ingress_config: dict[str, Any],
) -> list[dict[str, Any]] | None:
    peers = network_policy_ingress_peers(ingress_config)
    if not peers:
        return []

    rule: dict[str, Any] = {"from": peers}
    ports = network_policy_ports(ingress_config.get("ports"), service.get("port", 80))
    if ports:
        rule["ports"] = ports

    return [rule]


def network_policy_egress_rules(
    egress_config: dict[str, Any],
) -> list[dict[str, Any]] | None:
    if egress_config.get("allowExternal", True):
        return None

    peers = network_policy_egress_peers(egress_config)
    if not peers:
        return []

    rule: dict[str, Any] = {"to": peers}
    ports = network_policy_ports(egress_config.get("ports"))
    if ports:
        rule["ports"] = ports

    return [rule]


def network_policy_ingress_peers(ingress_config: dict[str, Any]) -> list[dict[str, Any]]:
    peers: list[dict[str, Any]] = []

    if ingress_config.get("fromSameNamespace"):
        peers.append({"podSelector": {}})

    for namespace_name in ingress_config.get("fromNamespaces", []):
        peers.append(
            {
                "namespaceSelector": {
                    "matchLabels": {
                        "kubernetes.io/metadata.name": namespace_name,
                    },
                },
            }
        )

    for source_service in ingress_config.get("fromServices", []):
        peers.append(
            {
                "podSelector": {
                    "matchLabels": {
                        "app.kubernetes.io/name": source_service,
                    },
                },
            }
        )

    return peers


def network_policy_egress_peers(egress_config: dict[str, Any]) -> list[dict[str, Any]]:
    peers: list[dict[str, Any]] = []

    for namespace_name in egress_config.get("toNamespaces", []):
        peers.append(
            {
                "namespaceSelector": {
                    "matchLabels": {
                        "kubernetes.io/metadata.name": namespace_name,
                    },
                },
            }
        )

    for target_service in egress_config.get("toServices", []):
        peers.append(
            {
                "podSelector": {
                    "matchLabels": {
                        "app.kubernetes.io/name": target_service,
                    },
                },
            }
        )

    return peers


def network_policy_ports(
    configured_ports: list[dict[str, Any]] | None,
    default_port: int | None = None,
) -> list[dict[str, Any]]:
    if configured_ports:
        return configured_ports

    if default_port is None:
        return []

    return [
        {
            "protocol": "TCP",
            "port": default_port,
        },
    ]


def merged_runtime_config(
    service: dict[str, Any],
    cluster: dict[str, Any],
    key: str,
) -> dict[str, str]:
    return {
        **service.get(key, {}),
        **cluster.get(key, {}),
    }


def secret_config_names(service: dict[str, Any], cluster: dict[str, Any]) -> list[str]:
    return list(dict.fromkeys([*service.get("secrets", []), *cluster.get("secrets", [])]))
