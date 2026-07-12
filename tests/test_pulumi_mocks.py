import asyncio
from types import SimpleNamespace
from typing import Any

import pulumi
import pytest
from pulumi.runtime import MockCallArgs, MockResourceArgs, Mocks, set_mocks
from pulumi.runtime.config import set_all_config

from paas_platform.defaults import service_config
from paas_platform.service import (
    _env_from,
    _network_policy_ports,
    _readiness_probe,
    _secret_config_names,
    _target_config,
    deploy_service,
)

asyncio.set_event_loop(asyncio.new_event_loop())


class RecordingMocks(Mocks):
    def __init__(self) -> None:
        self.resources: list[dict[str, Any]] = []

    def new_resource(self, args: MockResourceArgs) -> tuple[str, dict[str, Any]]:
        self.resources.append(
            {
                "type": args.typ,
                "name": args.name,
                "inputs": args.inputs,
            }
        )
        return f"{args.name}_id", args.inputs

    def call(self, args: MockCallArgs) -> tuple[dict[str, Any], None]:
        return args.args, None


mocks = RecordingMocks()
set_mocks(mocks, project="pulumi-playground-k8s", stack="dev")
set_all_config(
    {
        "configured-api:DATABASE_URL": "test-database-url",
        "configured-api:API_TOKEN": "test-api-token",
    },
    secret_keys=[
        "configured-api:DATABASE_URL",
        "configured-api:API_TOKEN",
    ],
)


def _resources_by_type(resource_type: str) -> list[dict[str, Any]]:
    return [
        resource
        for resource in mocks.resources
        if resource["type"] == resource_type
    ]


def _dummy_service(name: str = "dummy-api", **overrides: Any) -> dict[str, Any]:
    return {
        "name": name,
        "image": f"ghcr.io/example/{name}:latest",
        "targetClusters": ["local"],
        **overrides,
    }


def test_disabled_target_cluster_is_skipped():
    outputs = deploy_service(
        _dummy_service(
            "disabled-api",
            targetClusters=[
                {
                    "name": "local",
                    "enabled": False,
                }
            ],
        )
    )

    assert outputs == []


def test_unknown_cluster_target_raises_clear_error():
    with pytest.raises(ValueError, match="Unknown cluster target: missing"):
        _target_config("api", "missing")


def test_disabled_readiness_probe_returns_none():
    assert _readiness_probe({"enabled": False}, 8080) is None


def test_ingress_requires_service():
    with pytest.raises(ValueError, match="broken enables ingress but disables service"):
        deploy_service(
            _dummy_service(
                "broken",
                service={
                    "enabled": False,
                },
                ingress={
                    "enabled": True,
                },
            )
        )


def test_service_config_resolves_platform_environment_service_and_target_defaults():
    resolved = service_config(
        {
            "name": "precedence-api",
            "image": "ghcr.io/example/precedence-api:latest",
            "replicas": 3,
            "resources": {
                "requests": {
                    "memory": "96Mi",
                },
            },
            "service": {
                "type": "ClusterIP",
            },
            "targetClusters": ["future-cluster"],
        },
        "staging",
        {
            "name": "future-cluster",
            "replicas": 4,
            "resources": {
                "limits": {
                    "cpu": "500m",
                },
            },
            "service": {
                "type": "NodePort",
                "ports": [
                    {
                        "name": "http",
                        "port": 9000,
                        "targetPort": 8080,
                    },
                ],
            },
        },
    )

    assert resolved["replicas"] == 4
    assert resolved["resources"] == {
        "requests": {
            "cpu": "50m",
            "memory": "96Mi",
        },
        "limits": {
            "cpu": "500m",
            "memory": "256Mi",
        },
    }
    assert resolved["service"] == {
        "enabled": True,
        "type": "NodePort",
        "ports": [
            {
                "name": "http",
                "port": 9000,
                "targetPort": 8080,
            },
        ],
    }
    assert resolved["readinessProbe"] == {
        "enabled": True,
        "path": "/",
        "initialDelaySeconds": 3,
        "periodSeconds": 5,
    }


