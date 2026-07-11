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
                    "containers": [_container_spec(service, cluster)],
                },
            },
        },
        opts=pulumi.ResourceOptions(provider=provider),
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

    return {
        "cluster": cluster_name,
        "context": context,
        "environment": environment,
        "namespace": namespace.metadata["name"],
        "deployment": deployment.metadata["name"],
        "service": service_resource.metadata["name"] if service_resource else None,
        "ingress": ingress_resource.metadata["name"] if ingress_resource else None,
    }


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


def _container_spec(service: dict[str, Any], cluster: dict[str, Any]) -> dict[str, Any]:
    container_port = service["containerPort"]
    env = service.get("env", {})
    cluster_env = cluster.get("env", {})
    readiness_probe = _readiness_probe(service["readinessProbe"], container_port)

    return {
        "name": service["name"],
        "image": cluster.get("image", service["image"]),
        "ports": [{"containerPort": container_port}],
        "env": [
            {"name": key, "value": value}
            for key, value in {**env, **cluster_env}.items()
        ],
        **({"readinessProbe": readiness_probe} if readiness_probe else {}),
        "resources": service["resources"],
    }


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
