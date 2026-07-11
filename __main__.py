import pulumi

from paas_platform import deploy_service
from services import SERVICES

deployed_services = {}

for service in SERVICES:
    deployed_services[service["name"]] = deploy_service(service)

pulumi.export("services", deployed_services)