@pulumi.runtime.test
def test_service_defaults_create_namespace_deployment_and_service():
    outputs = deploy_service(
        _dummy_service("default-api")
    )

    def check_outputs(args: list[Any]) -> None:
        namespace, deployment, service = args

        assert namespace == "default-api-dev"
        assert deployment == "default-api"
        assert service == "default-api"

        namespaces = [
            resource
            for resource in _resources_by_type("kubernetes:core/v1:Namespace")
            if resource["name"] == "default-api-local-namespace"
        ]
        deployments = [
            resource
            for resource in _resources_by_type("kubernetes:apps/v1:Deployment")
            if resource["name"] == "default-api-local-deployment"
        ]
        services = [
            resource
            for resource in _resources_by_type("kubernetes:core/v1:Service")
            if resource["name"] == "default-api-local-service"
        ]
        ingresses = [
            resource
            for resource in _resources_by_type("kubernetes:networking.k8s.io/v1:Ingress")
            if resource["name"] == "default-api-local-ingress"
        ]

        assert len(namespaces) == 1
        assert len(deployments) == 1
        assert len(services) == 1
        assert len(ingresses) == 0
        assert len(_resources_by_type("kubernetes:core/v1:ConfigMap")) == 0
        assert len(_resources_by_type("kubernetes:core/v1:Secret")) == 0
        assert len(_resources_by_type("kubernetes:networking.k8s.io/v1:NetworkPolicy")) == 0

        namespace_inputs = namespaces[0]["inputs"]
        assert namespace_inputs["metadata"]["name"] == "default-api-dev"
        assert namespace_inputs["metadata"]["labels"]["paas.openai.com/environment"] == "dev"

        deployment_inputs = deployments[0]["inputs"]
        container = deployment_inputs["spec"]["template"]["spec"]["containers"][0]
        assert deployment_inputs["metadata"]["namespace"] == "default-api-dev"
        assert deployment_inputs["spec"]["replicas"] == 1
        assert container["image"] == "ghcr.io/example/default-api:latest"
        assert container["ports"] == [{"containerPort": 80}]
        assert container["readinessProbe"]["httpGet"] == {"path": "/", "port": 80}
        assert "envFrom" not in container

        service_inputs = services[0]["inputs"]
        assert service_inputs["spec"]["type"] == "ClusterIP"
        assert service_inputs["spec"]["ports"][0]["port"] == 80
        assert service_inputs["spec"]["ports"][0]["targetPort"] == 80
        assert container["resources"] == {
            "requests": {
                "cpu": "25m",
                "memory": "32Mi",
            },
            "limits": {
                "cpu": "100m",
                "memory": "128Mi",
            },
        }

    return pulumi.Output.all(
        outputs[0]["namespace"],
        outputs[0]["deployment"],
        outputs[0]["service"],
    ).apply(check_outputs)


