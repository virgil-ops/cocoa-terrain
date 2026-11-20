"""Create a STAC COG output and upload it to the configured object store."""

import argparse
import mimetypes
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

import boto3
import pystac
import rasterio.shutil

if __package__:
    from .common import bbox_geometry, parse_bbox
else:
    from common import bbox_geometry, parse_bbox


def stage_out(
    results_dir: Path,
    bbox: tuple[float, float, float, float],
    max_elev: float,
    max_slope: float,
    resolution: float,
    output_dir: Path,
) -> str:
    """Convert the raster to COG, write STAC metadata, and upload all outputs."""
    source_raster = results_dir / "suitability.tif"
    summary_source = results_dir / "summary.json"
    if not source_raster.is_file() or not summary_source.is_file():
        raise FileNotFoundError(
            "Processing Directory must contain suitability.tif and summary.json"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    raster_name = "suitability.tif"
    rasterio.shutil.copy(
        source_raster,
        output_dir / raster_name,
        driver="COG",
        compress="DEFLATE",
        overview_resampling="NEAREST",
    )
    shutil.copy2(summary_source, output_dir / "summary.json")

    item_id = f"cocoa-suitability-{uuid.uuid4().hex}"
    item = pystac.Item(
        id=item_id,
        geometry=bbox_geometry(bbox),
        bbox=list(bbox),
        datetime=datetime.now(timezone.utc),
        properties={
            "max_elev_m": max_elev,
            "max_slope_deg": max_slope,
            "resolution_deg": resolution,
            "title": "Cocoa terrain suitability",
        },
    )
    item.set_self_href(str(output_dir / "item.json"))
    item.add_asset(
        "suitability",
        pystac.Asset(
            href=raster_name,
            media_type="image/tiff; application=geotiff; profile=cloud-optimized",
            roles=["data"],
            title="Cocoa terrain suitability mask",
        ),
    )
    item.add_asset(
        "summary",
        pystac.Asset(
            href="summary.json",
            media_type="application/json",
            roles=["metadata"],
            title="Processing summary",
        ),
    )
    catalog = pystac.Catalog(
        id=item_id,
        description="Cocoa terrain suitability results.",
    )
    catalog.add_item(item)
    catalog.set_self_href(str(output_dir / "catalog.json"))
    catalog.save(catalog_type=pystac.CatalogType.SELF_CONTAINED)

    bucket = os.environ.get("S3_BUCKET")
    if not bucket:
        raise RuntimeError("S3_BUCKET must be set for stage-out")
    base_prefix = os.environ.get("S3_PREFIX", "cocoa-terrain").strip("/")
    prefix_parts = [part for part in base_prefix.split("/") if part]
    if any(part in {".", ".."} for part in prefix_parts):
        raise ValueError("S3_PREFIX must not contain '.' or '..' path components")
    prefix = "/".join([*prefix_parts, item_id])
    client = boto3.client(
        "s3",
        endpoint_url=os.environ.get("S3_ENDPOINT_URL") or None,
        region_name=os.environ.get("S3_REGION", "us-east-1"),
    )
    uploaded_keys = []
    try:
        for path in sorted(output_dir.iterdir()):
            if not path.is_file():
                continue
            key = f"{prefix}/{path.name}" if prefix else path.name
            content_type = mimetypes.guess_type(path.name)[0]
            extra_args = {"ContentType": content_type} if content_type else {}
            client.upload_file(
                str(path),
                bucket,
                key,
                ExtraArgs=extra_args,
            )
            uploaded_keys.append(key)
    except Exception as upload_error:
        if uploaded_keys:
            try:
                response = client.delete_objects(
                    Bucket=bucket,
                    Delete={
                        "Objects": [{"Key": key} for key in uploaded_keys],
                        "Quiet": True,
                    },
                )
                if response.get("Errors"):
                    raise RuntimeError("S3 reported errors while removing partial output")
            except Exception as cleanup_error:
                raise RuntimeError(
                    "S3 stage-out failed and partial output cleanup failed: "
                    f"{cleanup_error}"
                ) from upload_error
        raise
    return f"s3://{bucket}/{prefix}/catalog.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", required=True)
    parser.add_argument("--bbox", required=True, help="west,south,east,north")
    parser.add_argument("--max-elev", type=float, default=800.0)
    parser.add_argument("--max-slope", type=float, default=15.0)
    parser.add_argument("--res", type=float, default=0.000833)
    parser.add_argument("--outdir", default="stage-out")
    args = parser.parse_args()

    catalog_uri = stage_out(
        Path(args.results_dir),
        parse_bbox(args.bbox),
        args.max_elev,
        args.max_slope,
        args.res,
        Path(args.outdir),
    )
    print(catalog_uri)


if __name__ == "__main__":
    main()
