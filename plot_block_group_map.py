"""
Step 2 + 3 map: Census block groups within ~25 km of 333 Dexter Ave N.

Layers:
    - Median household income, renter share, median home value, median gross rent
      (exclusive: only one choropleth shows at a time)
    - Residential parking zones (RPZ) overlay (checkbox, off by default)
    - Bike and drive isochrones (checkboxes, off by default)

Inputs:
    data/bg_king_rpz.geojson   block-group boundaries + share of each block group inside RPZ zones
    data/acs_bg_king.json      Census ACS 5-year 2024 data pulled from the Census API
    data/rpz.geojson           RPZ zone polygons (EPSG:2926)
    output/isochrones_*.geojson

Output:
    output/block_group_map.html
"""

import json
import math
from pathlib import Path

import branca.colormap as cm
import folium
import geopandas as gpd

ROOT = Path(__file__).parent
DATA = ROOT / "data"
OUT = ROOT / "output" / "block_group_map.html"
DEST = (47.6219275, -122.3434557)  # 333 Dexter Ave N
RADIUS_KM = 40
MISSING = -500000000  # Census uses large negative numbers for "no data"


def haversine_km(a, b):
    R = 6371.0
    la1, lo1, la2, lo2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    d = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * R * math.asin(math.sqrt(d))


def load_acs() -> dict:
    rows = json.loads((DATA / "acs_bg_region.json").read_text())
    header, body = rows[0], rows[1:]
    idx = {name: i for i, name in enumerate(header)}
    out = {}
    for r in body:
        geoid = r[idx["state"]] + r[idx["county"]] + r[idx["tract"]] + r[idx["block group"]]

        def num(col):
            v = float(r[idx[col]])
            return None if v <= MISSING else v

        occupied, renters = num("B25003_001E"), num("B25003_003E")
        out[geoid] = {
            "income": num("B19013_001E"),
            "renter_share": (renters / occupied * 100) if occupied else None,
            "home_value": num("B25077_001E"),
            "rent": num("B25064_001E"),
            "name": r[idx["NAME"]],
        }
    return out


def clip_domain(values: list) -> tuple:
    """Stretch colors across the 10th–90th percentile so outliers don't wash out the rest."""
    ordered = sorted(values)
    return ordered[int(0.10 * (len(ordered) - 1))], ordered[int(0.90 * (len(ordered) - 1))]


def choropleth(name, key, fmt, colors, bgs, acs, show):
    vals = {g: acs[g][key] for g in bgs["GEOID"] if g in acs and acs[g][key] is not None}
    lo, hi = clip_domain(list(vals.values()))
    cmap = cm.LinearColormap(colors, vmin=lo, vmax=hi)
    group = folium.FeatureGroup(name=name, show=show)
    for _, row in bgs.iterrows():
        g = row["GEOID"]
        if g not in vals:
            continue
        v = vals[g]
        fill = cmap(min(max(v, lo), hi))
        tip = f"{acs[g]['name'].split(';')[0]}<br>{name}: {fmt.format(v)}<br>Renters: {acs[g]['renter_share']:.0f}%" if acs[g]['renter_share'] is not None else f"{name}: {fmt.format(v)}"
        folium.GeoJson(
            row.geometry.__geo_interface__,
            style_function=lambda _, c=fill: {"fillColor": c, "color": "#333", "weight": 0.5, "fillOpacity": 0.7},
            highlight_function=lambda _: {"weight": 2.5, "color": "#000"},
            tooltip=tip,
        ).add_to(group)
    return group, lo, hi

def legend_html(legend_id: str, name: str, fmt: str, colors: list, lo: float, hi: float) -> str:
    """Small gradient legend with the low/high values. Shown/hidden by JavaScript."""
    gradient = ", ".join(colors)
    return f"""
    <div id="{legend_id}" style="display:none; position:fixed; bottom:30px; left:50px; z-index:9999;
         background:white; padding:10px 12px; border-radius:6px; box-shadow:0 0 6px rgba(0,0,0,.3);
         font:12px Arial, sans-serif; min-width:240px;">
      <b>{name}</b><br>
      <div style="width:240px; height:12px; margin:6px 0 2px; background:linear-gradient(to right, {gradient});"></div>
      <div style="display:flex; justify-content:space-between; width:240px;">
        <span>{fmt.format(lo)}</span><span>{fmt.format(hi)}</span>
      </div>
      <div style="color:#666; margin-top:4px;">Colors stretch across the 10th–90th percentile.</div>
    </div>
    """



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

