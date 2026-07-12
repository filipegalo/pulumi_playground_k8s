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


def service_config(service: dict[str, Any]) -> dict[str, Any]:
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
