from .clusters import PLATFORM_LABELS


def selector_labels(service_name: str) -> dict[str, str]:
    return {
        "app.kubernetes.io/name": service_name,
        "app.kubernetes.io/part-of": PLATFORM_LABELS["app.kubernetes.io/part-of"],
    }


def metadata_labels(service_name: str, environment: str) -> dict[str, str]:
    return {
        **selector_labels(service_name),
        **PLATFORM_LABELS,
        "paas.openai.com/environment": environment,
    }
