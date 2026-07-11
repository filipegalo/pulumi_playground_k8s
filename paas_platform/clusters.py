CLUSTERS = {
    "local": {
        "name": "local",
        "context": "kind-local",
        "environment": "dev",
    },
    "future-cluster": {
        "name": "future-cluster",
        "context": "some-other-context",
        "environment": "staging",
    },
}

PLATFORM_LABELS = {
    "app.kubernetes.io/managed-by": "pulumi",
    "app.kubernetes.io/part-of": "pulumi-lab",
}
