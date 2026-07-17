CLUSTERS = {
    "dev": {
        "name": "dev",
        "context": "kind-dev",
        "environment": "dev",
        "paas": {
            "argocd": {
                "enabled": True,
                "namespace": "argocd",
            },
        },
    },
    "staging": {
        "name": "staging",
        "context": "kind-staging",
        "environment": "staging",
        "paas": {
            "argocd": {
                "enabled": False,
            },
        },
    },
}

PLATFORM_LABELS = {
    "app.kubernetes.io/managed-by": "pulumi",
    "app.kubernetes.io/part-of": "pulumi-lab",
}
