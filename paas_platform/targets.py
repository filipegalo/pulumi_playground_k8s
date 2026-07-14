from typing import Any

from .clusters import CLUSTERS


def default_namespace(service_name: str, _environment: str) -> str:
    return service_name


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
