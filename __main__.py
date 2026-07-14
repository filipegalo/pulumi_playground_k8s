import pulumi

from paas_platform import deploy_service
from services import load_services

deployed_services = {}

for service in load_services(pulumi.get_stack()):
    deployed_services[service["name"]] = deploy_service(service)

pulumi.export("services", deployed_services)
