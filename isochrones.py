"""
Step 1: Generate bike and drive isochrones (20-60 min) from 333 Dexter Ave N, Seattle.

Uses the OpenRouteService (ORS) isochrones API. Requires a free key:
    export ORS_API_KEY="your-key-here"

Outputs:
    output/isochrones_bike.geojson
    output/isochrones_drive.geojson
    output/isochrones_map.html   (open in a browser)

Notes:
- Isochrones are computed outward from the point. Travel times to the point can
  differ slightly because of one-way streets. Good enough for a first pass.
"""

import json
import os
import sys
from pathlib import Path

import folium
import requests
from shapely.geometry import mapping, shape

ORS_URL = "https://api.openrouteservice.org/v2/isochrones/{profile}"
DESTINATION = {"name": "Apple Office - 333 Dexter Ave N", "lat": 47.6219275, "lon": -122.3434557}
MINUTES = [20, 30, 40, 50, 60, 70, 80, 90]
PROFILES = {"bike": "cycling-regular", "drive": "driving-car"}
OUT_DIR = Path(__file__).parent / "output"

COLORS = {20: "#1a9850", 30: "#91cf60", 40: "#fee08b", 50: "#fc8d59", 60: "#d73027",
          70: "#9970ab", 80: "#5e3c99", 90: "#2d004b"}


def band_rings(fc: dict) -> dict:
    """ORS returns nested areas (the 60-min area contains the 50-min area, and so on).
    Cut each band so it covers only its own ring: this band minus everything inside shorter bands."""
    feats = sorted(fc["features"], key=lambda f: f["properties"]["minutes"])
    out, covered = [], None
    for f in feats:
        outer = shape(f["geometry"])
        ring = outer if covered is None else outer.difference(covered)
        covered = outer if covered is None else covered.union(outer)
        out.append({**f, "geometry": mapping(ring)})
    return {"type": "FeatureCollection", "features": out}


def fetch_isochrones(api_key: str, profile: str) -> dict:
    """Return a GeoJSON FeatureCollection with one feature per time band."""
    body = {
        "locations": [[DESTINATION["lon"], DESTINATION["lat"]]],
        "range": [m * 60 for m in MINUTES],  # ORS expects seconds
        "range_type": "time",
        "attributes": ["area"],
    }
    resp = requests.post(
        ORS_URL.format(profile=profile),
        json=body,
        headers={"Authorization": api_key, "Content-Type": "application/json"},
        timeout=60,
    )
    if resp.status_code != 200:
        sys.exit(f"ORS error for {profile}: {resp.status_code} {resp.text[:300]}")
    data = resp.json()
    # Tag each feature with its minute value so the map can color it
    for feat in data["features"]:
        feat["properties"]["minutes"] = int(feat["properties"]["value"] // 60)
    return data


def iso_legend_html(legend_id: str, title: str, visible: bool = True) -> str:
    """Color key for the travel-time bands. Shown on the isochrone map; other maps toggle it with JavaScript."""
    rows = "".join(
        f'<div style="display:flex; align-items:center; margin:2px 0;">'
        f'<span style="display:inline-block; width:22px; height:12px; background:{COLORS[m]}; '
        f'border:1px solid #999; margin-right:6px;"></span>{m} min</div>'
        for m in sorted(COLORS)
    )
    display = "block" if visible else "none"
    return (
        f'<div id="{legend_id}" style="display:{display}; position:fixed; bottom:30px; right:20px; z-index:9999; '
        f'background:white; padding:10px 12px; border-radius:6px; box-shadow:0 0 6px rgba(0,0,0,.3); '
        f'font:12px Arial, sans-serif;"><b>{title}</b><div style="margin-top:6px;">{rows}</div></div>'
    )


def build_map(all_data: dict, out_path: Path) -> None:
    m = folium.Map(location=[DESTINATION["lat"], DESTINATION["lon"]], zoom_start=12, tiles=None)
    # Esri basemap: openly usable with attribution. (OSM's default tile server blocks this kind of app.)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
        attr="Tiles © Esri — Esri, HERE, Garmin, USGS, NGA, EPA, NPS",
        name="Street map",
    ).add_to(m)
    folium.Marker(
        [DESTINATION["lat"], DESTINATION["lon"]],
        tooltip=DESTINATION["name"],
        icon=folium.Icon(color="black", icon="home"),
    ).add_to(m)

    mode_layers = {}
    # Draw largest bands first so smaller bands sit on top
    for mode_label, fc in all_data.items():
        layer = folium.FeatureGroup(name=f"{mode_label.title()} isochrones", show=(mode_label == "bike"))
        for feat in sorted(fc["features"], key=lambda f: -f["properties"]["minutes"]):
            minutes = feat["properties"]["minutes"]
            folium.GeoJson(
                feat,
                style_function=lambda _, c=COLORS[minutes]: {
                    "fillColor": c, "color": c, "weight": 1, "fillOpacity": 0.55,
                },
                tooltip=f"{mode_label}: {minutes} min",
            ).add_to(layer)
        layer.add_to(m)
        mode_layers[mode_label] = layer

    folium.LayerControl(collapsed=False).add_to(m)
    m.get_root().html.add_child(folium.Element(iso_legend_html('iso_legend', 'Commute Times', visible=True)))

    # Make the mode layers mutually exclusive: turning one on turns the others off.
    # Leaflet updates the checkboxes itself when layers are added/removed on the map.
    js_names = {k: v.get_name() for k, v in mode_layers.items()}
    # Note: folium already wraps this in a <script> tag, so don't add one here.
    # Wait for window load so the map variable exists before we attach the handler.
    exclusive_js = f"""
    window.addEventListener('load', function() {{
      var map = {m.get_name()};
      var modes = {json.dumps(js_names)};
      map.on('layeradd', function(e) {{
        for (var mode in modes) {{
          var other = window[modes[mode]];
          if (other && e.layer === other) {{
            for (var m2 in modes) {{
              if (m2 !== mode) {{
                var lyr = window[modes[m2]];
                if (lyr && map.hasLayer(lyr)) {{ map.removeLayer(lyr); }}
              }}
            }}
          }}
        }}
      }});
    }});
    """
    m.get_root().script.add_child(folium.Element(exclusive_js))
    m.save(str(out_path))


def main() -> None:
    api_key = os.environ.get("ORS_API_KEY")
    key_file = Path(__file__).parent / ".ors_key"  # private local file, chmod 600, git-ignored
    if not api_key and key_file.exists():
        api_key = key_file.read_text().strip()
    if not api_key:
        sys.exit("Set ORS_API_KEY or save the key in .ors_key (free key at https://openrouteservice.org/dev/#/signup)")

    OUT_DIR.mkdir(exist_ok=True)
    all_data = {}
    for label, profile in PROFILES.items():
        print(f"Fetching {label} isochrones ({profile})...")
        fc = band_rings(fetch_isochrones(api_key, profile))
        all_data[label] = fc
        (OUT_DIR / f"isochrones_{label}.geojson").write_text(json.dumps(fc))
        areas = {f["properties"]["minutes"]: round(f["properties"]["area"] / 1e6, 1) for f in fc["features"]}
        print(f"  area (km2) by minutes: {dict(sorted(areas.items()))}")

    build_map(all_data, OUT_DIR / "isochrones_map.html")
    print(f"\nDone. Open {OUT_DIR / 'isochrones_map.html'} in a browser.")


if __name__ == "__main__":
    main()
