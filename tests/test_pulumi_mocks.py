import asyncio
from typing import Any

import pulumi
import pytest
from pulumi.runtime import MockCallArgs, MockResourceArgs, Mocks, set_mocks

from paas_platform.service import _readiness_probe, _target_config, deploy_service
from services import SERVICES

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


def _resources_by_type(resource_type: str) -> list[dict[str, Any]]:
    return [
        resource
        for resource in mocks.resources
        if resource["type"] == resource_type
    ]


def test_service_registry_loads_nginx_service():
    nginx_service = next(service for service in SERVICES if service["name"] == "nginx")
    assert nginx_service["image"] == "nginx:1.27-alpine"
    assert nginx_service["targetClusters"] == ["local"]


def test_disabled_target_cluster_is_skipped():
    outputs = deploy_service(
        {
            "name": "disabled-api",
            "image": "ghcr.io/example/disabled-api:latest",
            "targetClusters": [
                {
                    "name": "local",
                    "enabled": False,
                }
            ],
        }
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
            {
                "name": "broken",
                "image": "ghcr.io/example/broken:latest",
                "service": {
                    "enabled": False,
                },
                "ingress": {
                    "enabled": True,
                },
                "targetClusters": ["local"],
            }
        )


@pulumi.runtime.test
def test_service_defaults_create_namespace_deployment_and_service():
    outputs = deploy_service(
        {
            "name": "api",
            "image": "ghcr.io/example/api:latest",
            "targetClusters": ["local"],
        }
    )

    def check_outputs(args: list[Any]) -> None:
        namespace, deployment, service = args

        assert namespace == "api-dev"
        assert deployment == "api"
        assert service == "api"

        namespaces = [
            resource
            for resource in _resources_by_type("kubernetes:core/v1:Namespace")
            if resource["name"] == "api-local-namespace"
        ]
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
        ingresses = _resources_by_type("kubernetes:networking.k8s.io/v1:Ingress")

        assert len(namespaces) == 1
        assert len(deployments) == 1
        assert len(services) == 1
        assert len(ingresses) == 0

        namespace_inputs = namespaces[0]["inputs"]
        assert namespace_inputs["metadata"]["name"] == "api-dev"
        assert namespace_inputs["metadata"]["labels"]["paas.openai.com/environment"] == "dev"

        deployment_inputs = deployments[0]["inputs"]
        container = deployment_inputs["spec"]["template"]["spec"]["containers"][0]
        assert deployment_inputs["metadata"]["namespace"] == "api-dev"
        assert deployment_inputs["spec"]["replicas"] == 1
        assert container["image"] == "ghcr.io/example/api:latest"
        assert container["ports"] == [{"containerPort": 80}]
        assert container["readinessProbe"]["httpGet"] == {"path": "/", "port": 80}

        service_inputs = services[0]["inputs"]
        assert service_inputs["spec"]["type"] == "ClusterIP"
        assert service_inputs["spec"]["ports"][0]["port"] == 80

    return pulumi.Output.all(
        outputs[0]["namespace"],
        outputs[0]["deployment"],
        outputs[0]["service"],
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
        ingresses = _resources_by_type("kubernetes:networking.k8s.io/v1:Ingress")

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
