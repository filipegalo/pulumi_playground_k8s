from typing import Any

from .clusters import CLUSTERS


def default_namespace(service_name: str, environment: str) -> str:
    return f"{service_name}-{environment}"


def target_config(service_name: str, target: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(target, str):
        target = {"name": target}

    cluster_name = target["name"]
    if cluster_name not in CLUSTERS:
        raise ValueError(f"Unknown cluster target: {cluster_name}")

    return {
        **CLUSTERS[cluster_name],
        **target,
    }
