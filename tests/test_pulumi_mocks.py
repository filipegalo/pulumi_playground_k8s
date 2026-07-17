import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pulumi
import pytest
from pulumi.runtime import MockCallArgs, MockResourceArgs, Mocks, set_mocks
from pulumi.runtime.config import set_all_config

import paas
import paas.argocd as argocd
from paas import load_paas_services
from paas.argocd import (
    _admin_password_values,
    _argocd_helm_config,
    _registration_config,
    destination_config,
    deploy_argocd,
    deploy_argocd_workload,
    is_argocd_enabled,
    is_gitops_enabled,
)
from paas.gitops import deploy_gitops_prerequisites
from paas_platform.defaults import service_config
from paas_platform.resources import _repository_opts
from paas_platform.service import (
    _env_from,
    _network_policy_ports,
    _readiness_probe,
    _secret_config_names,
    _target_config,
    deploy_service,
)
from services import load_services
from scripts.generate_gitops import render_registry

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
        outputs = args.inputs
        if args.name.endswith("-manager-token"):
            outputs = {
                **args.inputs,
                "data": {
                    "token": "dGVzdC10b2tlbg==",
                    "ca.crt": "dGVzdC1jYQ==",
                },
            }
        return f"{args.name}_id", outputs

    def call(self, args: MockCallArgs) -> tuple[dict[str, Any], None]:
        return args.args, None


