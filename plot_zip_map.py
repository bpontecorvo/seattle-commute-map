"""
Step 3 map: Seattle ZIP-level home values and rents (Zillow), plus commute isochrones.

Inputs (already created):
    data/zip_summary_radius.csv        built by build_zip_summary.py (ZIPs within 25 km)
    data/wa_zip_boundaries.geojson     Washington ZIP (ZCTA) boundaries
    output/isochrones_bike.geojson     from isochrones.py
    output/isochrones_drive.geojson    from isochrones.py

Output:
    output/zip_real_estate_map.html

Layers:
    - Home value (choose one): exclusive, turning one on turns the other off
    - Rent (choose one): exclusive with the above too, so only one choropleth shows at a time
    - Commute isochrones (bike, drive): independent checkboxes, off by default
"""

import csv
import json
from pathlib import Path

import branca.colormap as cm
import folium

ROOT = Path(__file__).parent
SUMMARY = ROOT / "data" / "zip_summary_radius.csv"  # built by build_zip_summary.py
BOUNDARIES = ROOT / "data" / "wa_zip_boundaries.geojson"
OUT = ROOT / "output" / "zip_real_estate_map.html"
DESTINATION = [47.6219275, -122.3434557]  # 333 Dexter Ave N

# Metric key -> (summary column, layer label, colormap, formatter)
METRICS = {
    "home": ("zhvi_home_value_latest", "Typical home value", ["#ffffb2", "#fecc5c", "#fd8d3c", "#e31a1c"], "${:,.0f}"),
    "rent": ("zori_rent_latest", "Typical monthly rent", ["#f7fbff", "#9ecae1", "#4292c6", "#08306b"], "${:,.0f}/mo"),
}


def load_summary() -> dict:
    rows = {}
    with open(SUMMARY, newline="") as f:
        for r in csv.DictReader(f):
            rows[r["zip"]] = r
    return rows


def build_choropleth_layer(name: str, column: str, colors: list, fmt: str, boundaries: dict, rows: dict, show: bool):
    values = {z: float(r[column]) for z, r in rows.items() if r.get(column)}
    # Stretch colors across the 10th–90th percentile so a few extreme ZIPs (e.g. Medina)
    # don't wash out the rest. Values beyond those cutoffs get the end colors.
    ordered = sorted(values.values())
    lo = ordered[int(0.10 * (len(ordered) - 1))]
    hi = ordered[int(0.90 * (len(ordered) - 1))]
    cmap = cm.LinearColormap(colors, vmin=lo, vmax=hi, caption=name)

    group = folium.FeatureGroup(name=name, show=show)
    for feat in boundaries["features"]:
        z = feat["properties"]["ZCTA5CE10"]
        if z not in values:
            continue
        v = values[z]
        fill = cmap(min(max(v, lo), hi))  # clamp outliers to the end colors
        tip = f"ZIP {z} ({rows[z]['city']}): {fmt.format(v)}"
        folium.GeoJson(
            feat,
            style_function=lambda _, c=fill: {"fillColor": c, "color": "#333", "weight": 1, "fillOpacity": 0.7},
            highlight_function=lambda _: {"weight": 3, "color": "#000"},
            tooltip=tip,
        ).add_to(group)
    return group, cmap


def build_isochrone_layer(path: Path, label: str, colors: dict, show: bool):
    fc = json.loads(path.read_text())
    group = folium.FeatureGroup(name=label, show=show)
    for feat in sorted(fc["features"], key=lambda f: -f["properties"]["minutes"]):
        m = feat["properties"]["minutes"]
        folium.GeoJson(
            feat,
            style_function=lambda _, c=colors[m]: {"fillColor": c, "color": c, "weight": 1, "fillOpacity": 0.55},
            tooltip=f"{label}: {m} min",
        ).add_to(group)
    return group



