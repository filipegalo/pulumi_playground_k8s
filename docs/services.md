# Service configuration

Use this guide to define container or Helm workloads, select target clusters, and configure runtime behavior.

## Current examples

| Directory | Effective deployment | Demonstrates |
| --- | --- | --- |
| `services/nginx/` | `dev` and `staging` | Secrets, environment overlays, and deny-all ingress NetworkPolicy |
| `services/api/` | `dev` only | Custom ports, ConfigMap values, replicas, and Traefik Ingress |
| `services/worker/` | Nowhere; no overlay | Deployment-only template with Service and readiness disabled |
| `services/litmus/` | Nowhere; no overlay | Dormant external Helm chart template named `chaos` |

`service.json` alone is a reusable declaration. A service is loaded only when `services/<directory>/<stack>.json` exists.

## Resolution and merge behavior

Configuration resolves in this order:

```text
platform defaults < environment defaults < service.json < cluster overlay
```

- Nested mappings deep-merge.
- Lists replace the earlier list.
- Scalars replace the earlier scalar.
- The namespace defaults to the service name.
- A cluster overlay may override only the fields allowed in `TARGET_SERVICE_OVERRIDE_KEYS`.

Example: overriding only the memory limit preserves the other resource defaults:

```json
{
  "resources": {
    "limits": {
      "memory": "256Mi"
    }
  }
}
```

Replacing a port list requires the complete desired list:

```json
{
  "service": {
    "ports": [
      {
        "name": "http",
        "port": 8080,
        "targetPort": 80
      }
    ]
  }
}
```

## Default values

| Field | Base/dev | Staging |
| --- | --- | --- |
| `type` | `container` | `container` |
| `port` | `80` | `80` |
| `containerPort` | `port` | `port` |
| `replicas` | `1` | `2` |
| `service.enabled` | `true` | `true` |
| `service.type` | `ClusterIP` | `ClusterIP` |
| `ingress.enabled` | `false` | `false` |
| `readinessProbe.enabled` | `true` | `true` |
| `networkPolicy.enabled` | `false` | `false` |
| CPU request/limit | `25m` / `100m` | `50m` / `250m` |
| Memory request/limit | `32Mi` / `128Mi` | `64Mi` / `256Mi` |

## Basic container service

```json
{
  "name": "orders",
  "image": "ghcr.io/example/orders:1.0.0",
  "port": 8080,
  "containerPort": 8080,
  "replicas": 2,
  "env": {
    "LOG_FORMAT": "json"
  }
}
```

### Basic fields

| Field | Purpose |
| --- | --- |
| `name` | Kubernetes resource, Helm release, namespace default, Pulumi config namespace, and child Application name prefix |
| `type` | `container` by default; set `helm` for an external chart |
| `image` | Container image for a container service |
| `port` | Default Kubernetes Service and policy port |
| `containerPort` | Container port; defaults to `port` |
| `replicas` | Deployment replica count |
| `env` | Literal environment variables committed to Git |

Use unique, Kubernetes-compatible service names. The repository does not perform a separate uniqueness or naming validation pass.

## Cluster overlays

For example, `services/orders/dev.json` can contain:

```json
{
  "replicas": 1,
  "env": {
    "APP_ENV": "dev"
  }
}
```

Supported service-value overrides are:

- `type`
- `image`
- `port`
- `containerPort`
- `replicas`
- `env`
- `config`
- `secrets`
- `service`
- `ingress`
- `readinessProbe`
- `resources`
- `networkPolicy`
- `helm`

Target metadata such as `namespace` is read separately by the deployment/generator logic.

### Target metadata

| Field | Mode | Behavior |
| --- | --- | --- |
| `namespace` | Direct and GitOps | Overrides the default service-name namespace |
| `enabled` | Direct only | Skips a direct-Pulumi target when false; GitOps ignores it |
| `resourceNames` | Direct/Pulumi prerequisites | Overrides Pulumi logical resource names for migrations/import compatibility |

Supported `resourceNames` keys are `provider`, `namespace`, `deployment`, `configMap`, `secret`, `service`, `ingress`, `networkPolicy`, and `helmRelease`. This is a platform migration mechanism; application teams normally should not set it. Cluster routing fields such as `context` and `environment` belong in `paas_platform/clusters.py`, not service overlays.

