"""Download Copernicus DEM tiles and create a local STAC Catalog Directory."""

import argparse
import json
import math
import shutil
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import pystac

if __package__:
    from .common import parse_bbox
else:
    from common import parse_bbox

TILE_URL = (
    "https://copernicus-dem-30m.s3.amazonaws.com/"
    "Copernicus_DSM_COG_10_{lat}_00_{lon}_00_DEM/"
    "Copernicus_DSM_COG_10_{lat}_00_{lon}_00_DEM.tif"
)


def tile_specs(bbox: tuple[float, float, float, float]):
    """Yield tile indices and URLs for all 1-degree cells intersecting bbox."""
    west, south, east, north = bbox
    for lat in range(math.floor(south), math.ceil(north)):
        for lon in range(math.floor(west), math.ceil(east)):
            lat_tag = f"{'N' if lat >= 0 else 'S'}{abs(lat):02d}"
            lon_tag = f"{'E' if lon >= 0 else 'W'}{abs(lon):03d}"
            yield lat, lon, TILE_URL.format(lat=lat_tag, lon=lon_tag)


def download_tile(url: str, destination: Path) -> bool:
    """Download a public tile, returning False when the tile does not exist."""
    temporary = destination.with_suffix(destination.suffix + ".part")
    request = Request(url, headers={"User-Agent": "cocoa-terrain-stage-in/1.0"})
    try:
        with urlopen(request, timeout=180) as response, temporary.open("wb") as output:
            shutil.copyfileobj(response, output)
        temporary.replace(destination)
        return True
    except HTTPError as error:
        temporary.unlink(missing_ok=True)
        if error.code == 404:
            return False
        raise RuntimeError(
            f"Could not download DEM tile {url}: HTTP {error.code}"
        ) from error
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def stage_tiles(
    bbox: tuple[float, float, float, float],
    output_dir: Path,
    downloader=download_tile,
) -> list[Path]:
    """Download bbox DEM tiles and write a self-contained STAC Catalog."""
    output_dir.mkdir(parents=True, exist_ok=True)
    assets_dir = output_dir / "assets"
    items_dir = output_dir / "items"
    assets_dir.mkdir(exist_ok=True)
    items_dir.mkdir(exist_ok=True)

    catalog = pystac.Catalog(
        id="copernicus-dem-input",
        description="Locally staged Copernicus DEM GLO-30 tiles.",
    )
    downloaded = []
    for lat, lon, url in tile_specs(bbox):
        filename = Path(urlparse(url).path).name
        asset_path = assets_dir / filename
        if not downloader(url, asset_path):
            continue

        tile_bbox = [lon, lat, lon + 1, lat + 1]
        item_id = Path(filename).stem
        item = pystac.Item(
            id=item_id,
            geometry={
                "type": "Polygon",
                "coordinates": [
                    [
                        [tile_bbox[0], tile_bbox[1]],
                        [tile_bbox[2], tile_bbox[1]],
                        [tile_bbox[2], tile_bbox[3]],
                        [tile_bbox[0], tile_bbox[3]],
                        [tile_bbox[0], tile_bbox[1]],
                    ]
                ],
            },
            bbox=tile_bbox,
            datetime=None,
            properties={
                "start_datetime": None,
                "end_datetime": None,
                "platform": "copernicus-dem",
                "gsd": 30,
            },
            stac_extensions=[
                "https://stac-extensions.github.io/temporal/v1.1.0/schema.json"
            ],
        )
        item.set_self_href(str(items_dir / f"{item_id}.json"))
        item.add_asset(
            "data",
            pystac.Asset(
                href=f"../assets/{filename}",
                media_type="image/tiff; application=geotiff; profile=cloud-optimized",
                roles=["data"],
                title="Copernicus DEM GLO-30",
            ),
        )
        catalog.add_item(item)
        downloaded.append(asset_path)

    if not downloaded:
        raise RuntimeError("No Copernicus DEM tiles were found for the requested bbox")

    catalog.set_self_href(str(output_dir / "catalog.json"))
    catalog.save(catalog_type=pystac.CatalogType.SELF_CONTAINED)
    return downloaded


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bbox", required=True, help="west,south,east,north")
    parser.add_argument("--outdir", default="staged")
    args = parser.parse_args()

    paths = stage_tiles(parse_bbox(args.bbox), Path(args.outdir))
    print(json.dumps({"catalog": str(Path(args.outdir) / "catalog.json"), "tiles": len(paths)}))


if __name__ == "__main__":
    main()
