import pulumi

from paas import load_paas_services
from paas.argocd import deploy_argocd, is_argocd_enabled
from paas.gitops import deploy_gitops_prerequisites
from paas_platform import deploy_service
from services import load_services

deployed_paas = {}
deployed_services = {}

for service in load_paas_services(pulumi.get_stack()):
    if service["name"] == "argocd":
        deployed_paas[service["name"]] = deploy_argocd(pulumi.get_stack())

services = load_services(pulumi.get_stack())
if is_argocd_enabled(pulumi.get_stack()):
    deployed_paas["servicePrerequisites"] = deploy_gitops_prerequisites(services)
else:
    for service in services:
        deployed_services[service["name"]] = deploy_service(service)

pulumi.export("paas", deployed_paas)
pulumi.export("services", deployed_services)