def iso_legend_html(legend_id: str, title: str) -> str:
    """Color key for the travel-time bands (bottom-right, so it doesn't overlap the value legends)."""
    rows = "".join(
        f'<div style="display:flex; align-items:center; margin:2px 0;">'
        f'<span style="display:inline-block; width:22px; height:12px; background:{ISO_COLORS[m]}; '
        f'border:1px solid #999; margin-right:6px;"></span>{m} min</div>'
        for m in sorted(ISO_COLORS)
    )
    return (
        f'<div id="{legend_id}" style="display:block; position:fixed; bottom:30px; right:20px; z-index:9999; '
        f'background:white; padding:10px 12px; border-radius:6px; box-shadow:0 0 6px rgba(0,0,0,.3); '
        f'font:12px Arial, sans-serif;"><b>{title}</b><div style="margin-top:6px;">{rows}</div></div>'
    )

ISO_COLORS = {20: "#1a9850", 30: "#91cf60", 40: "#fee08b", 50: "#fc8d59", 60: "#d73027", 70: "#9970ab", 80: "#5e3c99", 90: "#2d004b"}

def main() -> None:
    rows = load_summary()
    boundaries = json.loads(BOUNDARIES.read_text())
    # Only keep Seattle ZIPs that have data
    boundaries["features"] = [f for f in boundaries["features"] if f["properties"]["ZCTA5CE10"] in rows]

    m = folium.Map(location=DESTINATION, zoom_start=11, tiles=None)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
        attr="Tiles © Esri — Esri, HERE, Garmin, USGS, NGA, EPA, NPS",
        name="Street map",
    ).add_to(m)
    folium.Marker(DESTINATION, tooltip=folium.Tooltip("Apple Office - 333 Dexter Ave N", permanent=True), icon=folium.Icon(color="black", icon="briefcase")).add_to(m)

    # Exclusive choropleth layers (home value / rent)
    choro_groups = {}
    for key, (column, label, colors, fmt) in METRICS.items():
        # The color legend is not added: both legends would show at once, and folium can't tie a legend to a layer.
        group, _cmap = build_choropleth_layer(label, column, colors, fmt, boundaries, rows, show=(key == "home"))
        group.add_to(m)
        choro_groups[key] = group

    # Commute isochrones (independent, off by default)
    iso_colors = {20: "#1a9850", 30: "#91cf60", 40: "#fee08b", 50: "#fc8d59", 60: "#d73027", 70: "#9970ab", 80: "#5e3c99", 90: "#2d004b"}
    for name, path in [("Bike isochrones", ROOT / "output" / "isochrones_bike.geojson"),
                       ("Drive isochrones", ROOT / "output" / "isochrones_drive.geojson")]:
        if path.exists():
            build_isochrone_layer(path, name, iso_colors, show=False).add_to(m)

    m.get_root().html.add_child(folium.Element(iso_legend_html('iso_legend', 'Commute Times')))
    folium.LayerControl(collapsed=False).add_to(m)

    # Only one choropleth at a time (home value vs rent). Leaflet keeps the checkboxes in sync.
    js_names = {k: g.get_name() for k, g in choro_groups.items()}
    label_names = {k: METRICS[k][1] for k in choro_groups}  # key -> layer name shown in the menu
    exclusive_js = f"""
    window.addEventListener('load', function() {{
      var map = {m.get_name()};
      var modes = {json.dumps(js_names)};
      var labelNames = {json.dumps(label_names)};
      function untick(label) {{
        document.querySelectorAll('.leaflet-control-layers-overlays label').forEach(function(l) {{
          if (l.textContent.trim() === label) {{
            var box = l.querySelector('input'); if (box) box.checked = false;
          }}
        }});
      }}
      map.on('layeradd', function(e) {{
        for (var mode in modes) {{
          var other = window[modes[mode]];
          if (other && e.layer === other) {{
            for (var m2 in modes) {{
              if (m2 !== mode) {{
                var lyr = window[modes[m2]];
                if (lyr && map.hasLayer(lyr)) {{ map.removeLayer(lyr); untick(labelNames[m2]); }}
              }}
            }}
          }}
        }}
      }});
    }});
    """
    m.get_root().script.add_child(folium.Element(exclusive_js))

    OUT.parent.mkdir(exist_ok=True)
    m.save(str(OUT))
    print(f"Saved {OUT} with {len(boundaries['features'])} ZIPs")


if __name__ == "__main__":
    main()
