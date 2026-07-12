from copy import deepcopy
from typing import Any


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

ENVIRONMENT_DEFAULTS = {
    "dev": {
        "replicas": 1,
        "service": {
            "type": "ClusterIP",
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
    },
    "staging": {
        "replicas": 2,
        "service": {
            "type": "LoadBalancer",
        },
        "resources": {
            "requests": {
                "cpu": "50m",
                "memory": "64Mi",
            },
            "limits": {
                "cpu": "250m",
                "memory": "256Mi",
            },
        },
    },
}

TARGET_SERVICE_OVERRIDE_KEYS = frozenset(
    [
        "config",
        "containerPort",
        "env",
        "image",
        "ingress",
        "networkPolicy",
        "port",
        "readinessProbe",
        "replicas",
        "resources",
        "secrets",
        "service",
    ]
)


def service_config(
    service: dict[str, Any],
    environment: str | None = None,
    target: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = deep_merge(
        SERVICE_DEFAULTS,
        ENVIRONMENT_DEFAULTS.get(environment, {}),
        service,
        target_service_overrides(target),
    )

    config["containerPort"] = config.get("containerPort", config["port"])
    return config


def target_service_overrides(target: dict[str, Any] | None) -> dict[str, Any]:
    if target is None:
        return {}

    return {
        key: value
        for key, value in target.items()
        if key in TARGET_SERVICE_OVERRIDE_KEYS
    }


def deep_merge(*configs: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}

    for config in configs:
        for key, value in config.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = deep_merge(merged[key], value)
                continue

            merged[key] = deepcopy(value)

    return merged
