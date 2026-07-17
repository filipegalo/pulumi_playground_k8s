CLUSTERS = {
    "dev": {
        "name": "dev",
        "context": "kind-dev",
        "environment": "dev",
        "gitops": {
            "enabled": True,
            "cicdCluster": "cicd",
            "destination": {
                "name": "dev",
                "server": "https://dev-control-plane:6443",
                "clusterRoleName": "cluster-admin",
            },
            "registryPath": "gitops/clusters/dev/registry",
        },
    },
    "staging": {
        "name": "staging",
        "context": "kind-staging",
        "environment": "staging",
        "gitops": {
            "enabled": True,
            "cicdCluster": "cicd",
            "destination": {
                "name": "staging",
                "server": "https://staging-control-plane:6443",
                "clusterRoleName": "cluster-admin",
            },
            "registryPath": "gitops/clusters/staging/registry",
        },
    },
    "cicd": {
        "name": "cicd",
        "context": "kind-cicd",
        "environment": "platform",
        "paas": {
            "argocd": {
                "enabled": True,
                "namespace": "argocd",
                "adminPassword": {
                    "configNamespace": "argocd",
                    "hashConfigKey": "ADMIN_PASSWORD_BCRYPT",
                    "mtimeConfigKey": "ADMIN_PASSWORD_MTIME",
                },
                "repository": {
                    "url": "https://github.com/filipegalo/pulumi_playground_k8s.git",
                    "targetRevision": "master",
                },
            },
        },
    },
}

PLATFORM_LABELS = {
    "app.kubernetes.io/managed-by": "pulumi",
    "app.kubernetes.io/part-of": "pulumi-lab",
}
