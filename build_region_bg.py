"""
Build data/bg_region_rpz.geojson and data/acs_bg_region.json for King, Snohomish, Pierce, and Kitsap counties.
Each block group gets rpz_share = share of its area inside Seattle residential parking zones (0 outside Seattle).
"""
import json
from pathlib import Path
import geopandas as gpd

DATA = Path(__file__).parent / "data"
COUNTIES = {"033", "061", "053", "035"}  # King, Snohomish, Pierce, Kitsap

bg = gpd.read_file(DATA / "bg" / "tl_2024_53_bg.shp")
region = bg[bg.COUNTYFP.isin(COUNTIES)].to_crs(4326).copy()
rpz = gpd.read_file(DATA / "rpz.geojson").set_crs(2926, allow_override=True).to_crs(4326)
rpz_m = gpd.GeoSeries([rpz.dissolve().geometry.iloc[0]], crs=4326).to_crs(2926).iloc[0]
region_m = region.to_crs(2926)
region["rpz_share"] = [(g.intersection(rpz_m).area / g.area if g.area else 0) for g in region_m.geometry]
region[["GEOID", "rpz_share", "geometry"]].to_file(DATA / "bg_region_rpz.geojson", driver="GeoJSON")

# Merge the four ACS downloads into one file (header from the first)
header, rows = None, []
for c in ["033", "061", "053", "035"]:
    d = json.loads((DATA / f"acs_bg_{c}.json").read_text()) if c != "033" else json.loads((DATA / "acs_bg_king.json").read_text())
    header = header or d[0]
    rows += d[1:]
(DATA / "acs_bg_region.json").write_text(json.dumps([header] + rows))
print(f"{len(region)} block groups, {len(rows)} ACS rows")
