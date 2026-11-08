"""
Combined map: everything on one page.

Color layers (one at a time, each with its own legend):
    Block groups (40 km):  median household income, renter share, median home value, median gross rent
    ZIP codes (25 km):     typical home value, typical rent
Overlays (checkboxes):
    Residential parking zones, bike isochrones, drive isochrones
Always visible:
    Commute Times key (isochrone colors)

Output: output/combined_map.html
"""

import csv
import html
import json
import math
from pathlib import Path

import branca.colormap as cm
import folium
import folium.plugins
import geopandas as gpd

ROOT = Path(__file__).parent
DATA = ROOT / "data"
OUT = ROOT / "output" / "combined_map.html"
DEST = (47.6219275, -122.3434557)  # 333 Dexter Ave N
BG_RADIUS_KM = 40
MISSING = -500000000
ISO_COLORS = {20: "#1a9850", 30: "#91cf60", 40: "#fee08b", 50: "#fc8d59", 60: "#d73027",
              70: "#9970ab", 80: "#5e3c99", 90: "#2d004b"}


def haversine_km(a, b):
    R = 6371.0
    la1, lo1, la2, lo2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    d = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * R * math.asin(math.sqrt(d))


CENSUS = ("U.S. Census Bureau, American Community Survey 5-year estimates (2020–2024), "
          "block groups; pulled from the Census API")
ZILLOW = "Zillow Research, ZIP-level public data (latest month: Sept 2026)"
LAYER_INFO = {
    "Median household income": f"Median household income of residents in each block group. Source: {CENSUS} (table B19013).",
    "Renter share (%)": f"Share of occupied homes that are rented, by block group. Source: {CENSUS} (table B25003).",
    "Median home value": f"Median value of owner-occupied homes, by block group. Source: {CENSUS} (table B25077). Self-reported by owners, so may lag the market.",
    "Median gross rent": f"Median monthly rent including utilities, by block group. Source: {CENSUS} (table B25064).",
    "ZIP: Typical home value": f"Typical home value in each ZIP code (Zillow Home Value Index, all homes). Source: {ZILLOW}.",
    "ZIP: Typical rent": f"Typical monthly rent in each ZIP code (Zillow Observed Rent Index, all rentals). Source: {ZILLOW}.",
    "Residential parking zones": "Seattle Residential Parking Zone (RPZ) areas, where street parking is limited to permit holders. Source: City of Seattle Department of Transportation, Restricted Parking Zones dataset (City of Seattle ArcGIS open data).",
    "Bike isochrones": "How far you can ride a bike from 333 Dexter Ave N in 20–90 minutes. Source: OpenRouteService cycling routes on OpenStreetMap roads.",
    "Drive isochrones": "How far you can drive from 333 Dexter Ave N in 20–90 minutes. Source: OpenRouteService driving routes on OpenStreetMap roads.",
}

def iso_band_text(mins, prev):
    """Tooltip for one travel-time band: the ring between the previous band and this one."""
    span = f"{prev}–{mins} min" if prev else f"0–{mins} min"
    return (f"{span} from 333 Dexter Ave N. Bike = cycling route time; drive = car route time. "
            "Routes from OpenRouteService using OpenStreetMap roads. Band shows only its own ring, "
            "not the area inside shorter bands.")

def clip_domain(values):
    ordered = sorted(values)
    return ordered[int(0.10 * (len(ordered) - 1))], ordered[int(0.90 * (len(ordered) - 1))]


def legend_html(legend_id, name, fmt, colors, lo, hi):
    gradient = ", ".join(colors)
    info = html.escape(LAYER_INFO.get(name, ""), quote=True)
    return f"""
    <div id="{legend_id}" style="display:none; position:fixed; bottom:30px; left:50px; z-index:9999;
         background:white; padding:10px 12px; border-radius:6px; box-shadow:0 0 6px rgba(0,0,0,.3);
         font:12px Arial, sans-serif; min-width:240px;">
      <b title="{info}" style="border-bottom:1px dotted #888;">{name}</b><br>
      <div style="width:240px; height:12px; margin:6px 0 2px; background:linear-gradient(to right, {gradient});"></div>
      <div style="display:flex; justify-content:space-between; width:240px;">
        <span>{fmt.format(lo)}</span><span>{fmt.format(hi)}</span>
      </div>
      <div style="color:#666; margin-top:4px;">Colors stretch across the 10th–90th percentile.</div>
    </div>
    """