mocks = RecordingMocks()
set_mocks(mocks, project="pulumi-playground-k8s", stack="dev")
set_all_config(
    {
        "configured-api:DATABASE_URL": "test-database-url",
        "configured-api:API_TOKEN": "test-api-token",
        "argocd:GIT_USERNAME": "git-user",
        "argocd:GIT_PASSWORD": "git-password",
        "argocd:GIT_SSH_KEY": "private-key",
        "argocd:ADMIN_PASSWORD_BCRYPT": "$2a$12$test-admin-password-hash",
        "argocd:ADMIN_PASSWORD_MTIME": "2026-07-17T16:00:00Z",
        "nginx:DUMMY_SECRET": "dummy-secret",
        "nginx:DUMMY_SECRET_2": "dummy-secret-2",
    },
    secret_keys=[
        "configured-api:DATABASE_URL",
        "configured-api:API_TOKEN",
        "argocd:GIT_USERNAME",
        "argocd:GIT_PASSWORD",
        "argocd:GIT_SSH_KEY",
        "argocd:ADMIN_PASSWORD_BCRYPT",
        "nginx:DUMMY_SECRET",
        "nginx:DUMMY_SECRET_2",
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
        "targetClusters": ["dev"],
        **overrides,
    }


def test_load_services_uses_stack_named_target_overlays():
    dev_services = load_services("dev")
    staging_services = load_services("staging")

    assert [service["name"] for service in dev_services] == ["api", "nginx"]
    assert [service["name"] for service in staging_services] == ["nginx"]
    assert all(
        service["targetClusters"][0]["name"] == "dev"
        for service in dev_services
    )
    assert staging_services[0]["targetClusters"] == [
        {
            "name": "staging",
            "env": {
                "APP_ENV": "staging",
            },
        },
    ]


def test_generated_registry_matches_service_declarations():
    rendered = render_registry("dev")
    registry_path = Path("gitops/clusters/dev/registry")

    assert set(rendered) == {"api.yaml", "nginx.yaml"}
    assert {
        path.name: path.read_text()
        for path in registry_path.glob("*.yaml")
    } == rendered

    api = json.loads(rendered["api.yaml"])
    assert api["metadata"]["name"] == "api-dev"
    assert api["metadata"]["finalizers"] == [
        "resources-finalizer.argocd.argoproj.io"
    ]
    assert api["spec"]["destination"] == {"name": "dev", "namespace": "api"}
    api_values = json.loads(api["spec"]["source"]["helm"]["values"])
    assert api_values["service"]["ports"] == [
        {"name": "http", "port": 8080, "targetPort": 80}
    ]
    nginx = json.loads(rendered["nginx.yaml"])
    nginx_values = json.loads(nginx["spec"]["source"]["helm"]["values"])
    assert nginx_values["networkPolicy"]["spec"]["policyTypes"] == [
        "Ingress"
    ]
    staging = json.loads(render_registry("staging")["nginx.yaml"])
    assert staging["metadata"]["name"] == "nginx-staging"
    assert json.loads(rendered["nginx.yaml"])["metadata"]["name"] == "nginx-dev"
    assert staging["spec"]["destination"] == {
        "name": "staging",
        "namespace": "nginx",
    }


def test_argocd_is_enabled_per_cluster_as_a_paas_service():
    dev_paas = load_paas_services("dev")
    staging_paas = load_paas_services("staging")
    cicd_paas = load_paas_services("cicd")

    assert dev_paas == []
    assert staging_paas == []
    assert [service["name"] for service in cicd_paas] == ["argocd"]
    assert cicd_paas[0]["type"] == "helm"
    assert cicd_paas[0]["targetClusters"] == [
        {
            "name": "cicd",
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
        }
    ]
    assert cicd_paas[0]["helm"] == {
        "chart": "argo-cd",
        "repository": "https://argoproj.github.io/argo-helm/",
        "releaseName": "argocd",
    }


def test_loading_paas_for_an_unknown_cluster_raises_clear_error():
    with pytest.raises(ValueError, match="Unknown cluster target: missing"):
        load_paas_services("missing")


def test_argocd_enablement_is_cluster_specific():
    assert is_argocd_enabled("cicd") is True
    assert is_argocd_enabled("dev") is False
    assert is_argocd_enabled("staging") is False
    assert is_argocd_enabled("missing") is False
    assert is_gitops_enabled("dev") is True
    assert is_gitops_enabled("staging") is True
    assert is_gitops_enabled("cicd") is False
    assert is_gitops_enabled("missing") is False
    assert deploy_argocd("dev") == {}
    assert deploy_argocd_workload("cicd") == {}
    with pytest.raises(ValueError, match="Unknown cluster target: missing"):
        deploy_argocd("missing")
    with pytest.raises(ValueError, match="Unknown cluster target: missing"):
        deploy_argocd_workload("missing")


def test_argocd_admin_password_is_optional():
    assert _admin_password_values({}) == {}
    assert _argocd_helm_config({}) == {
        "chart": "argo-cd",
        "repository": "https://argoproj.github.io/argo-helm/",
        "releaseName": "argocd",
        "values": {},
    }


@pulumi.runtime.test
def test_argocd_admin_password_uses_secret_pulumi_config_and_merges_values():
    helm_config = _argocd_helm_config(
        {
            "adminPassword": {"configNamespace": "argocd"},
            "helm": {
                "values": {
                    "configs": {"secret": {"createSecret": True}},
                    "server": {"service": {"type": "ClusterIP"}},
                }
            },
        }
    )

    def check_values(args: list[Any]) -> None:
        password_hash, password_mtime, password_is_secret = args
        assert password_hash == "$2a$12$test-admin-password-hash"
        assert password_mtime == "2026-07-17T16:00:00Z"
        assert password_is_secret is True
        assert helm_config["values"]["configs"]["secret"]["createSecret"] is True
        assert helm_config["values"]["server"] == {
            "service": {"type": "ClusterIP"}
        }

    secret_values = helm_config["values"]["configs"]["secret"]
    password_hash = secret_values["argocdServerAdminPassword"]
    return pulumi.Output.all(
        password_hash,
        secret_values["argocdServerAdminPasswordMtime"],
        pulumi.Output.from_input(password_hash.is_secret()),
    ).apply(check_values)


def test_argocd_registration_config_decodes_token_and_preserves_ca():
    assert json.loads(
        _registration_config(
            {
                "token": "dGVzdC10b2tlbg==",
                "ca.crt": "dGVzdC1jYQ==",
            }
        )
    ) == {
        "bearerToken": "test-token",
        "tlsClientConfig": {
            "insecure": False,
            "caData": "dGVzdC1jYQ==",
        },
    }


def test_remote_argocd_configuration_is_validated(monkeypatch: pytest.MonkeyPatch):
    invalid_clusters = {
        **argocd.CLUSTERS,
        "invalid": {
            "name": "invalid",
            "context": "kind-invalid",
            "environment": "dev",
            "gitops": {
                "enabled": True,
                "cicdCluster": "missing",
            },
        },
        "invalid-remote": {
            "name": "invalid-remote",
            "context": "kind-invalid-remote",
            "environment": "dev",
            "gitops": {
                "enabled": True,
                "cicdCluster": "cicd",
                "destination": {"name": "invalid-remote"},
                "repository": {"url": "https://example.com/repository.git"},
            },
        },
        "disabled-cicd": {
            "name": "disabled-cicd",
            "context": "kind-disabled-cicd",
            "environment": "platform",
        },
        "invalid-disabled": {
            "name": "invalid-disabled",
            "context": "kind-invalid-disabled",
            "environment": "dev",
            "gitops": {
                "enabled": True,
                "cicdCluster": "disabled-cicd",
            },
        },
    }
    monkeypatch.setattr(argocd, "CLUSTERS", invalid_clusters)
    with pytest.raises(ValueError, match="Unknown CI/CD cluster: missing"):
        argocd.deploy_argocd_workload("invalid")

    with pytest.raises(ValueError, match="missing: server, clusterRoleName"):
        destination_config("invalid-remote")

    with pytest.raises(ValueError, match="Argo CD is not enabled"):
        argocd.deploy_argocd_workload("invalid-disabled")


@pulumi.runtime.test
def test_argocd_bootstraps_registry_application_from_git():
    platform_output = deploy_argocd("cicd")
    workload_output = deploy_argocd_workload("dev")

    def check_output(args: list[Any]) -> None:
        namespace, release, registry, management_cluster, destination = args
        assert namespace == "argocd"
        assert release == "argocd"
        assert registry == "registry-dev"
        assert management_cluster == "cicd"
        assert destination == {
            "name": "dev",
            "server": "https://dev-control-plane:6443",
            "clusterRoleName": "cluster-admin",
        }

        applications = [
            resource
            for resource in mocks.resources
            if resource["name"] == "registry-dev-cicd-application"
        ]
        repository_secrets = [
            resource
            for resource in _resources_by_type("kubernetes:core/v1:Secret")
            if resource["name"] == "argocd-dev-repository-secret"
        ]
        assert len(applications) == 1
        assert repository_secrets == []
        releases = [
            resource
            for resource in mocks.resources
            if resource["name"] == "argocd-cicd-helm-release"
        ]
        assert len(releases) == 1
        release_values = releases[0]["inputs"]["values"]
        assert release_values["value"] == {
            "configs": {
                "secret": {
                    "argocdServerAdminPassword": (
                        "$2a$12$test-admin-password-hash"
                    ),
                    "argocdServerAdminPasswordMtime": (
                        "2026-07-17T16:00:00Z"
                    ),
                }
            }
        }
        cluster_secrets = [
            resource
            for resource in _resources_by_type("kubernetes:core/v1:Secret")
            if resource["name"] == "argocd-dev-cluster-secret"
        ]
        service_accounts = [
            resource
            for resource in _resources_by_type("kubernetes:core/v1:ServiceAccount")
            if resource["name"] == "argocd-dev-manager-service-account"
        ]
        bindings = [
            resource
            for resource in _resources_by_type(
                "kubernetes:rbac.authorization.k8s.io/v1:ClusterRoleBinding"
            )
            if resource["name"] == "argocd-dev-manager-binding"
        ]
        assert len(cluster_secrets) == 1
        assert len(service_accounts) == 1
        assert len(bindings) == 1
        token_secrets = [
            resource
            for resource in _resources_by_type("kubernetes:core/v1:Secret")
            if resource["name"] == "argocd-dev-manager-token"
        ]
        assert token_secrets[-1]["inputs"]["metadata"]["annotations"][
            "pulumi.com/waitFor"
        ] == "jsonpath={.data.token}"
        assert cluster_secrets[0]["inputs"]["metadata"]["labels"] == {
            "argocd.argoproj.io/secret-type": "cluster"
        }
        assert applications[0]["inputs"]["metadata"]["finalizers"] == [
            "resources-finalizer.argocd.argoproj.io"
        ]
        assert applications[0]["inputs"]["spec"] == {
            "project": "default",
            "source": {
                "repoURL": (
                    "https://github.com/filipegalo/pulumi_playground_k8s.git"
                ),
                "targetRevision": "master",
                "path": "gitops/clusters/dev/registry",
            },
            "destination": {
                "server": "https://kubernetes.default.svc",
                "namespace": "argocd",
            },
            "syncPolicy": {
                "automated": {"prune": True, "selfHeal": True},
                "syncOptions": ["CreateNamespace=true"],
            },
        }

    return pulumi.Output.all(
        platform_output["namespace"],
        platform_output["helmRelease"],
        workload_output["registryApplication"],
        workload_output["cicdCluster"],
        workload_output["destination"],
    ).apply(check_output)


@pulumi.runtime.test
def test_private_argocd_repository_uses_pulumi_backed_credentials(
    monkeypatch: pytest.MonkeyPatch,
):
    private_clusters = {
        **argocd.CLUSTERS,
        "cicd": {
            **argocd.CLUSTERS["cicd"],
            "paas": {
                "argocd": {
                    **argocd.CLUSTERS["cicd"]["paas"]["argocd"],
                    "repository": {
                        "url": "https://git.example.com/platform/repository.git",
                        "credentials": {
                            "secretName": "private-repository",
                            "usernameConfigKey": "GIT_USERNAME",
                            "passwordConfigKey": "GIT_PASSWORD",
                            "sshPrivateKeyConfigKey": "GIT_SSH_KEY",
                        },
                    },
                },
            },
        },
    }
    monkeypatch.setattr(argocd, "CLUSTERS", private_clusters)
    output = argocd.deploy_argocd("cicd")

    def check_output(repository_secret_name: str) -> None:
        assert repository_secret_name == "private-repository"
        secrets = [
            resource
            for resource in _resources_by_type("kubernetes:core/v1:Secret")
            if resource["name"] == "argocd-cicd-repository-secret"
        ]
        assert len(secrets) == 1
        assert secrets[0]["inputs"]["metadata"]["name"] == "private-repository"
        assert secrets[0]["inputs"]["metadata"]["labels"] == {
            "argocd.argoproj.io/secret-type": "repository"
        }

    return output["repositorySecret"].apply(check_output)


@pulumi.runtime.test
def test_gitops_prerequisites_create_only_non_git_secrets():
    outputs = deploy_gitops_prerequisites(load_services("dev"))

    def check_outputs(args: list[Any]) -> None:
        namespace, secret = args
        assert namespace == "nginx"
        assert secret == "nginx"
        deployments = [
            resource
            for resource in _resources_by_type("kubernetes:apps/v1:Deployment")
            if resource["name"] == "nginx-dev-deployment"
        ]
        assert deployments == []
        secrets = [
            resource
            for resource in _resources_by_type("kubernetes:core/v1:Secret")
            if resource["name"] == "nginx-dev-secret"
        ]
        assert secrets[-1]["inputs"]["metadata"]["labels"] == {
            "app.kubernetes.io/name": "nginx",
            "app.kubernetes.io/part-of": "pulumi-lab",
            "app.kubernetes.io/managed-by": "pulumi",
            "paas.openai.com/environment": "dev",
        }

    assert list(outputs) == ["nginx"]
    return pulumi.Output.all(
        outputs["nginx"]["namespace"],
        outputs["nginx"]["secret"],
    ).apply(check_outputs)


def test_enabled_paas_service_requires_a_platform_declaration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
):
    monkeypatch.setattr(paas, "_PAAS_DIR", tmp_path)

    with pytest.raises(ValueError, match="Unknown PaaS service: argocd"):
        load_paas_services("cicd")


