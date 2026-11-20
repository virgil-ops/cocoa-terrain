#!/usr/bin/env python3
"""Compute cocoa terrain suitability from a local STAC Directory of DEM tiles."""

import argparse
import json
import math
from contextlib import ExitStack
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.merge import merge

if __package__:
    from .common import catalog_dem_assets, parse_bbox
else:
    from common import catalog_dem_assets, parse_bbox

NODATA = 255


def compute_slope_deg(elevation: np.ndarray, transform) -> np.ndarray:
    """Compute slope in degrees from a geographic-CRS elevation grid."""
    if elevation.shape[0] < 2 or elevation.shape[1] < 2:
        raise ValueError("DEM mosaic must be at least 2 by 2 pixels")
    pixel_size = abs(transform.a)
    rows = np.arange(elevation.shape[0])
    latitudes = transform.f + (rows + 0.5) * transform.e
    dx = pixel_size * 111320.0 * np.cos(np.radians(latitudes))
    dy = pixel_size * 110574.0
    dz_dx = np.gradient(elevation, axis=1) / dx[:, None]
    dz_dy = np.gradient(elevation, axis=0) / dy
    return np.degrees(np.arctan(np.hypot(dz_dx, dz_dy)))


def process_dem(
    dem_directory: Path,
    bbox: tuple[float, float, float, float],
    max_elev: float,
    max_slope: float,
    resolution: float,
    output_dir: Path,
) -> dict:
    """Read local STAC-linked DEM assets and write suitability raster and summary."""
    if not math.isfinite(max_elev) or max_elev < 0:
        raise ValueError("max-elev must be a finite non-negative value")
    if not math.isfinite(max_slope) or not 0 <= max_slope <= 90:
        raise ValueError("max-slope must be between 0 and 90 degrees")
    if not math.isfinite(resolution) or resolution <= 0:
        raise ValueError("resolution must be a finite positive value")

    assets = catalog_dem_assets(dem_directory)
    with ExitStack() as stack:
        datasets = [stack.enter_context(rasterio.open(path)) for path in assets]
        mosaic, transform = merge(
            datasets,
            bounds=bbox,
            res=resolution,
            nodata=-9999,
            resampling=Resampling.average,
        )

    elevation = mosaic[0].astype("float32")
    elevation[elevation == -9999] = np.nan
    slope = compute_slope_deg(elevation, transform)

    valid = np.isfinite(elevation) & np.isfinite(slope)
    suitability = np.full(elevation.shape, NODATA, dtype="uint8")
    suitability[valid] = (
        (elevation[valid] <= max_elev) & (slope[valid] <= max_slope)
    ).astype("uint8")

    output_dir.mkdir(parents=True, exist_ok=True)
    raster_path = output_dir / "suitability.tif"
    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        height=suitability.shape[0],
        width=suitability.shape[1],
        count=1,
        dtype="uint8",
        crs="EPSG:4326",
        transform=transform,
        nodata=NODATA,
        compress="deflate",
    ) as destination:
        destination.write(suitability, 1)

    valid_pixels = suitability[valid]
    summary = {
        "file": raster_path.name,
        "bbox": list(bbox),
        "max_elev_m": max_elev,
        "max_slope_deg": max_slope,
        "resolution_deg": resolution,
        "valid_pixel_count": int(valid_pixels.size),
        "suitable_fraction": (
            float(valid_pixels.mean()) if valid_pixels.size else None
        ),
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dem-dir", required=True)
    parser.add_argument("--bbox", required=True, help="west,south,east,north")
    parser.add_argument("--max-elev", type=float, default=800.0)
    parser.add_argument("--max-slope", type=float, default=15.0)
    parser.add_argument("--res", type=float, default=0.000833)
    parser.add_argument("--outdir", default="results")
    args = parser.parse_args()

    summary = process_dem(
        Path(args.dem_dir),
        parse_bbox(args.bbox),
        args.max_elev,
        args.max_slope,
        args.res,
        Path(args.outdir),
    )
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
