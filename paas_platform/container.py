from typing import Any

import pulumi_kubernetes as k8s


def container_spec(
    service: dict[str, Any],
    cluster: dict[str, Any],
    config_map: k8s.core.v1.ConfigMap | None,
    secret: k8s.core.v1.Secret | None,
) -> dict[str, Any]:
    container_port = service["containerPort"]
    env = service.get("env", {})
    cluster_env = cluster.get("env", {})
    readiness_probe = readiness_probe_spec(service["readinessProbe"], container_port)
    env_from_refs = env_from(config_map, secret)

    return {
        "name": service["name"],
        "image": cluster.get("image", service["image"]),
        "ports": [{"containerPort": container_port}],
        "env": [
            {"name": key, "value": value}
            for key, value in {**env, **cluster_env}.items()
        ],
        **({"envFrom": env_from_refs} if env_from_refs else {}),
        **({"readinessProbe": readiness_probe} if readiness_probe else {}),
        "resources": service["resources"],
    }


def env_from(
    config_map: k8s.core.v1.ConfigMap | None,
    secret: k8s.core.v1.Secret | None,
) -> list[dict[str, Any]]:
    env_from_refs = []

    if config_map is not None:
        env_from_refs.append(
            {
                "configMapRef": {
                    "name": config_map.metadata["name"],
                },
            }
        )

    if secret is not None:
        env_from_refs.append(
            {
                "secretRef": {
                    "name": secret.metadata["name"],
                },
            }
        )

    return env_from_refs


def readiness_probe_spec(config: dict[str, Any], container_port: int) -> dict[str, Any] | None:
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