def test_disabled_paas_service_is_skipped(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        paas,
        "CLUSTERS",
        {
            "disabled": {
                "paas": {"argocd": {"enabled": False}},
            }
        },
    )
    assert load_paas_services("disabled") == []


def test_disabled_target_cluster_is_skipped():
    outputs = deploy_service(
        _dummy_service(
            "disabled-api",
            targetClusters=[
                {
                    "name": "dev",
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
            "targetClusters": ["staging"],
        },
        "staging",
        {
            "name": "staging",
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

        assert namespace == "default-api"
        assert deployment == "default-api"
        assert service == "default-api"

        namespaces = [
            resource
            for resource in _resources_by_type("kubernetes:core/v1:Namespace")
            if resource["name"] == "default-api-dev-namespace"
        ]
        deployments = [
            resource
            for resource in _resources_by_type("kubernetes:apps/v1:Deployment")
            if resource["name"] == "default-api-dev-deployment"
        ]
        services = [
            resource
            for resource in _resources_by_type("kubernetes:core/v1:Service")
            if resource["name"] == "default-api-dev-service"
        ]
        ingresses = [
            resource
            for resource in _resources_by_type("kubernetes:networking.k8s.io/v1:Ingress")
            if resource["name"] == "default-api-dev-ingress"
        ]

        assert len(namespaces) == 1
        assert len(deployments) == 1
        assert len(services) == 1
        assert len(ingresses) == 0
        assert len(_resources_by_type("kubernetes:core/v1:ConfigMap")) == 0
        assert not any(
            resource["name"] == "default-api-dev-secret"
            for resource in _resources_by_type("kubernetes:core/v1:Secret")
        )
        assert len(_resources_by_type("kubernetes:networking.k8s.io/v1:NetworkPolicy")) == 0

        namespace_inputs = namespaces[0]["inputs"]
        assert namespace_inputs["metadata"]["name"] == "default-api"
        assert namespace_inputs["metadata"]["labels"]["paas.openai.com/environment"] == "dev"

        deployment_inputs = deployments[0]["inputs"]
        container = deployment_inputs["spec"]["template"]["spec"]["containers"][0]
        assert deployment_inputs["metadata"]["namespace"] == "default-api"
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
                "dev",
                {
                    "name": "staging",
                    "enabled": False,
                },
            ],
        )
    )

    def check_outputs(args: list[Any]) -> None:
        namespace, deployment, service, ingress, config_map = args

        assert len(outputs) == 1
        assert namespace == "api"
        assert deployment == "api"
        assert service == "api"
        assert ingress == "api"
        assert config_map == "api"

        deployments = [
            resource
            for resource in _resources_by_type("kubernetes:apps/v1:Deployment")
            if resource["name"] == "api-dev-deployment"
        ]
        services = [
            resource
            for resource in _resources_by_type("kubernetes:core/v1:Service")
            if resource["name"] == "api-dev-service"
        ]
        ingresses = [
            resource
            for resource in _resources_by_type("kubernetes:networking.k8s.io/v1:Ingress")
            if resource["name"] == "api-dev-ingress"
        ]
        config_maps = [
            resource
            for resource in _resources_by_type("kubernetes:core/v1:ConfigMap")
            if resource["name"] == "api-dev-config-map"
        ]
        future_deployments = [
            resource
            for resource in _resources_by_type("kubernetes:apps/v1:Deployment")
            if resource["name"] == "api-staging-deployment"
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

        assert namespace == "worker"
        assert deployment == "worker"
        assert service is None
        assert ingress is None

        deployments = [
            resource
            for resource in _resources_by_type("kubernetes:apps/v1:Deployment")
            if resource["name"] == "worker-dev-deployment"
        ]
        services = [
            resource
            for resource in _resources_by_type("kubernetes:core/v1:Service")
            if resource["name"] == "worker-dev-service"
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
                "dev",
                {
                    "name": "staging",
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
        (
            local_namespace,
            future_namespace,
            future_deployment,
            future_config_map,
            future_service,
        ) = args

        assert local_namespace == "multi-api"
        assert future_namespace == "multi-api"
        assert future_deployment == "multi-api"
        assert future_config_map == "multi-api"
        assert future_service == "multi-api"

        future_namespaces = [
            resource
            for resource in _resources_by_type("kubernetes:core/v1:Namespace")
            if resource["name"] == "multi-api-staging-namespace"
        ]
        future_deployments = [
            resource
            for resource in _resources_by_type("kubernetes:apps/v1:Deployment")
            if resource["name"] == "multi-api-staging-deployment"
        ]
        future_config_maps = [
            resource
            for resource in _resources_by_type("kubernetes:core/v1:ConfigMap")
            if resource["name"] == "multi-api-staging-config-map"
        ]
        future_services = [
            resource
            for resource in _resources_by_type("kubernetes:core/v1:Service")
            if resource["name"] == "multi-api-staging-service"
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
        assert deployment_inputs["metadata"]["namespace"] == "multi-api"
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
        assert future_services[0]["inputs"]["spec"]["type"] == "ClusterIP"

    return pulumi.Output.all(
        outputs[0]["namespace"],
        outputs[1]["namespace"],
        outputs[1]["deployment"],
        outputs[1]["configMap"],
        outputs[1]["service"],
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
                    "name": "dev",
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
            if resource["name"] == "web-dev-deployment"
        ]
        services = [
            resource
            for resource in _resources_by_type("kubernetes:core/v1:Service")
            if resource["name"] == "web-dev-service"
        ]
        ingresses = [
            resource
            for resource in _resources_by_type("kubernetes:networking.k8s.io/v1:Ingress")
            if resource["name"] == "web-dev-ingress"
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
            "targetClusters": ["dev"],
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


def test_repository_opts_supports_repo_alias():
    assert _repository_opts(
        {
            "repositoryOpts": {
                "username": "bot",
            },
            "repo": "https://charts.example.com",
        }
    ) == {
        "username": "bot",
        "repo": "https://charts.example.com",
    }


@pulumi.runtime.test
def test_helm_service_creates_namespace_and_release_without_container_resources():
    outputs = deploy_service(
        {
            "name": "chaos",
            "type": "helm",
            "helm": {
                "chart": "litmus",
                "repository": "https://litmuschaos.github.io/litmus-helm/",
                "version": "3.21.0",
                "values": {
                    "portal": {
                        "frontend": {
                            "service": {
                                "type": "ClusterIP",
                            },
                        },
                    },
                },
            },
            "targetClusters": [
                {
                    "name": "dev",
                    "namespace": "litmus",
                    "helm": {
                        "values": {
                            "portal": {
                                "frontend": {
                                    "service": {
                                        "type": "NodePort",
                                    },
                                },
                                "server": {
                                    "graphqlServer": {
                                        "genericEnv": {
                                            "CHAOS_CENTER_UI_ENDPOINT": (
                                                "http://chaos-litmus-frontend-service."
                                                "litmus.svc.cluster.local:9091"
                                            ),
                                        },
                                    },
                                },
                            },
                        },
                    },
                },
            ],
        }
    )

    def check_outputs(args: list[Any]) -> None:
        namespace, helm_release, deployment, service = args

        assert namespace == "litmus"
        assert helm_release == "chaos"
        assert deployment is None
        assert service is None

        namespaces = [
            resource
            for resource in _resources_by_type("kubernetes:core/v1:Namespace")
            if resource["name"] == "chaos-dev-namespace"
        ]
        releases = [
            resource
            for resource in mocks.resources
            if resource["name"] == "chaos-dev-helm-release"
        ]
        deployments = [
            resource
            for resource in _resources_by_type("kubernetes:apps/v1:Deployment")
            if resource["name"] == "chaos-dev-deployment"
        ]
        services = [
            resource
            for resource in _resources_by_type("kubernetes:core/v1:Service")
            if resource["name"] == "chaos-dev-service"
        ]

        assert len(namespaces) == 1
        assert len(releases) == 1
        assert len(deployments) == 0
        assert len(services) == 0

        release_inputs = releases[0]["inputs"]
        assert release_inputs["chart"] == "litmus"
        assert release_inputs["name"] == "chaos"
        assert release_inputs["namespace"] == "litmus"
        assert release_inputs["version"] == "3.21.0"
        assert release_inputs["repositoryOpts"]["repo"] == (
            "https://litmuschaos.github.io/litmus-helm/"
        )
        assert release_inputs["values"] == {
            "portal": {
                "frontend": {
                    "service": {
                        "type": "NodePort",
                    },
                },
                "server": {
                    "graphqlServer": {
                        "genericEnv": {
                            "CHAOS_CENTER_UI_ENDPOINT": (
                                "http://chaos-litmus-frontend-service."
                                "litmus.svc.cluster.local:9091"
                            ),
                        },
                    },
                },
            },
        }

    return pulumi.Output.all(
        outputs[0]["namespace"],
        outputs[0]["helmRelease"],
        outputs[0]["deployment"],
        outputs[0]["service"],
    ).apply(check_outputs)


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
            "targetClusters": ["dev"],
        }
    )

    def check_outputs(args: list[Any]) -> None:
        network_policy = args[0]

        assert network_policy == "api"

        policies = [
            resource
            for resource in _resources_by_type("kubernetes:networking.k8s.io/v1:NetworkPolicy")
            if resource["name"] == "api-dev-network-policy"
        ]

        assert len(policies) == 1

        policy_inputs = policies[0]["inputs"]
        assert policy_inputs["metadata"]["namespace"] == "api"
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
            "targetClusters": ["dev"],
        }
    )

    def check_outputs(args: list[Any]) -> None:
        network_policy = args[0]

        assert network_policy == "worker"

        policies = [
            resource
            for resource in _resources_by_type("kubernetes:networking.k8s.io/v1:NetworkPolicy")
            if resource["name"] == "worker-dev-network-policy"
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
            "targetClusters": ["dev"],
        }
    )

    def check_outputs(args: list[Any]) -> None:
        network_policy = args[0]

        assert network_policy == "isolated"

        policies = [
            resource
            for resource in _resources_by_type("kubernetes:networking.k8s.io/v1:NetworkPolicy")
            if resource["name"] == "isolated-dev-network-policy"
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
            "targetClusters": ["dev"],
        }
    )

    def check_outputs(args: list[Any]) -> None:
        network_policy = args[0]

        assert network_policy == "locked-down"

        policies = [
            resource
            for resource in _resources_by_type("kubernetes:networking.k8s.io/v1:NetworkPolicy")
            if resource["name"] == "locked-down-dev-network-policy"
        ]

        assert len(policies) == 1
        assert policies[0]["inputs"]["spec"]["egress"] == []

    return pulumi.Output.all(outputs[0]["networkPolicy"]).apply(check_outputs)


def test_network_policy_ports_without_config_or_default_returns_empty():
    assert _network_policy_ports(None) == []
