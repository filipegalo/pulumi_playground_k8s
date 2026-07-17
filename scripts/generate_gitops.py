#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
import sys
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from paas.argocd import is_argocd_enabled
from paas_platform.clusters import CLUSTERS
from paas_platform.defaults import service_config
from paas_platform.labels import selector_labels
from paas_platform.resources import network_policy_spec
from paas_platform.targets import default_namespace, target_config
from services import load_services

_CHART_PATH = "gitops/charts/service"


def _sync_policy() -> dict[str, Any]:
    return {
        "automated": {"prune": True, "selfHeal": True},
        "syncOptions": ["CreateNamespace=true"],
    }


def _container_values(service: dict[str, Any], cluster_name: str) -> dict[str, Any]:
    service_values = {
        "enabled": service["service"]["enabled"],
        "type": service["service"]["type"],
        "ports": service["service"].get(
            "ports",
            [
                {
                    "name": "http",
                    "port": service["port"],
                    "targetPort": service["containerPort"],
                }
            ],
        ),
    }
    ingress = service["ingress"]
    ingress_values = {
        "enabled": ingress["enabled"],
        "host": ingress.get("host") or f"{service['name']}.{cluster_name}.localhost",
        "className": ingress.get("className"),
        "path": ingress.get("path", "/"),
        "pathType": ingress.get("pathType", "Prefix"),
        "servicePort": ingress.get("servicePort", service["port"]),
        "annotations": ingress.get("annotations", {}),
    }
    policy = service["networkPolicy"]
    policy_values: dict[str, Any] = {"enabled": policy["enabled"]}
    if policy["enabled"]:
        policy_values["spec"] = network_policy_spec(
            service,
            policy,
            selector_labels(service["name"]),
        )
    values = {
        "image": service["image"],
        "replicas": service["replicas"],
        "containerPort": service["containerPort"],
        "env": service["env"],
        "config": service["config"],
        "service": service_values,
        "ingress": ingress_values,
        "readinessProbe": service["readinessProbe"],
        "resources": service["resources"],
        "networkPolicy": policy_values,
    }
    if service["secrets"]:
        values["existingSecret"] = service["name"]
    return values


def _application_source(
    service: dict[str, Any], repository: dict[str, Any], cluster_name: str
) -> dict[str, Any]:
    if service["type"] == "helm":
        helm = service["helm"]
        unsupported_repository_options = set(helm.get("repositoryOpts", {})) - {"repo"}
        if unsupported_repository_options:
            raise ValueError(
                f"{service['name']} uses private Helm repository options; "
                "configure that repository in Argo CD instead"
            )
        return {
            "repoURL": helm["repository"],
            "chart": helm["chart"],
            "targetRevision": helm.get("version", "*"),
            "helm": {
                "releaseName": helm.get("releaseName", service["name"]),
                "values": json.dumps(helm.get("values", {}), indent=2),
            },
        }

    return {
        "repoURL": repository["url"],
        "targetRevision": repository.get("targetRevision", "HEAD"),
        "path": _CHART_PATH,
        "helm": {
            "releaseName": service["name"],
            "values": json.dumps(_container_values(service, cluster_name), indent=2),
        },
    }


def render_registry(cluster_name: str) -> dict[str, str]:
    if not is_argocd_enabled(cluster_name):
        return {}

    cluster = CLUSTERS[cluster_name]
    repository = cluster["paas"]["argocd"]["repository"]
    rendered: dict[str, str] = {}

    for declaration in load_services(cluster_name):
        base = service_config(declaration)
        target = target_config(base["name"], base["targetClusters"][0])
        service = service_config(declaration, target["environment"], target)
        namespace = target.get(
            "namespace",
            default_namespace(service["name"], target["environment"]),
        )
        application = {
            "apiVersion": "argoproj.io/v1alpha1",
            "kind": "Application",
            "metadata": {
                "name": service["name"],
                "namespace": cluster["paas"]["argocd"].get(
                    "namespace", "argocd"
                ),
                "labels": {"app.kubernetes.io/part-of": "registry"},
            },
            "spec": {
                "project": repository.get("project", "default"),
                "source": _application_source(service, repository, cluster_name),
                "destination": {
                    "server": "https://kubernetes.default.svc",
                    "namespace": namespace,
                },
                "syncPolicy": _sync_policy(),
            },
        }
        rendered[f"{service['name']}.yaml"] = json.dumps(application, indent=2) + "\n"

    return rendered


def write_registry(cluster_name: str, check: bool = False) -> bool:
    config = CLUSTERS[cluster_name]["paas"]["argocd"]["repository"]
    destination = _ROOT / config["registryPath"]
    rendered = render_registry(cluster_name)
    existing = (
        {path.name: path.read_text() for path in destination.glob("*.yaml")}
        if destination.exists()
        else {}
    )

    if check:
        return existing == rendered

    destination.mkdir(parents=True, exist_ok=True)
    for stale_name in existing.keys() - rendered.keys():
        (destination / stale_name).unlink()
    for name, content in rendered.items():
        (destination / name).write_text(content)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Argo CD child applications")
    parser.add_argument("--cluster", default="dev")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    clusters = (
        [name for name in CLUSTERS if is_argocd_enabled(name)]
        if args.all
        else [args.cluster]
    )
    if all(write_registry(cluster, args.check) for cluster in clusters):
        return 0
    print("GitOps registry is stale; run make generate-gitops")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
