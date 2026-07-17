import pulumi

from paas_platform import deploy_service
from paas import load_paas_services
from services import load_services

deployed_paas = {}
deployed_services = {}

for service in load_paas_services(pulumi.get_stack()):
    deployed_paas[service["name"]] = deploy_service(service)

for service in load_services(pulumi.get_stack()):
    deployed_services[service["name"]] = deploy_service(service)

pulumi.export("paas", deployed_paas)
pulumi.export("services", deployed_services)
