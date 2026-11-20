# Cocoa terrain suitability

The CWL workflow runs three independent CommandLineTools, each from its own
Docker image:

1. `stage-in` downloads Copernicus DEM GLO-30 tiles for `bbox` and creates a
   local STAC Catalog Directory.
2. `process` consumes that Directory without network access and creates the
   suitability raster and summary.
3. `stage-out` converts the raster to a COG, writes the result STAC Catalog and
   Item, then uploads all four files to S3. The workflow returns the Catalog's
   `s3://` URI.

DPH only orchestrates the CWL job and stores the returned URI. It does not
download the input data or upload the result files for this workflow.
All three images run as UID 1001/GID 1000 so their files remain accessible
across the Calrissian step workspaces.

## Build and publish the three images

Run these commands from the repository root, replacing the image namespace if
needed:

```bash
docker build -f lib/processors/cocoa_terrain/Dockerfile.stage-in \
  -t docker.io/stormbreaker0/cocoa-terrain-stage-in:1.0.0 \
  lib/processors/cocoa_terrain
docker build -f lib/processors/cocoa_terrain/Dockerfile.process \
  -t docker.io/stormbreaker0/cocoa-terrain-process:1.0.0 \
  lib/processors/cocoa_terrain
docker build -f lib/processors/cocoa_terrain/Dockerfile.stage-out \
  -t docker.io/stormbreaker0/cocoa-terrain-stage-out:1.0.0 \
  lib/processors/cocoa_terrain

docker push docker.io/stormbreaker0/cocoa-terrain-stage-in:1.0.0
docker push docker.io/stormbreaker0/cocoa-terrain-process:1.0.0
docker push docker.io/stormbreaker0/cocoa-terrain-stage-out:1.0.0
```

## S3 configuration

Configure `PROCESS_ENV` under the deployed process ID, `cocoa-terrain`. The
variables required by stage-out are:

- `S3_BUCKET` (required)
- `S3_PREFIX` (optional; defaults to `cocoa-terrain`)
- `S3_ENDPOINT_URL` (optional for S3-compatible services)
- `S3_REGION` (optional; defaults to `us-east-1`)
- `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`, or credentials supplied by
  the stage-out pod's AWS credential chain

For example, the DPH environment map has the shape
`{"cocoa-terrain":{"S3_BUCKET":"<bucket>","S3_PREFIX":"cocoa-terrain","AWS_ACCESS_KEY_ID":"<key>","AWS_SECRET_ACCESS_KEY":"<secret>"}}`.
See the [Kubernetes deployment guide](../../../docs/deployment/kubernetes.md#processor-secrets-without-vault)
for storing and exposing `PROCESS_ENV` as a Kubernetes Secret. The
[Secret manifest example](./process-env-secret.yaml.example) contains placeholders
only; replace them locally and do not commit real credentials.

DPH injects `PROCESS_ENV` into the Calrissian step pods; credentials are not CWL
inputs. DPH's own `S3_ACCESS_KEY_ID` and `S3_SECRET_ACCESS_KEY` settings are not
automatically forwarded to those pods. For workload identity, configure an IAM
role for the Kubernetes service account used by the step pods and set
`CWL_TOOL_SERVICE_ACCOUNT` to that service account. Each run writes to a unique
`<S3_PREFIX>/cocoa-suitability-<id>/` prefix. Ensure the stage-out pod can reach
the configured S3 endpoint and the bucket policy permits writes.

## Deploy

The [cocoa-terrain.json](./cocoa-terrain.json) file follows the DPH
Application Package deploy contract. Its `executionUnit.href` points at the
`main` branch; DPH snapshots and hashes the CWL at deploy time, so each
deployed process runs the exact snapshot it received. Redeploy after updating
the branch to pick up changes. For a private GitLab repository, configure
`CWL_FETCH_HEADERS` with the required read token.

## Validate

```bash
cwltool --validate lib/processors/cocoa_terrain/cocoa-terrain.cwl
```