For GitOps, overlay presence is the supported enable/disable mechanism. An overlay containing `"enabled": false` is still generated; remove the overlay instead.

## Kubernetes Service

The default is one `ClusterIP` Service port named `http`, using `port` and `containerPort`:

```json
{
  "service": {
    "enabled": true,
    "type": "ClusterIP"
  }
}
```

Custom ports:

```json
{
  "service": {
    "ports": [
      {
        "name": "http",
        "port": 8080,
        "targetPort": 8000
      },
      {
        "name": "metrics",
        "port": 9090,
        "targetPort": 9090
      }
    ]
  }
}
```

Deployment-only worker:

```json
{
  "service": {
    "enabled": false
  },
  "readinessProbe": {
    "enabled": false
  }
}
```

Ingress requires the Kubernetes Service. Direct-Pulumi mode raises an error if ingress is enabled while the Service is disabled. The current GitOps generator does not reject that combination, so keep the same invariant in declarations.

## Ingress

```json
{
  "ingress": {
    "enabled": true,
    "host": "orders.localhost",
    "className": "traefik",
    "path": "/",
    "pathType": "Prefix",
    "servicePort": 8080,
    "annotations": {}
  }
}
```

| Field | Default | Purpose |
| --- | --- | --- |
| `enabled` | `false` | Create an Ingress |
| `host` | `<service>.<cluster>.localhost` | HTTP host rule |
| `className` | unset | Select an IngressClass/controller |
| `path` | `/` | URL path |
| `pathType` | `Prefix` | Kubernetes path matching behavior |
| `servicePort` | service `port` | Backend Service port |
| `annotations` | `{}` | Controller-specific metadata |

The checked-in API explicitly selects Traefik. Other applications must set `className: traefik` themselves when they should use the platform controller.

The convenience schema does not currently model TLS blocks, certificates, or external DNS.

## Readiness probe

```json
{
  "readinessProbe": {
    "enabled": true,
    "path": "/healthz",
    "initialDelaySeconds": 5,
    "periodSeconds": 10
  }
}
```

The probe is HTTP-only and uses `containerPort`. Disable it for workers or applications that do not serve HTTP.

## Resources

```json
{
  "resources": {
    "requests": {
      "cpu": "50m",
      "memory": "64Mi"
    },
    "limits": {
      "cpu": "250m",
      "memory": "256Mi"
    }
  }
}
```

Nested resource mappings deep-merge with environment defaults.

## Environment variables

`env` creates container environment variables:

```json
{
  "env": {
    "APP_ENV": "dev",
    "LOG_FORMAT": "json"
  }
}
```

In direct-Pulumi mode they are emitted as literal container `env` entries. In GitOps mode the shared chart stores them in `<service>-env` and attaches that ConfigMap through `envFrom`. In both cases the values are committed to Git. Never put credentials in `env`.

## ConfigMap-backed configuration

`config` creates a ConfigMap and attaches it through `envFrom`:

```json
{
  "config": {
    "LOG_LEVEL": "info",
    "FEATURE_FLAG": "enabled"
  }
}
```

The chart creates `<service>-env` for literal `env` values and `<service>` for `config` values. Treat both as public repository content.

## Secret-backed configuration

Declare names only:

```json
{
  "secrets": [
    "DATABASE_URL",
    "API_TOKEN"
  ]
}
```

Pulumi reads values from configuration keys such as `orders:DATABASE_URL`, creates a Kubernetes Secret named `orders`, and the GitOps chart attaches it through `envFrom`.

For container services and GitOps prerequisites, every declared key is required before `make up STACK=<cluster>` succeeds. See [Secrets and credentials](secrets.md).

This generic attachment applies to container services. In GitOps mode, a Helm service can cause Pulumi to create the prerequisite Secret, but the external chart consumes it only if its `helm.values` explicitly reference that existing Secret. In direct-Pulumi Helm mode, the generic service Secret path is not created because Helm deployment returns before the container resource builders; manage the chart's secret requirements through its supported values or a dedicated PaaS/platform integration.

## NetworkPolicy

### Enable deny-all ingress

```json
{
  "networkPolicy": {
    "enabled": true
  }
}
```