@pulumi.runtime.test
def test_dummy_api_service_creates_config_ingress_and_skips_disabled_target():
    outputs = deploy_service(
        _dummy_service(
            "api",
            image="httpd:2.4-alpine",
            containerPort=80,
            port=8080,
            replicas=2,
            env={
                "APP_ENV": "dev",
                "SERVICE_ROLE": "api",
            },
            config={
                "LOG_LEVEL": "info",
                "FEATURE_FLAG": "platform-examples",
            },
            ingress={
                "enabled": True,
                "host": "api.localhost",
                "annotations": {
                    "pulumi.com/skipAwait": "true",
                },
            },
            targetClusters=[
                "local",
                {
                    "name": "future-cluster",
                    "enabled": False,
                },
            ],
        )
    )

    def check_outputs(args: list[Any]) -> None:
        namespace, deployment, service, ingress, config_map = args

        assert len(outputs) == 1
        assert namespace == "api-dev"
        assert deployment == "api"
        assert service == "api"
        assert ingress == "api"
        assert config_map == "api"

        deployments = [
            resource
            for resource in _resources_by_type("kubernetes:apps/v1:Deployment")
            if resource["name"] == "api-local-deployment"
        ]
        services = [
            resource
            for resource in _resources_by_type("kubernetes:core/v1:Service")
            if resource["name"] == "api-local-service"
        ]
        ingresses = [
            resource
            for resource in _resources_by_type("kubernetes:networking.k8s.io/v1:Ingress")
            if resource["name"] == "api-local-ingress"
        ]
        config_maps = [
            resource
            for resource in _resources_by_type("kubernetes:core/v1:ConfigMap")
            if resource["name"] == "api-local-config-map"
        ]
        future_deployments = [
            resource
            for resource in _resources_by_type("kubernetes:apps/v1:Deployment")
            if resource["name"] == "api-future-cluster-deployment"
        ]

        assert len(deployments) == 1
        assert len(services) == 1
        assert len(ingresses) == 1
        assert len(config_maps) == 1
        assert len(future_deployments) == 0

        deployment_inputs = deployments[0]["inputs"]
        container = deployment_inputs["spec"]["template"]["spec"]["containers"][0]
        assert deployment_inputs["spec"]["replicas"] == 2
        assert container["image"] == "httpd:2.4-alpine"
        assert container["ports"] == [{"containerPort": 80}]
        assert container["env"] == [
            {
                "name": "APP_ENV",
                "value": "dev",
            },
            {
                "name": "SERVICE_ROLE",
                "value": "api",
            },
        ]
        assert container["envFrom"] == [
            {
                "configMapRef": {
                    "name": "api",
                },
            },
        ]

        config_map_inputs = config_maps[0]["inputs"]
        assert config_map_inputs["data"] == {
            "LOG_LEVEL": "info",
            "FEATURE_FLAG": "platform-examples",
        }

        service_inputs = services[0]["inputs"]
        assert service_inputs["spec"]["ports"][0]["port"] == 8080
        assert service_inputs["spec"]["ports"][0]["targetPort"] == 80

        ingress_inputs = ingresses[0]["inputs"]
        assert ingress_inputs["metadata"]["annotations"] == {
            "pulumi.com/skipAwait": "true",
        }
        rule = ingress_inputs["spec"]["rules"][0]
        backend = rule["http"]["paths"][0]["backend"]["service"]
        assert rule["host"] == "api.localhost"
        assert backend["name"] == "api"
        assert backend["port"]["number"] == 8080

    return pulumi.Output.all(
        outputs[0]["namespace"],
        outputs[0]["deployment"],
        outputs[0]["service"],
        outputs[0]["ingress"],
        outputs[0]["configMap"],
    ).apply(check_outputs)


@pulumi.runtime.test
def test_dummy_worker_service_creates_deployment_without_service():
    outputs = deploy_service(
        _dummy_service(
            "worker",
            image="registry.k8s.io/pause:3.10",
            env={
                "APP_ENV": "dev",
                "SERVICE_ROLE": "worker",
            },
            service={
                "enabled": False,
            },
            readinessProbe={
                "enabled": False,
            },
        )
    )

    def check_outputs(args: list[Any]) -> None:
        namespace, deployment, service, ingress = args

        assert namespace == "worker-dev"
        assert deployment == "worker"
        assert service is None
        assert ingress is None

        deployments = [
            resource
            for resource in _resources_by_type("kubernetes:apps/v1:Deployment")
            if resource["name"] == "worker-local-deployment"
        ]
        services = [
            resource
            for resource in _resources_by_type("kubernetes:core/v1:Service")
            if resource["name"] == "worker-local-service"
        ]

        assert len(deployments) == 1
        assert len(services) == 0

        container = deployments[0]["inputs"]["spec"]["template"]["spec"]["containers"][0]
        assert container["image"] == "registry.k8s.io/pause:3.10"
        assert container["env"] == [
            {
                "name": "APP_ENV",
                "value": "dev",
            },
            {
                "name": "SERVICE_ROLE",
                "value": "worker",
            },
        ]
        assert "readinessProbe" not in container

    return pulumi.Output.all(
        outputs[0]["namespace"],
        outputs[0]["deployment"],
        outputs[0]["service"],
        outputs[0]["ingress"],
    ).apply(check_outputs)


