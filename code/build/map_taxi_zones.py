# ============================================================
# Script: map_taxi_zones.py
# Purpose: Verify the TLC taxi zone shapefile (CRS, LocationID range, zone
#          count, geometry validity) and produce a reference map of the
#          263 zones colored by borough.
# Inputs: raw_data/taxi_zones/taxi_zones_shp/taxi_zones/taxi_zones.shp
#         raw_data/taxi_zones/taxi_zone_lookup.csv
# Outputs: output/fig/taxi_zones_map.png
# Author: EK  Date: 2026-07-30
# ============================================================

from pathlib import Path
import geopandas as gpd
import matplotlib.pyplot as plt

project_root = Path(__file__).resolve().parents[2]
shp_path = project_root / "raw_data" / "taxi_zones" / "taxi_zones_shp" / "taxi_zones" / "taxi_zones.shp"
lookup_path = project_root / "raw_data" / "taxi_zones" / "taxi_zone_lookup.csv"
out_path = project_root / "output" / "fig" / "taxi_zones_map.png"

gdf = gpd.read_file(shp_path)

# TLC taxi zone shapefile ships in EPSG:2263 (NY State Plane Long Island, ft) —
# reproject explicitly per project CRS convention, never assume 4326.
print(f"Shapefile CRS: {gdf.crs}")
assert gdf.crs is not None and gdf.crs.to_epsg() == 2263, "unexpected source CRS"

n_zones = len(gdf)
loc_id_range = (gdf["LocationID"].min(), gdf["LocationID"].max())
n_dup = gdf["LocationID"].duplicated().sum()
n_null_geom = gdf.geometry.isna().sum()
n_invalid_geom = (~gdf.geometry.is_valid).sum()

print(f"N zones: {n_zones}")
print(f"LocationID range: {loc_id_range[0]}-{loc_id_range[1]}")
print(f"Duplicate LocationIDs: {n_dup}")
print(f"Null geometries: {n_null_geom}")
print(f"Invalid geometries: {n_invalid_geom}")

assert n_zones == 263, f"expected 263 zones, got {n_zones}"
assert n_dup == 0, "duplicate LocationIDs present"
assert n_null_geom == 0, "null geometries present"
assert n_invalid_geom == 0, "invalid geometries present"

# HVFHV PULocationID/DOLocationID use the same 1-263 zone IDs (264/265 are
# N/A and "Outside of NYC" placeholders in the lookup CSV, not real polygons —
# confirmed by lookup_path having 265 rows against the shapefile's 263).
lookup = gpd.pd.read_csv(lookup_path)
print(f"Lookup CSV rows: {len(lookup)} (includes non-geometry IDs 264/265)")

# Borough coloring — reproject to EPSG:4326 (WGS84) for the reference map,
# consistent with the project's storage/display CRS convention.
gdf_wgs84 = gdf.to_crs(epsg=4326)

fig, ax = plt.subplots(figsize=(10, 10))
gdf_wgs84.plot(
    column="borough",
    categorical=True,
    legend=True,
    edgecolor="white",
    linewidth=0.3,
    ax=ax,
    legend_kwds={"loc": "upper left", "title": "Borough"},
)
ax.set_title(f"NYC TLC Taxi Zones (n={n_zones})")
ax.set_axis_off()
fig.tight_layout()

out_path.parent.mkdir(parents=True, exist_ok=True)
if out_path.exists():
    print(f"WARNING: {out_path} already exists — overwriting")
fig.savefig(out_path, dpi=200)
print(f"Saved map to {out_path}")