With no allowed ingress peers, enabling the default policy emits an empty ingress rule list and denies all ingress to the selected pods. Egress remains unrestricted because `allowExternal` defaults to true.

### Allow the same namespace

```json
{
  "networkPolicy": {
    "enabled": true,
    "ingress": {
      "fromSameNamespace": true
    }
  }
}
```

### Allow namespaces or service-labelled pods

```json
{
  "networkPolicy": {
    "enabled": true,
    "ingress": {
      "fromNamespaces": ["traefik"],
      "fromServices": ["frontend"],
      "ports": [
        {
          "protocol": "TCP",
          "port": 8080
        }
      ]
    }
  }
}
```

Important selector behavior:

- `fromNamespaces` selects every pod in the named namespace.
- `fromServices` selects matching pods in the policy's own namespace because no namespace selector is combined with it.
- To expose a protected app through Traefik, allow the `traefik` namespace and the application port.
- NetworkPolicy ports are pod destination ports. The implementation defaults ingress policy ports to service `port`; when `port` differs from `containerPort`, configure the policy port explicitly.

### Restrict egress

```json
{
  "networkPolicy": {
    "enabled": true,
    "egress": {
      "allowExternal": false,
      "toNamespaces": ["data"],
      "toServices": ["database"],
      "ports": [
        {
          "protocol": "TCP",
          "port": 5432
        }
      ]
    }
  }
}
```

When `allowExternal` is true, the platform emits no Egress policy and any configured egress peers are ignored. When false with no peers, it emits deny-all egress. Restricted egress may block cluster DNS unless DNS is explicitly allowed by an appropriate policy design.

Like `fromServices`, `toServices` uses only a pod selector and therefore selects matching pods in the policy's own namespace. `toNamespaces` selects all pods in each named namespace; the current schema cannot combine a namespace selector and service pod selector into one peer.

## Helm chart service

```json
{
  "name": "metrics",
  "type": "helm",
  "helm": {
    "chart": "example-chart",
    "repository": "https://charts.example.com",
    "releaseName": "metrics",
    "version": "1.2.3",
    "values": {
      "replicaCount": 1
    }
  }
}
```

The overlay can set a namespace and deep-merge `helm.values`:

```json
{
  "namespace": "metrics",
  "helm": {
    "values": {
      "service": {
        "type": "ClusterIP"
      }
    }
  }
}
```

### Direct-Pulumi Helm options

Direct mode supports the release fields accepted by `HELM_RELEASE_OPTION_KEYS`, including:

- `allowNullValues`
- `atomic`
- `cleanupOnFail`
- `compat`
- `createNamespace`
- `dependencyUpdate`
- `description`
- `devel`
- `disableCrdHooks`
- `disableOpenapiValidation`
- `disableWebhooks`
- `forceUpdate`
- `keyring`
- `lint`
- `maxHistory`
- `postrender`
- `recreatePods`
- `renderSubchartNotes`
- `replace`
- `resetValues`
- `resourceNames`
- `reuseValues`
- `skipAwait`
- `skipCrds`
- `takeOwnership`
- `timeout`
- `valueYamlFiles`
- `verify`
- `version`
- `waitForJobs`

The implementation also accepts `repository`, `repo`, and `repositoryOpts` to build Helm repository options.

### GitOps Helm limitations

The GitOps generator carries only chart, repository, version, release name, and values. Other Pulumi release flags do not affect the child Application. Credential-like `repositoryOpts` are rejected; configure a private Helm repository in Argo CD separately.

## Unsupported convenience features

The current service schema does not provide first-class support for:

- Ingress TLS/certificate management;
- external DNS;
- image builds or pushes;
- private image `imagePullSecrets`;
- persistent volume convenience fields;
- multiple containers or init containers;
- command/args overrides;
- liveness or startup probes;
- PodDisruptionBudgets;
- autoscaling;
- service dependency ordering or Argo sync waves.

These can be added as platform features with tests and matching direct/GitOps implementations. See [Contributing](contributing.md).

## Related documentation

- [GitOps workflow](gitops.md)
- [PaaS components](paas.md)
- [Secrets and credentials](secrets.md)
- [Troubleshooting](troubleshooting.md)
