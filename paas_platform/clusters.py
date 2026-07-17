CLUSTERS = {
    "dev": {
        "name": "dev",
        "context": "kind-dev",
        "environment": "dev",
        "paas": {
            "argocd": {
                "enabled": True,
                "managementCluster": "cicd",
                "namespace": "argocd",
                "destination": {
                    "name": "dev",
                    "server": "https://dev-control-plane:6443",
                    "clusterRoleName": "cluster-admin",
                },
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
    "cicd": {
        "name": "cicd",
        "context": "kind-cicd",
        "environment": "platform",
    },
}

PLATFORM_LABELS = {
    "app.kubernetes.io/managed-by": "pulumi",
    "app.kubernetes.io/part-of": "pulumi-lab",
}