@pulumi.runtime.test
def test_service_can_target_future_cluster_with_cluster_overrides():
    outputs = deploy_service(
        {
            "name": "multi-api",
            "image": "httpd:2.4-alpine",
            "containerPort": 80,
            "port": 8080,
            "config": {
                "LOG_LEVEL": "info",
            },
            "targetClusters": [
                "local",
                {
                    "name": "future-cluster",
                    "replicas": 3,
                    "env": {
                        "APP_ENV": "staging",
                    },
                    "config": {
                        "LOG_LEVEL": "debug",
                    },
                },
            ],
        }
    )

    def check_outputs(args: list[Any]) -> None:
        local_namespace, future_namespace, future_deployment, future_config_map = args

        assert local_namespace == "multi-api-dev"
        assert future_namespace == "multi-api-staging"
        assert future_deployment == "multi-api"
        assert future_config_map == "multi-api"

        future_namespaces = [
            resource
            for resource in _resources_by_type("kubernetes:core/v1:Namespace")
            if resource["name"] == "multi-api-future-cluster-namespace"
        ]
        future_deployments = [
            resource
            for resource in _resources_by_type("kubernetes:apps/v1:Deployment")
            if resource["name"] == "multi-api-future-cluster-deployment"
        ]
        future_config_maps = [
            resource
            for resource in _resources_by_type("kubernetes:core/v1:ConfigMap")
            if resource["name"] == "multi-api-future-cluster-config-map"
        ]
        future_services = [
            resource
            for resource in _resources_by_type("kubernetes:core/v1:Service")
            if resource["name"] == "multi-api-future-cluster-service"
        ]

        assert len(outputs) == 2
        assert len(future_namespaces) == 1
        assert len(future_deployments) == 1
        assert len(future_config_maps) == 1
        assert len(future_services) == 1

        namespace_inputs = future_namespaces[0]["inputs"]
        assert namespace_inputs["metadata"]["labels"]["paas.openai.com/environment"] == "staging"

        deployment_inputs = future_deployments[0]["inputs"]
        container = deployment_inputs["spec"]["template"]["spec"]["containers"][0]
        assert deployment_inputs["metadata"]["namespace"] == "multi-api-staging"
        assert deployment_inputs["spec"]["replicas"] == 3
        assert container["env"] == [
            {
                "name": "APP_ENV",
                "value": "staging",
            },
        ]
        assert container["resources"] == {
            "requests": {
                "cpu": "50m",
                "memory": "64Mi",
            },
            "limits": {
                "cpu": "250m",
                "memory": "256Mi",
            },
        }

        assert future_config_maps[0]["inputs"]["data"] == {
            "LOG_LEVEL": "debug",
        }
        assert future_services[0]["inputs"]["spec"]["type"] == "LoadBalancer"

    return pulumi.Output.all(
        outputs[0]["namespace"],
        outputs[1]["namespace"],
        outputs[1]["deployment"],
        outputs[1]["configMap"],
    ).apply(check_outputs)


@pulumi.runtime.test
def test_service_overrides_port_replicas_ingress_and_namespace():
    outputs = deploy_service(
        {
            "name": "web",
            "image": "ghcr.io/example/web:latest",
            "port": 8080,
            "replicas": 3,
            "ingress": {
                "enabled": True,
                "host": "web.localhost",
            },
            "targetClusters": [
                {
                    "name": "local",
                    "namespace": "custom-web",
                }
            ],
        }
    )

    def check_outputs(args: list[Any]) -> None:
        namespace, deployment, service, ingress = args

        assert namespace == "custom-web"
        assert deployment == "web"
        assert service == "web"
        assert ingress == "web"

        deployments = [
            resource
            for resource in _resources_by_type("kubernetes:apps/v1:Deployment")
            if resource["name"] == "web-local-deployment"
        ]
        services = [
            resource
            for resource in _resources_by_type("kubernetes:core/v1:Service")
            if resource["name"] == "web-local-service"
        ]
        ingresses = [
            resource
            for resource in _resources_by_type("kubernetes:networking.k8s.io/v1:Ingress")
            if resource["name"] == "web-local-ingress"
        ]

        assert len(deployments) == 1
        assert len(services) == 1
        assert len(ingresses) == 1

        deployment_inputs = deployments[0]["inputs"]
        container = deployment_inputs["spec"]["template"]["spec"]["containers"][0]
        assert deployment_inputs["metadata"]["namespace"] == "custom-web"
        assert deployment_inputs["spec"]["replicas"] == 3
        assert container["ports"] == [{"containerPort": 8080}]

        service_inputs = services[0]["inputs"]
        assert service_inputs["spec"]["ports"][0]["port"] == 8080
        assert service_inputs["spec"]["ports"][0]["targetPort"] == 8080

        ingress_inputs = ingresses[0]["inputs"]
        rule = ingress_inputs["spec"]["rules"][0]
        backend = rule["http"]["paths"][0]["backend"]["service"]
        assert rule["host"] == "web.localhost"
        assert backend["name"] == "web"
        assert backend["port"]["number"] == 8080

    return pulumi.Output.all(
        outputs[0]["namespace"],
        outputs[0]["deployment"],
        outputs[0]["service"],
        outputs[0]["ingress"],
    ).apply(check_outputs)


