from typing import Any

import pulumi
import pulumi_kubernetes as k8s

from .clusters import CLUSTERS, PLATFORM_LABELS


SERVICE_DEFAULTS = {
    "port": 80,
    "replicas": 1,
    "service": {
        "enabled": True,
        "type": "ClusterIP",
    },
    "ingress": {
        "enabled": False,
        "host": None,
    },
    "resources": {
        "requests": {
            "cpu": "25m",
            "memory": "32Mi",
        },
        "limits": {
            "cpu": "100m",
            "memory": "128Mi",
        },
    },
    "readinessProbe": {
        "enabled": True,
        "path": "/",
        "initialDelaySeconds": 3,
        "periodSeconds": 5,
    },
    "networkPolicy": {
        "enabled": False,
        "ingress": {
            "fromServices": [],
            "fromSameNamespace": False,
            "fromNamespaces": [],
            "ports": [],
        },
        "egress": {
            "allowExternal": True,
            "toServices": [],
            "toNamespaces": [],
            "ports": [],
        },
    },
    "config": {},
    "secrets": [],
}


def deploy_service(service: dict[str, Any]) -> list[dict[str, Any]]:
    service_config = _service_config(service)
    outputs = []

    for target in service_config.get("targetClusters", []):
        target_config = _target_config(service_config["name"], target)
        if not target_config.get("enabled", True):
            continue

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

    provider = k8s.Provider(
        resource_names.get("provider", f"{service_name}-{cluster_name}-provider"),
        context=context,
    )

    namespace = k8s.core.v1.Namespace(
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

    config_map = _create_config_map(
        service_name,
        cluster_name,
        namespace,
        metadata_labels,
        provider,
        _merged_runtime_config(service, cluster, "config"),
        resource_names,
    )
    secret = _create_secret(
        service_name,
        cluster_name,
        namespace,
        metadata_labels,
        provider,
        _secret_config_names(service, cluster),
        resource_names,
    )

    deployment = k8s.apps.v1.Deployment(
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
                    "containers": [_container_spec(service, cluster, config_map, secret)],
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

    service_resource = None
    service_resource_config = service["service"]
    if service_resource_config["enabled"]:
        service_resource = _create_service(
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
        ingress_resource = _create_ingress(
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
        network_policy_resource = _create_network_policy(
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


def _create_config_map(
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


def _create_secret(
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


def _create_service(
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


def _create_ingress(
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


def _create_network_policy(
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
    spec = _network_policy_spec(service, network_policy_config, selector_labels)

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


def _network_policy_spec(
    service: dict[str, Any],
    network_policy_config: dict[str, Any],
    selector_labels: dict[str, str],
) -> dict[str, Any]:
    ingress_config = network_policy_config["ingress"]
    egress_config = network_policy_config["egress"]
    ingress_rules = _network_policy_ingress_rules(service, ingress_config)
    egress_rules = _network_policy_egress_rules(egress_config)
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


def _network_policy_ingress_rules(
    service: dict[str, Any],
    ingress_config: dict[str, Any],
) -> list[dict[str, Any]] | None:
    peers = _network_policy_ingress_peers(ingress_config)
    if not peers:
        return []

    rule: dict[str, Any] = {"from": peers}
    ports = _network_policy_ports(ingress_config.get("ports"), service.get("port", 80))
    if ports:
        rule["ports"] = ports

    return [rule]


def _network_policy_egress_rules(
    egress_config: dict[str, Any],
) -> list[dict[str, Any]] | None:
    if egress_config.get("allowExternal", True):
        return None

    peers = _network_policy_egress_peers(egress_config)
    if not peers:
        return []

    rule: dict[str, Any] = {"to": peers}
    ports = _network_policy_ports(egress_config.get("ports"))
    if ports:
        rule["ports"] = ports

    return [rule]


def _network_policy_ingress_peers(ingress_config: dict[str, Any]) -> list[dict[str, Any]]:
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


def _network_policy_egress_peers(egress_config: dict[str, Any]) -> list[dict[str, Any]]:
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


def _network_policy_ports(
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


def _container_spec(
    service: dict[str, Any],
    cluster: dict[str, Any],
    config_map: k8s.core.v1.ConfigMap | None,
    secret: k8s.core.v1.Secret | None,
) -> dict[str, Any]:
    container_port = service["containerPort"]
    env = service.get("env", {})
    cluster_env = cluster.get("env", {})
    readiness_probe = _readiness_probe(service["readinessProbe"], container_port)
    env_from = _env_from(config_map, secret)

    return {
        "name": service["name"],
        "image": cluster.get("image", service["image"]),
        "ports": [{"containerPort": container_port}],
        "env": [
            {"name": key, "value": value}
            for key, value in {**env, **cluster_env}.items()
        ],
        **({"envFrom": env_from} if env_from else {}),
        **({"readinessProbe": readiness_probe} if readiness_probe else {}),
        "resources": service["resources"],
    }


def _env_from(
    config_map: k8s.core.v1.ConfigMap | None,
    secret: k8s.core.v1.Secret | None,
) -> list[dict[str, Any]]:
    env_from = []

    if config_map is not None:
        env_from.append(
            {
                "configMapRef": {
                    "name": config_map.metadata["name"],
                },
            }
        )

    if secret is not None:
        env_from.append(
            {
                "secretRef": {
                    "name": secret.metadata["name"],
                },
            }
        )

    return env_from


def _merged_runtime_config(
    service: dict[str, Any],
    cluster: dict[str, Any],
    key: str,
) -> dict[str, str]:
    return {
        **service.get(key, {}),
        **cluster.get(key, {}),
    }


def _secret_config_names(service: dict[str, Any], cluster: dict[str, Any]) -> list[str]:
    return list(dict.fromkeys([*service.get("secrets", []), *cluster.get("secrets", [])]))


def _selector_labels(service_name: str) -> dict[str, str]:
    return {
        "app.kubernetes.io/name": service_name,
        "app.kubernetes.io/part-of": PLATFORM_LABELS["app.kubernetes.io/part-of"],
    }


def _metadata_labels(service_name: str, environment: str) -> dict[str, str]:
    return {
        **_selector_labels(service_name),
        **PLATFORM_LABELS,
        "paas.openai.com/environment": environment,
    }


def _default_namespace(service_name: str, environment: str) -> str:
    return f"{service_name}-{environment}"


def _target_config(service_name: str, target: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(target, str):
        target = {"name": target}

    cluster_name = target["name"]
    if cluster_name not in CLUSTERS:
        raise ValueError(f"Unknown cluster target: {cluster_name}")

    return {
        **CLUSTERS[cluster_name],
        **target,
    }


def _service_config(service: dict[str, Any]) -> dict[str, Any]:
    config = {
        **SERVICE_DEFAULTS,
        **service,
        "service": {
            **SERVICE_DEFAULTS["service"],
            **service.get("service", {}),
        },
        "ingress": {
            **SERVICE_DEFAULTS["ingress"],
            **service.get("ingress", {}),
        },
        "resources": {
            **SERVICE_DEFAULTS["resources"],
            **service.get("resources", {}),
        },
        "readinessProbe": {
            **SERVICE_DEFAULTS["readinessProbe"],
            **service.get("readinessProbe", {}),
        },
        "networkPolicy": {
            **SERVICE_DEFAULTS["networkPolicy"],
            **service.get("networkPolicy", {}),
            "ingress": {
                **SERVICE_DEFAULTS["networkPolicy"]["ingress"],
                **service.get("networkPolicy", {}).get("ingress", {}),
            },
            "egress": {
                **SERVICE_DEFAULTS["networkPolicy"]["egress"],
                **service.get("networkPolicy", {}).get("egress", {}),
            },
        },
    }

    config["containerPort"] = config.get("containerPort", config["port"])
    return config


def _readiness_probe(config: dict[str, Any], container_port: int) -> dict[str, Any] | None:
    if not config["enabled"]:
        return None

    return {
        "httpGet": {
            "path": config["path"],
            "port": container_port,
        },
        "initialDelaySeconds": config["initialDelaySeconds"],
        "periodSeconds": config["periodSeconds"],
    }
