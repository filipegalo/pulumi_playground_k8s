import json
from pathlib import Path
from typing import Any

_SERVICES_DIR = Path(__file__).parent


def _load_services() -> list[dict[str, Any]]:
    services: list[dict[str, Any]] = []
    for path in sorted(_SERVICES_DIR.glob("*/service.json")):
        with path.open() as file:
            services.append(json.load(file))
    return services


SERVICES = _load_services()