@pulumi.runtime.test
def test_service_config_and_secrets_create_env_from_resources():
    outputs = deploy_service(
        {
            "name": "configured-api",
            "image": "ghcr.io/example/configured-api:latest",
            "config": {
                "LOG_LEVEL": "info",
                "FEATURE_FLAG": "enabled",
            },
            "secrets": [
                "DATABASE_URL",
                "API_TOKEN",
            ],
            "targetClusters": ["local"],
        }
    )

    def check_outputs(args: list[Any]) -> None:
        config_map, secret = args

        assert config_map == "configured-api"
        assert secret == "configured-api"

    return pulumi.Output.all(
        outputs[0]["configMap"],
        outputs[0]["secret"],
    ).apply(check_outputs)


def test_secret_config_names_merge_service_and_cluster_without_duplicates():
    assert _secret_config_names(
        {
            "secrets": [
                "DATABASE_URL",
                "API_TOKEN",
            ],
        },
        {
            "secrets": [
                "API_TOKEN",
                "WEBHOOK_SECRET",
            ],
        },
    ) == [
        "DATABASE_URL",
        "API_TOKEN",
        "WEBHOOK_SECRET",
    ]


def test_env_from_references_config_map_and_secret_names():
    config_map = SimpleNamespace(metadata={"name": "configured-api"})
    secret = SimpleNamespace(metadata={"name": "configured-api"})

    assert _env_from(config_map, secret) == [
        {
            "configMapRef": {
                "name": "configured-api",
            },
        },
        {
            "secretRef": {
                "name": "configured-api",
            },
        },
    ]


@pulumi.runtime.test
def test_network_policy_allows_external_egress_by_default():
    outputs = deploy_service(
        {
            "name": "api",
            "image": "ghcr.io/example/api:latest",
            "port": 8080,
            "networkPolicy": {
                "enabled": True,
                "ingress": {
                    "fromSameNamespace": True,
                    "fromServices": ["worker"],
                    "fromNamespaces": ["ingress-nginx"],
                },
            },
            "targetClusters": ["local"],
        }
    )

    def check_outputs(args: list[Any]) -> None:
        network_policy = args[0]

        assert network_policy == "api"

        policies = [
            resource
            for resource in _resources_by_type("kubernetes:networking.k8s.io/v1:NetworkPolicy")
            if resource["name"] == "api-local-network-policy"
        ]

        assert len(policies) == 1

        policy_inputs = policies[0]["inputs"]
        assert policy_inputs["metadata"]["namespace"] == "api-dev"
        assert policy_inputs["spec"]["policyTypes"] == ["Ingress"]
        assert "egress" not in policy_inputs["spec"]

        ingress_rule = policy_inputs["spec"]["ingress"][0]
        assert ingress_rule["ports"] == [{"protocol": "TCP", "port": 8080}]
        assert ingress_rule["from"] == [
            {"podSelector": {}},
            {
                "namespaceSelector": {
                    "matchLabels": {
                        "kubernetes.io/metadata.name": "ingress-nginx",
                    },
                },
            },
            {
                "podSelector": {
                    "matchLabels": {
                        "app.kubernetes.io/name": "worker",
                    },
                },
            },
        ]

    return pulumi.Output.all(outputs[0]["networkPolicy"]).apply(check_outputs)


