"""Shared path and bounding-box helpers for the cocoa terrain workflow."""

import json
import math
from pathlib import Path
from urllib.parse import unquote, urlparse


def parse_bbox(value: str) -> tuple[float, float, float, float]:
    """Parse and validate a west,south,east,north bounding box."""
    try:
        coordinates = tuple(float(part.strip()) for part in value.split(","))
    except ValueError as error:
        raise ValueError("bbox must contain four numeric coordinates") from error
    if len(coordinates) != 4 or not all(math.isfinite(v) for v in coordinates):
        raise ValueError("bbox must contain four finite coordinates")
    west, south, east, north = coordinates
    if not (-180 <= west < east <= 180):
        raise ValueError("bbox longitudes must satisfy -180 <= west < east <= 180")
    if not (-90 <= south < north <= 90):
        raise ValueError("bbox latitudes must satisfy -90 <= south < north <= 90")
    return coordinates


def bbox_geometry(bbox: tuple[float, float, float, float]) -> dict:
    """Return a GeoJSON polygon for a west,south,east,north bounding box."""
    west, south, east, north = bbox
    return {
        "type": "Polygon",
        "coordinates": [[
            [west, south],
            [east, south],
            [east, north],
            [west, north],
            [west, south],
        ]],
    }


def _resolve_local_href(root: Path, base_dir: Path, href: str) -> Path:
    parsed = urlparse(href)
    if parsed.scheme not in ("", "file") or parsed.netloc:
        raise ValueError(f"STAC input href must be local: {href}")
    path = Path(unquote(parsed.path if parsed.scheme else href))
    if not path.is_absolute():
        path = base_dir / path
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"STAC input href escapes its Directory: {href}")
    if not resolved.is_file():
        raise FileNotFoundError(f"STAC input file does not exist: {resolved}")
    return resolved


def catalog_dem_assets(directory: Path) -> list[Path]:
    """Resolve local GeoTIFF assets linked by a STAC Catalog Directory."""
    root = directory.resolve()
    catalog_path = root / "catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    if (
        not isinstance(catalog, dict)
        or str(catalog.get("type", "")).lower() != "catalog"
        or not isinstance(catalog.get("links"), list)
    ):
        raise ValueError("Input Directory must contain a STAC catalog.json")

    items = []
    for link in catalog["links"]:
        if link.get("rel") == "item":
            href = link.get("href")
            if not isinstance(href, str):
                raise ValueError("STAC Catalog Item links must have an href")
            items.append(_resolve_local_href(root, root, href))
    if not items:
        raise ValueError("STAC input Catalog must link to at least one Item")

    assets = set()
    for item_path in items:
        item = json.loads(item_path.read_text(encoding="utf-8"))
        if (
            not isinstance(item, dict)
            or item.get("type") != "Feature"
            or not isinstance(item.get("assets"), dict)
        ):
            raise ValueError(f"STAC Catalog entry is not a valid Item: {item_path}")
        for asset in item["assets"].values():
            href = asset.get("href") if isinstance(asset, dict) else None
            if not isinstance(href, str):
                raise ValueError(f"STAC Item asset href is missing: {item_path}")
            path = _resolve_local_href(root, item_path.parent, href)
            if path.suffix.lower() in {".tif", ".tiff"}:
                assets.add(path)

    if not assets:
        raise ValueError("STAC input Catalog contains no GeoTIFF assets")
    return sorted(assets)
