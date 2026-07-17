import json
from pathlib import Path
from typing import Any

from paas_platform.clusters import CLUSTERS
from paas_platform.defaults import deep_merge

_PAAS_DIR = Path(__file__).parent


def _read_json(path: Path) -> dict[str, Any]:
    with path.open() as file:
        return json.load(file)


def load_paas_services(cluster_name: str) -> list[dict[str, Any]]:
    """Load platform-owned services enabled for one cluster."""
    if cluster_name not in CLUSTERS:
        raise ValueError(f"Unknown cluster target: {cluster_name}")

    cluster_services = CLUSTERS[cluster_name].get("paas", {})
    services: list[dict[str, Any]] = []

    for service_name, cluster_config in sorted(cluster_services.items()):
        if not cluster_config.get("enabled", False):
            continue

        service_path = _PAAS_DIR / service_name / "service.json"
        if not service_path.exists():
            raise ValueError(f"Unknown PaaS service: {service_name}")

        target_config = {
            key: value
            for key, value in cluster_config.items()
            if key != "enabled"
        }
        services.append(
            deep_merge(
                _read_json(service_path),
                {
                    "targetClusters": [
                        {
                            "name": cluster_name,
                            **target_config,
                        }
                    ],
                },
            )
        )

    return services


__all__ = ["load_paas_services"]
