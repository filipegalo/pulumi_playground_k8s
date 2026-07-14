import json
from pathlib import Path
from typing import Any

_SERVICES_DIR = Path(__file__).parent


def _read_json(path: Path) -> dict[str, Any]:
    with path.open() as file:
        return json.load(file)


def load_services(stack: str) -> list[dict[str, Any]]:
    services: list[dict[str, Any]] = []
    for service_path in sorted(_SERVICES_DIR.glob("*/service.json")):
        target_path = service_path.with_name(f"{stack}.json")
        if not target_path.exists():
            continue

        service = _read_json(service_path)
        target = _read_json(target_path)
        services.append(
            {
                **service,
                "targetClusters": [
                    {
                        "name": stack,
                        **target,
                    }
                ],
            }
        )
    return services