def iso_key_html():
    times = sorted(ISO_COLORS)
    rows = "".join(
        f'<div title="{html.escape(iso_band_text(m, times[i - 1] if i else 0), quote=True)}" '
        f'style="display:flex; align-items:center; margin:2px 0;">'
        f'<span style="display:inline-block; width:22px; height:12px; background:{ISO_COLORS[m]}; '
        f'border:1px solid #999; margin-right:6px;"></span>{m} min</div>'
        for i, m in enumerate(times)
    )
    title_text = html.escape(
        "Travel-time bands from 333 Dexter Ave N. Hover a band for details. "
        "Source: OpenRouteService isochrones (bike and drive) on OpenStreetMap roads.", quote=True)
    return (
        '<div id="iso_legend" style="display:block; position:fixed; bottom:30px; right:20px; z-index:9999; '
        'background:white; padding:10px 12px; border-radius:6px; box-shadow:0 0 6px rgba(0,0,0,.3); '
        f'font:12px Arial, sans-serif;"><b title="{title_text}" style="border-bottom:1px dotted #888;">'
        f'Commute Times</b><div style="margin-top:6px;">{rows}</div></div>'
    )


def load_bg_acs():
    rows = json.loads((DATA / "acs_bg_region.json").read_text())
    header, body = rows[0], rows[1:]
    idx = {n: i for i, n in enumerate(header)}
    out = {}
    for r in body:
        geoid = r[idx["state"]] + r[idx["county"]] + r[idx["tract"]] + r[idx["block group"]]

        def num(col):
            v = float(r[idx[col]])
            return None if v <= MISSING else v

        occ, ren = num("B25003_001E"), num("B25003_003E")
        out[geoid] = {
            "income": num("B19013_001E"),
            "renter_share": (ren / occ * 100) if occ else None,
            "home_value": num("B25077_001E"),
            "rent": num("B25064_001E"),
            "name": r[idx["NAME"]].split(";")[0],
        }
    return out


def color_layer(name, values, fmt, colors, geoms, show, tooltip_extra=None):
    """values: {zip_or_geoid: float}; geoms: {id: GeoJSON geometry dict}. Returns (group, lo, hi)."""
    lo, hi = clip_domain(list(values.values()))
    cmap = cm.LinearColormap(colors, vmin=lo, vmax=hi)
    group = folium.FeatureGroup(name=name, show=show)
    for key, v in values.items():
        if key not in geoms:
            continue
        fill = cmap(min(max(v, lo), hi))
        tip = f"{key}: {fmt.format(v)}"
        if tooltip_extra:
            tip = tooltip_extra(key, v, fmt)
        folium.GeoJson(
            geoms[key],
            style_function=lambda _, c=fill: {"fillColor": c, "color": "#333", "weight": 0.5, "fillOpacity": 0.7},
            highlight_function=lambda _: {"weight": 2.5, "color": "#000"},
            tooltip=tip,
        ).add_to(group)
    return group, lo, hi


