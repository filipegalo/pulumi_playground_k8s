CLUSTERS = {
    "dev": {
        "name": "dev",
        "context": "kind-dev",
        "environment": "dev",
        "paas": {
            "argocd": {
                "enabled": True,
                "namespace": "argocd",
                "repository": {
                    "url": "https://github.com/filipegalo/pulumi_playground_k8s.git",
                    "targetRevision": "master",
                    "registryPath": "gitops/clusters/dev/registry",
                },
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
