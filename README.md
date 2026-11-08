# Seattle commute and housing maps

Maps of bike and drive commute times from 333 Dexter Ave N, Seattle, overlaid with Census block-group data, Zillow ZIP data, and Seattle residential parking zones.

## Setup

1. Create a Python environment and install the packages:
   ```
   python3 -m venv .venv
   ./.venv/bin/pip install requests folium geopandas pyogrio pyproj branca shapely
   ```
2. Get free keys:
   - OpenRouteService (isochrones): https://openrouteservice.org/dev/#/signup
   - US Census (demographics): https://api.census.gov/data/key_signup.html
3. Save each key in a file in this folder (keep these files private, they are git-ignored):
   - `.ors_key`: the OpenRouteService key on one line
   - `.census_key`: the Census key on one line

## Build the maps

Run in this order (the data files are downloaded or built by these scripts):

1. `python isochrones.py`: bike and drive travel-time bands, 20 to 90 minutes
2. `python build_zip_summary.py`: Zillow ZIP values within 25 km (needs `data/zillow_zhvi_zip.csv` and `data/zillow_zori_zip.csv` from zillow.com/research/data)
3. `python build_region_bg.py`: block-group boundaries and Census data (needs the ACS downloads described in that file)
4. `python plot_combined_map.py`: the combined map, saved to `output/combined_map.html`

Data sources: U.S. Census Bureau (ACS 5-year 2020–2024, TIGER 2024), Zillow Research (ZHVI, ZORI), City of Seattle SDOT (Restricted Parking Zones), OpenRouteService with OpenStreetMap roads.
