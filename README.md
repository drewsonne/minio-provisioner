# minio-provisioner

A lightweight Kubernetes operator that provisions MinIO buckets and users declaratively via CRDs.

Applications can request their own MinIO bucket and credentials without manual MinIO console access.

---

## What it does

The operator manages two CRD kinds:

| Kind | What it provisions |
| --- | --- |
| `MinioBucket` | A MinIO bucket with optional versioning |
| `MinioUser` | A MinIO user with a built-in policy, credentials stored in a K8s Secret |

All resources are reconciled continuously — the operator detects and repairs out-of-band drift every 5 minutes.

---

## Installation

Add the Helm repository:

```bash
helm repo add minio-provisioner https://drewsonne.github.io/minio-provisioner
helm repo update
```

Install the chart:

```bash
helm install minio-provisioner minio-provisioner/minio-provisioner \
  --namespace minio \
  --set minio.endpoint=minio.minio.svc.cluster.local:9000 \
  --set minio.credentialsSecret.name=minio \
  --set minio.credentialsSecret.namespace=minio
```

---

## Requirements

* A running MinIO instance accessible from within the cluster
* A Kubernetes Secret containing MinIO root credentials:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: minio
  namespace: minio
stringData:
  rootUser: <admin-access-key>
  rootPassword: <admin-secret-key>
```

This is the secret that the official MinIO Helm chart creates automatically.

---

## Configuration

Default values:

```yaml
image:
  repository: drewsonne/minio-provisioner
  tag: latest

minio:
  endpoint: minio.minio.svc.cluster.local:9000
  secure: false
  credentialsSecret:
    name: minio
    namespace: minio

namespace: minio
```

---

## Usage

### MinioBucket

Creates a MinIO bucket. The bucket name is taken from `metadata.name`.

```yaml
apiVersion: minio.sonne.zone/v1
kind: MinioBucket
metadata:
  name: dagster-io
  namespace: minio
spec:
  versioning: false
```

**Deletion safety**: Deleting a `MinioBucket` CR removes the Kubernetes resource but intentionally does **not** delete the MinIO bucket or its data, preventing accidental data loss.

### MinioUser

Creates a MinIO user with the named built-in policy. The access key is taken from `metadata.name`.

```yaml
apiVersion: minio.sonne.zone/v1
kind: MinioUser
metadata:
  name: dagster
  namespace: minio
spec:
  policy: readwrite
  secretName: dagster-minio-credentials
  secretNamespace: dagster       # optional; defaults to CR namespace
```

`policy` values:

| Value | Access |
| --- | --- |
| `readwrite` | Read and write to all buckets |
| `readonly` | Read from all buckets |
| `writeonly` | Write to all buckets |
| `diagnostics` | Read-only diagnostic/metrics access |
| `consoleAdmin` | Full MinIO console administration |

---

## Output

`MinioUser` creates a Secret containing:

* `access_key` — the MinIO access key (same as the CR name)
* `secret_key` — the randomly generated secret key
* `endpoint` — the MinIO endpoint URL (e.g. `http://minio.minio.svc.cluster.local:9000`)

```bash
kubectl get secret dagster-minio-credentials -n dagster -o yaml
```

Use these as `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` environment variables for S3-compatible clients:

```yaml
env:
  - name: AWS_ACCESS_KEY_ID
    valueFrom:
      secretKeyRef:
        name: dagster-minio-credentials
        key: access_key
  - name: AWS_SECRET_ACCESS_KEY
    valueFrom:
      secretKeyRef:
        name: dagster-minio-credentials
        key: secret_key
```

---

## Behaviour notes

* **Idempotent** — safe to reapply; existing MinIO resources are updated, not recreated
* **Secret preservation** — if a Secret already exists, the `secret_key` is preserved rather than regenerated; user credentials are not rotated on every reconcile
* **Bucket safety** — deleting a `MinioBucket` CR preserves the MinIO bucket and its data
* **User deletion** — deleting a `MinioUser` CR removes the MinIO user and the K8s Secret
* **Drift detection** — a timer runs every 5 minutes to detect and repair out-of-band changes (e.g. manually deleted users or buckets); drift is visible in `kubectl describe` as a K8s Warning event and in the `Drift` printer column

---

## Observability

```bash
kubectl get miniobuckets
kubectl get miniousers
```

Printer columns include `Ready`, `Drift`, and `Age`. Drift events are also emitted as Kubernetes Warning events visible via `kubectl describe`.

---

## Development

Build locally:

```bash
docker build -t drewsonne/minio-provisioner:dev .
```

Run locally (requires cluster access and MinIO reachable):

```bash
docker run --rm \
  -e MINIO_ENDPOINT=minio.minio.svc.cluster.local:9000 \
  -e MINIO_ACCESS_KEY=minioadmin \
  -e MINIO_SECRET_KEY=minioadmin \
  -e MINIO_SECURE=false \
  drewsonne/minio-provisioner:dev
```

---

## License

MIT
