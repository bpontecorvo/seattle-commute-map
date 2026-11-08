"""
Build data/zip_summary_radius.csv: Zillow home value and rent for every Washington ZIP
within RADIUS_KM of 333 Dexter Ave N. Re-run this if you change the radius.
"""
import csv, json, math
from pathlib import Path

ROOT = Path(__file__).parent / "data"
RADIUS_KM = 25                      # ~15 miles
DEST = (47.6219275, -122.3434557)   # 333 Dexter Ave N


def haversine_km(a, b):
    R = 6371.0
    la1, lo1, la2, lo2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    d = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * R * math.asin(math.sqrt(d))


def main():
    bounds = json.loads((ROOT / "wa_zip_boundaries.geojson").read_text())["features"]
    centroid = {f["properties"]["ZCTA5CE10"]: (float(f["properties"]["INTPTLAT10"]), float(f["properties"]["INTPTLON10"])) for f in bounds}

    zhvi = {r["RegionName"]: r for r in csv.DictReader(open(ROOT / "zillow_zhvi_zip.csv", newline=""))}
    zori = {r["RegionName"]: r for r in csv.DictReader(open(ROOT / "zillow_zori_zip.csv", newline=""))}
    h_last = list(next(iter(zhvi.values())).keys())[-1]
    r_last = list(next(iter(zori.values())).keys())[-1]

    rows = []
    for z, (lat, lon) in centroid.items():
        d = haversine_km(DEST, (lat, lon))
        if d > RADIUS_KM or z not in zhvi:
            continue
        zh = zhvi[z]
        rows.append({
            "zip": z,
            "city": zh["City"],
            "county": zh["CountyName"],
            "distance_km": round(d, 1),
            "zhvi_home_value_latest": zh.get(h_last, ""),
            "zori_rent_latest": zori.get(z, {}).get(r_last, ""),
        })
    rows.sort(key=lambda r: r["distance_km"])
    with open(ROOT / "zip_summary_radius.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} ZIPs within {RADIUS_KM} km; home value month {h_last}, rent month {r_last}")


if __name__ == "__main__":
    main()