def main():
    m = folium.Map(location=DEST, zoom_start=11, tiles=None)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
        attr="Tiles © Esri — Esri, HERE, Garmin, USGS, NGA, EPA, NPS",
        name="Street map",
    ).add_to(m)
    folium.Marker(DEST, tooltip=folium.Tooltip("Apple Office - 333 Dexter Ave N", permanent=True), icon=folium.Icon(color="black", icon="briefcase")).add_to(m)

    choro = {}   # layer name -> (group, legend_id, legend_html)
    legends = []

    # ---- Block-group choropleths ----
    acs = load_bg_acs()
    bgs = gpd.read_file(DATA / "bg_region_rpz.geojson")
    centers = bgs.to_crs(2926).geometry.centroid.to_crs(4326)
    bgs = bgs[[haversine_km(DEST, (c.y, c.x)) <= BG_RADIUS_KM for c in centers]].reset_index(drop=True)
    bg_geoms = {r["GEOID"]: r.geometry.__geo_interface__ for _, r in bgs.iterrows()}
    bg_specs = [
        ("Median household income", "income", "${:,.0f}", ["#f7fcf5", "#a1d99b", "#238b45", "#00441b"]),
        ("Renter share (%)", "renter_share", "{:.0f}%", ["#fff5eb", "#fdae6b", "#e6550d", "#7f2704"]),
        ("Median home value", "home_value", "${:,.0f}", ["#ffffb2", "#fecc5c", "#fd8d3c", "#e31a1c"]),
        ("Median gross rent", "rent", "${:,.0f}/mo", ["#f7fbff", "#9ecae1", "#4292c6", "#08306b"]),
    ]
    for name, key, fmt, colors in bg_specs:
        vals = {g: acs[g][key] for g in bg_geoms if g in acs and acs[g][key] is not None}
        group, lo, hi = color_layer(name, vals, fmt, colors, bg_geoms, show=False)
        choro[name] = (group, legend_html(f"legend_{len(choro)}", name, fmt, colors, lo, hi))

    # ---- ZIP choropleths ----
    zrows = {r["zip"]: r for r in csv.DictReader(open(DATA / "zip_summary_radius.csv", newline=""))}
    zbounds = json.loads((DATA / "wa_zip_boundaries.geojson").read_text())["features"]
    zgeoms = {f["properties"]["ZCTA5CE10"]: f["geometry"] for f in zbounds if f["properties"]["ZCTA5CE10"] in zrows}
    zip_specs = [
        ("ZIP: Typical home value", "zhvi_home_value_latest", "${:,.0f}", ["#ffffb2", "#fecc5c", "#fd8d3c", "#e31a1c"]),
        ("ZIP: Typical rent", "zori_rent_latest", "${:,.0f}/mo", ["#f7fbff", "#9ecae1", "#4292c6", "#08306b"]),
    ]
    for name, col, fmt, colors in zip_specs:
        vals = {z: float(r[col]) for z, r in zrows.items() if r.get(col)}
        tip = lambda k, v, f, _rows=zrows: f"ZIP {k} ({_rows[k]['city']}): {f.format(v)}"
        group, lo, hi = color_layer(name, vals, fmt, colors, zgeoms, show=False, tooltip_extra=tip)
        choro[name] = (group, legend_html(f"legend_{len(choro)}", name, fmt, colors, lo, hi))

    # Default layer on
    for name, (group, leg) in choro.items():
        group.add_to(m)
        legends.append(leg)

    # ---- Overlays ----
    rpz = gpd.read_file(DATA / "rpz.geojson").set_crs(2926, allow_override=True).to_crs(4326)
    rpz_group = folium.FeatureGroup(name="Residential parking zones", show=False)
    folium.GeoJson(
        json.loads(rpz.to_json()),
        style_function=lambda _: {"color": "#7b3294", "weight": 2, "fillColor": "#c2a5cf", "fillOpacity": 0.25},
        tooltip=folium.GeoJsonTooltip(fields=["NAME"], aliases=["Zone:"]),
    ).add_to(rpz_group)
    rpz_group.add_to(m)

    iso_groups = {}
    for label, fname in [("Bike isochrones", "isochrones_bike.geojson"), ("Drive isochrones", "isochrones_drive.geojson")]:
        fc = json.loads((ROOT / "output" / fname).read_text())
        grp = folium.FeatureGroup(name=label, show=(label == "Drive isochrones"))  # only drive on by default
        for feat in sorted(fc["features"], key=lambda f: -f["properties"]["minutes"]):
            mins = feat["properties"]["minutes"]
            folium.GeoJson(
                feat,
                style_function=lambda _, c=ISO_COLORS[mins]: {"fillColor": c, "color": c, "weight": 1, "fillOpacity": 0.55},
                tooltip=f"{label}: {mins} min",
            ).add_to(grp)
        grp.add_to(m)
        iso_groups[label] = grp

    # Group the menu into three buckets. Each layer is listed once.
    bucket_members = {
        "Commute": [iso_groups["Bike isochrones"], iso_groups["Drive isochrones"]],
        "Renter": [choro["Renter share (%)"][0], choro["Median gross rent"][0],
                   choro["ZIP: Typical rent"][0], rpz_group],
        "Home owner": [choro["Median home value"][0], choro["Median household income"][0],
                       choro["ZIP: Typical home value"][0]],
    }
    folium.plugins.GroupedLayerControl(groups=bucket_members, collapsed=False, exclusive_groups=False).add_to(m)

    for leg in legends:
        m.get_root().html.add_child(folium.Element(leg))
    m.get_root().html.add_child(folium.Element(iso_key_html()))

    # ---- Only one color layer at a time; legend follows the active layer ----
    js_names = {i: g.get_name() for i, (name, (g, _)) in enumerate(choro.items())}
    label_names = {i: name for i, (name, _) in enumerate(choro.items())}
    legend_ids = {i: f"legend_{i}" for i in range(len(choro))}
    exclusive_js = f"""
    window.addEventListener('load', function() {{
      var map = {m.get_name()};
      var modes = {json.dumps(js_names)};
      var labelNames = {json.dumps(label_names)};
      var legendIds = {json.dumps(legend_ids)};
      var layerInfo = {json.dumps(LAYER_INFO)};
      function labelText(l) {{
        var c = l.cloneNode(true);
        c.querySelectorAll('.lyr-info').forEach(function(n) {{ n.remove(); }});
        return c.textContent.trim();
      }}
      document.querySelectorAll('.leaflet-control-layers label').forEach(function(l) {{
        var t = labelText(l);
        if (!layerInfo[t]) return;
        // Find the span holding just the layer name (not the checkbox), so hover applies to the words only
        var nameSpan = null;
        l.querySelectorAll('span').forEach(function(sp) {{
          if (!nameSpan && !sp.querySelector('input') && !sp.classList.contains('lyr-info') && sp.textContent.trim() === t) {{
            nameSpan = sp;
          }}
        }});
        if (!nameSpan) {{
          // Fallback: wrap the bare text nodes of the label in a span
          nameSpan = document.createElement('span');
          Array.from(l.childNodes).forEach(function(n) {{
            if (n.nodeType === 3 && n.textContent.trim()) nameSpan.appendChild(n);
          }});
          l.appendChild(nameSpan);
        }}
        nameSpan.classList.add('lyr-name');
        l.style.position = 'relative';
        var pop = document.createElement('span');
        pop.className = 'lyr-info';
        pop.innerHTML = layerInfo[t].replace(' Source: ', '<br><b>Source:</b> ');
        l.appendChild(pop);  // sibling of the name, positioned against the whole row
      }});
      function untick(label) {{
        document.querySelectorAll('.leaflet-control-layers-overlays label').forEach(function(l) {{
          if (labelText(l) === label) {{
            var box = l.querySelector('input'); if (box) box.checked = false;
          }}
        }});
      }}
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
    m.get_root().header.add_child(folium.Element("""
    <style>
      .lyr-info {
        display: none; position: absolute; right: 100%; top: 0; margin-right: 14px; z-index: 10000;
        width: 280px; background: #fff; border: 1px solid #999; border-radius: 4px;
        padding: 8px 10px; box-shadow: 0 2px 8px rgba(0,0,0,.25);
        font: 12px/1.4 Arial, sans-serif; color: #222; white-space: normal;
      }
      .lyr-name { display: inline-block; margin-left: 6px; transform-origin: left center; transition: transform .12s ease; }
      .lyr-name:hover { transform: scale(1.08); }
      .lyr-name:hover ~ .lyr-info { display: block; }
    </style>
    """))

    OUT.parent.mkdir(exist_ok=True)
    m.save(str(OUT))
    print(f"Saved {OUT}: {len(bg_geoms)} block groups, {len(zgeoms)} ZIPs, {len(choro)} color layers")


if __name__ == "__main__":
    main()
