# Cocoa terrain suitability

The CWL workflow runs three independent CommandLineTools, each from its own
Docker image:

1. `stage-in` downloads Copernicus DEM GLO-30 tiles for `bbox` and creates a
   local STAC Catalog Directory.
2. `process` consumes that Directory without network access, computes the
   suitability raster name from the canonical input parameters, converts it to
   a COG, and writes the summary and stage-out manifest. For example, the raster
   is named `suitability-{md5}.tif`.
3. `stage-out` is the shared STAC tool. It copies declared assets without
   renaming them and uses PySTAC to create the Catalog and Items locally.

DPH handles artifact persistence, optional S3 upload, and artifact URLs after
the CWL workflow completes. Configure remote storage in DPH (`STAC_OUTPUT_MODE`,
`S3_BUCKET`, and related settings); this processor does not need S3 credentials.
The `process` and shared `stage-out` tools have no network access. All three
images run as UID 1001/GID 1000 so their files remain accessible across the
Calrissian step workspaces. The shared stage-out contract is documented in
[lib/stac_stage_out/README.md](../../stac_stage_out/README.md).
The MD5 suffix is calculated by the algorithm from canonical JSON containing
`bbox`, `max_elev`, `max_slope`, and `resolution`; DPH never changes asset names.

## Build and publish the three images

Run these commands from the repository root, replacing the image namespace if
needed:

```bash
docker build -f lib/processors/cocoa_terrain/Dockerfile.stage-in \
  -t docker.io/stormbreaker0/cocoa-terrain-stage-in:1.0.0 \
  lib/processors/cocoa_terrain
docker build -f lib/processors/cocoa_terrain/Dockerfile.process \
  -t docker.io/stormbreaker0/cocoa-terrain-process:1.0.2 \
  lib/processors/cocoa_terrain
docker build -f lib/stac_stage_out/Dockerfile \
  -t docker.io/stormbreaker0/dph-stac-stage-out:1.0.0 \
  lib/stac_stage_out

docker push docker.io/stormbreaker0/cocoa-terrain-stage-in:1.0.0
docker push docker.io/stormbreaker0/cocoa-terrain-process:1.0.2
docker push docker.io/stormbreaker0/dph-stac-stage-out:1.0.0
```

For S3 output, configure storage on DPH itself. The workflow tools need no
S3 credentials or S3 network access.

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
