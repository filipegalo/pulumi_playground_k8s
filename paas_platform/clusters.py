CLUSTERS = {
    "dev": {
        "name": "dev",
        "context": "kind-dev",
        "environment": "dev",
    },
    "staging": {
        "name": "staging",
        "context": "kind-staging",
        "environment": "staging",
    },
}

PLATFORM_LABELS = {
    "app.kubernetes.io/managed-by": "pulumi",
    "app.kubernetes.io/part-of": "pulumi-lab",
}