@pulumi.runtime.test
def test_network_policy_can_restrict_egress():
    outputs = deploy_service(
        {
            "name": "worker",
            "image": "ghcr.io/example/worker:latest",
            "networkPolicy": {
                "enabled": True,
                "ingress": {
                    "fromServices": ["api"],
                },
                "egress": {
                    "allowExternal": False,
                    "toServices": ["redis"],
                    "toNamespaces": ["monitoring"],
                    "ports": [
                        {
                            "protocol": "TCP",
                            "port": 6379,
                        },
                    ],
                },
            },
            "targetClusters": ["local"],
        }
    )

    def check_outputs(args: list[Any]) -> None:
        network_policy = args[0]

        assert network_policy == "worker"

        policies = [
            resource
            for resource in _resources_by_type("kubernetes:networking.k8s.io/v1:NetworkPolicy")
            if resource["name"] == "worker-local-network-policy"
        ]

        assert len(policies) == 1

        policy_inputs = policies[0]["inputs"]
        assert policy_inputs["spec"]["policyTypes"] == ["Ingress", "Egress"]

        ingress_rule = policy_inputs["spec"]["ingress"][0]
        assert ingress_rule["ports"] == [{"protocol": "TCP", "port": 80}]
        assert ingress_rule["from"] == [
            {
                "podSelector": {
                    "matchLabels": {
                        "app.kubernetes.io/name": "api",
                    },
                },
            },
        ]

        egress_rule = policy_inputs["spec"]["egress"][0]
        assert egress_rule["ports"] == [{"protocol": "TCP", "port": 6379}]
        assert egress_rule["to"] == [
            {
                "namespaceSelector": {
                    "matchLabels": {
                        "kubernetes.io/metadata.name": "monitoring",
                    },
                },
            },
            {
                "podSelector": {
                    "matchLabels": {
                        "app.kubernetes.io/name": "redis",
                    },
                },
            },
        ]

    return pulumi.Output.all(outputs[0]["networkPolicy"]).apply(check_outputs)


@pulumi.runtime.test
def test_network_policy_without_ingress_peers_denies_ingress():
    outputs = deploy_service(
        {
            "name": "isolated",
            "image": "ghcr.io/example/isolated:latest",
            "networkPolicy": {
                "enabled": True,
            },
            "targetClusters": ["local"],
        }
    )

    def check_outputs(args: list[Any]) -> None:
        network_policy = args[0]

        assert network_policy == "isolated"

        policies = [
            resource
            for resource in _resources_by_type("kubernetes:networking.k8s.io/v1:NetworkPolicy")
            if resource["name"] == "isolated-local-network-policy"
        ]

        assert len(policies) == 1
        assert policies[0]["inputs"]["spec"]["ingress"] == []
        assert "egress" not in policies[0]["inputs"]["spec"]

    return pulumi.Output.all(outputs[0]["networkPolicy"]).apply(check_outputs)


@pulumi.runtime.test
def test_network_policy_restricted_egress_without_peers_denies_egress():
    outputs = deploy_service(
        {
            "name": "locked-down",
            "image": "ghcr.io/example/locked-down:latest",
            "networkPolicy": {
                "enabled": True,
                "egress": {
                    "allowExternal": False,
                },
            },
            "targetClusters": ["local"],
        }
    )

    def check_outputs(args: list[Any]) -> None:
        network_policy = args[0]

        assert network_policy == "locked-down"

        policies = [
            resource
            for resource in _resources_by_type("kubernetes:networking.k8s.io/v1:NetworkPolicy")
            if resource["name"] == "locked-down-local-network-policy"
        ]

        assert len(policies) == 1
        assert policies[0]["inputs"]["spec"]["egress"] == []

    return pulumi.Output.all(outputs[0]["networkPolicy"]).apply(check_outputs)


def test_network_policy_ports_without_config_or_default_returns_empty():
    assert _network_policy_ports(None) == []