def main():
    acs = load_acs()
    bgs = gpd.read_file(DATA / "bg_region_rpz.geojson")
    # Keep block groups whose center is within RADIUS_KM of the destination
    centers = bgs.to_crs(2926).geometry.centroid.to_crs(4326)  # centroid in meters, then back to lat/lon
    keep = [haversine_km(DEST, (c.y, c.x)) <= RADIUS_KM for c in centers]
    bgs = bgs[keep].reset_index(drop=True)

    m = folium.Map(location=DEST, zoom_start=11, tiles=None)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
        attr="Tiles © Esri — Esri, HERE, Garmin, USGS, NGA, EPA, NPS",
        name="Street map",
    ).add_to(m)
    folium.Marker(DEST, tooltip=folium.Tooltip("Apple Office - 333 Dexter Ave N", permanent=True), icon=folium.Icon(color="black", icon="briefcase")).add_to(m)

    specs = [
        ("Median household income", "income", "${:,.0f}", ["#f7fcf5", "#a1d99b", "#238b45", "#00441b"]),
        ("Renter share (%)", "renter_share", "{:.0f}%", ["#fff5eb", "#fdae6b", "#e6550d", "#7f2704"]),
        ("Median home value", "home_value", "${:,.0f}", ["#ffffb2", "#fecc5c", "#fd8d3c", "#e31a1c"]),
        ("Median gross rent", "rent", "${:,.0f}/mo", ["#f7fbff", "#9ecae1", "#4292c6", "#08306b"]),
    ]
    groups = {}
    legends = {}
    for i, (name, key, fmt, colors) in enumerate(specs):
        g, lo, hi = choropleth(name, key, fmt, colors, bgs, acs, show=(i == 2))
        g.add_to(m)
        groups[key] = g
        legends[key] = legend_html(f"legend_{key}", name, fmt, colors, lo, hi)

    # RPZ overlay (independent)
    rpz = gpd.read_file(DATA / "rpz.geojson").set_crs(2926, allow_override=True).to_crs(4326)
    folium.GeoJson(
        json.loads(rpz.to_json()),
        name="Residential parking zones",
        show=False,
        style_function=lambda _: {"color": "#7b3294", "weight": 2, "fillColor": "#c2a5cf", "fillOpacity": 0.25},
        tooltip=folium.GeoJsonTooltip(fields=["NAME"], aliases=["Zone:"]),
    ).add_to(m)

    # Isochrones (independent)
    iso_colors = {20: "#1a9850", 30: "#91cf60", 40: "#fee08b", 50: "#fc8d59", 60: "#d73027", 70: "#9970ab", 80: "#5e3c99", 90: "#2d004b"}
    for label, fname in [("Bike isochrones", "isochrones_bike.geojson"), ("Drive isochrones", "isochrones_drive.geojson")]:
        path = ROOT / "output" / fname
        if not path.exists():
            continue
        fc = json.loads(path.read_text())
        grp = folium.FeatureGroup(name=label, show=False)
        for feat in sorted(fc["features"], key=lambda f: -f["properties"]["minutes"]):
            mins = feat["properties"]["minutes"]
            folium.GeoJson(
                feat,
                style_function=lambda _, c=iso_colors[mins]: {"fillColor": c, "color": c, "weight": 1, "fillOpacity": 0.55},
                tooltip=f"{label}: {mins} min",
            ).add_to(grp)
        grp.add_to(m)

    m.get_root().html.add_child(folium.Element(iso_legend_html('iso_legend', 'Commute Times')))
    folium.LayerControl(collapsed=False).add_to(m)

    js_names = {k: g.get_name() for k, g in groups.items()}
    label_names = {spec[1]: spec[0] for spec in specs}  # key -> layer name shown in the menu
    legend_ids = {k: f"legend_{k}" for k in groups}
    for leg in legends.values():
        m.get_root().html.add_child(folium.Element(leg))
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
      var legendIds = {json.dumps(legend_ids)};
      function showLegendFor(key) {{
        for (var k in legendIds) {{
          var el = document.getElementById(legendIds[k]);
          if (el) el.style.display = (k === key) ? 'block' : 'none';
        }}
      }}
      for (var k in modes) {{
        if (map.hasLayer(window[modes[k]])) showLegendFor(k);
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
            showLegendFor(mode);
          }}
        }}
      }});
    }});
    """
    m.get_root().script.add_child(folium.Element(exclusive_js))

    OUT.parent.mkdir(exist_ok=True)
    m.save(str(OUT))
    print(f"Saved {OUT} with {len(bgs)} block groups within {RADIUS_KM} km")


if __name__ == "__main__":
    main()
