# app.py - Road Distance Finder v2.0 (Streamlit)
# Complete version with all features integrated
# Features:
# - Sites/Airports/Seaports distance calculations with Top-N prefilter
# - Highway/expressway distance calculations
# - Eurostat population and unemployment catchment areas
# - NUTS2/NUTS3 enrichment (fixed)
# - Project ID and Site ID support
# - Site Selection Tool export format
# - Enhanced map visualization with fullscreen
# - National admin boundaries (PL + custom URL loader)

import io
import time
import math
import json
from typing import Tuple, Dict, Any, List, Optional
from datetime import datetime

import numpy as np
import pandas as pd
import requests
import streamlit as st

# ---------------------- Optional imports ----------------------
try:
    from streamlit.runtime.uploaded_file_manager import UploadedFile  # type: ignore
except Exception:
    from typing import Any as UploadedFile  # type: ignore

try:
    from streamlit_folium import st_folium  # type: ignore
    import folium  # type: ignore
    from folium.plugins import Fullscreen  # type: ignore
    _HAS_MAP = True
except Exception:
    _HAS_MAP = False

# Geometry stack (required for admin/NUTS)
try:
    from shapely.geometry import shape, Point  # type: ignore
    from shapely.strtree import STRtree  # type: ignore
    from shapely.validation import make_valid
    _HAS_SHAPELY = True
except Exception:
    _HAS_SHAPELY = False

# ---------------------- App constants ----------------------
APP_TITLE = "Road Distance Finder v2.0"
APP_SUBTITLE = "Complete site evaluation with logistics, labor market, and infrastructure analysis"
DEFAULT_REF = {"name": "Bedburg, Germany", "lat": 51.0126, "lon": 6.5741}
REQUIRED_SITES_COLS = ["Project ID", "Site ID", "Site Name", "Latitude", "Longitude"]
REQUIRED_AIRPORTS_COLS = ["Airport Name", "Latitude", "Longitude"]
REQUIRED_SEAPORTS_COLS = ["Seaport Name", "Latitude", "Longitude"]
ENRICH_DEFAULT_OSM_ADMIN = True

# Eurostat API endpoints
EUROSTAT_API_BASE = "https://ec.europa.eu/eurostat/api/dissemination"
EUROSTAT_DATA_V2 = f"{EUROSTAT_API_BASE}/statistics/1.0/data"
EUROSTAT_METADATA = f"{EUROSTAT_API_BASE}/metadata/1.0/codelist"

# Eurostat dataset codes
POPULATION_DATASET = "demo_r_pjangrp3"  # Population by age, sex and NUTS 3 regions
UNEMPLOYMENT_DATASET = "lfst_r_lfu3rt"  # Unemployment by NUTS 3 regions
ACTIVE_POP_DATASET = "lfst_r_lfp3pop"  # Active population by NUTS 3 regions

# NUTS URLs
NUTS2_URL = "https://gisco-services.ec.europa.eu/distribution/v2/nuts/geojson/NUTS_RG_01M_2021_4326_LEVL_2.geojson"
NUTS3_URL = "https://gisco-services.ec.europa.eu/distribution/v2/nuts/geojson/NUTS_RG_01M_2021_4326_LEVL_3.geojson"

# Overpass API for highway detection
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# OSM endpoints
NOMINATIM_REVERSE = "https://nominatim.openstreetmap.org/reverse"
NOMINATIM_SEARCH = "https://nominatim.openstreetmap.org/search"

# OSRM routing
OSRM_URL = "https://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=false&annotations=duration,distance"

# ---------------------- Load EU Cities Database ----------------------
import os
import sys

# Ensure we can find eu_cities_db.py in the same directory
_app_dir = os.path.dirname(os.path.abspath(__file__))
if _app_dir not in sys.path:
    sys.path.insert(0, _app_dir)

try:
    from eu_cities_db import EU_CITIES_DB, get_nearest_city
    _HAS_CITIES_DB = True
except ImportError as import_err:
    _HAS_CITIES_DB = False
    EU_CITIES_DB = {}
    def get_nearest_city(lat, lon, max_distance=200):
        return None

# ---------------------- Utilities ----------------------
def haversine_km(lat1, lon1, lat2, lon2):
    """Calculate distance between two points on Earth using Haversine formula"""
    R = 6371.0088
    phi1 = np.radians(lat1)
    phi2 = np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlambda = np.radians(lon2 - lon1)
    a = np.sin(dphi/2.0)**2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlambda/2.0)**2
    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1-a))
    return R * c

# ---------------------- Template files ----------------------
@st.cache_data(show_spinner=False)
def template_files() -> Dict[str, bytes]:
    """Generate Excel templates with example data"""
    out: Dict[str, bytes] = {}
    
    # Sites.xlsx with Project ID and Site ID
    df_sites = pd.DataFrame([
        {"Project ID": "P-20250101-01", "Site ID": "SK-20250101-01", "Site Name": "Example Plant A", 
         "Latitude": 52.2297, "Longitude": 21.0122},
        {"Project ID": "P-20250101-01", "Site ID": "SK-20250101-02", "Site Name": "Example Plant B", 
         "Latitude": 48.1486, "Longitude": 17.1077},
        {"Project ID": "P-20250101-02", "Site ID": "SK-20250102-01", "Site Name": "Example Plant C", 
         "Latitude": 50.1109, "Longitude": 8.6821},
    ])
    b = io.BytesIO()
    with pd.ExcelWriter(b, engine="xlsxwriter") as xw:
        df_sites.to_excel(xw, sheet_name="Sites", index=False)
    out["Sites.xlsx"] = b.getvalue()
    
    # Airports.xlsx
    df_airports = pd.DataFrame([
        {"Airport Name": "Frankfurt Airport", "IATA": "FRA", "Latitude": 50.0379, "Longitude": 8.5622},
        {"Airport Name": "Warsaw Chopin Airport", "IATA": "WAW", "Latitude": 52.1657, "Longitude": 20.9671},
        {"Airport Name": "Vienna International Airport", "IATA": "VIE", "Latitude": 48.1103, "Longitude": 16.5697},
        {"Airport Name": "Prague Vaclav Havel", "IATA": "PRG", "Latitude": 50.1008, "Longitude": 14.2600},
        {"Airport Name": "Amsterdam Schiphol", "IATA": "AMS", "Latitude": 52.3105, "Longitude": 4.7683},
    ])
    b = io.BytesIO()
    with pd.ExcelWriter(b, engine="xlsxwriter") as xw:
        df_airports.to_excel(xw, sheet_name="Airports", index=False)
    out["Airports.xlsx"] = b.getvalue()
    
    # Seaports.xlsx
    df_ports = pd.DataFrame([
        {"Seaport Name": "Rotterdam", "UNLOCODE": "NLRTM", "Latitude": 51.9490, "Longitude": 4.1420},
        {"Seaport Name": "Hamburg", "UNLOCODE": "DEHAM", "Latitude": 53.5461, "Longitude": 9.9661},
        {"Seaport Name": "Antwerp", "UNLOCODE": "BEANR", "Latitude": 51.2637, "Longitude": 4.3866},
        {"Seaport Name": "Gdynia", "UNLOCODE": "PLGDY", "Latitude": 54.5333, "Longitude": 18.5500},
        {"Seaport Name": "Valencia", "UNLOCODE": "ESVLC", "Latitude": 39.4400, "Longitude": -0.3167},
    ])
    b = io.BytesIO()
    with pd.ExcelWriter(b, engine="xlsxwriter") as xw:
        df_ports.to_excel(xw, sheet_name="Seaports", index=False)
    out["Seaports.xlsx"] = b.getvalue()
    
    return out

# ---------------------- Site Selection Tool Export Format ----------------------
def create_site_selection_format(df_results: pd.DataFrame, ref_name: str = None, catchment_radius: int = 50) -> pd.DataFrame:
    """Convert results to long format for Site Selection Tool"""
    long_format_rows = []
    
    for _, row in df_results.iterrows():
        # Extract base site information
        project_id = row.get("Project ID", "")
        site_id = row.get("Site ID", "")
        site_name = row.get("Site Name", "")
        lat = row.get("Latitude", "")
        lon = row.get("Longitude", "")
        nuts3_code = row.get("NUTS3 Code", "")
        
        # Airport record (Accessibility: 1)
        if pd.notna(row.get("Nearest Airport")):
            long_format_rows.append({
                "Project ID": project_id,
                "Project Name": "",
                "Site ID": site_id,
                "Site Name": site_name,
                "LatitudeY": lat,
                "LongitudeX": lon,
                "Destination": row.get("Nearest Airport", ""),
                "Destination group": "Nearest Airport",
                "Distance (km)": row.get("Distance to Airport (km)", ""),
                "Time (min)": row.get("Time to Airport (min)", ""),
                "Accessibility": 1,
                "NUTS3 Code": nuts3_code
            })
        
        # Seaport record (renamed to "Inbound", Accessibility: 0)
        if pd.notna(row.get("Nearest Seaport")):
            long_format_rows.append({
                "Project ID": project_id,
                "Project Name": "",
                "Site ID": site_id,
                "Site Name": site_name,
                "LatitudeY": lat,
                "LongitudeX": lon,
                "Destination": row.get("Nearest Seaport", ""),
                "Destination group": "Inbound",
                "Distance (km)": row.get("Distance to Seaport (km)", ""),
                "Time (min)": row.get("Time to Seaport (min)", ""),
                "Accessibility": 0,
                "NUTS3 Code": nuts3_code
            })
        
        # Highway record (Accessibility: 1)
        if pd.notna(row.get("Nearest Highway Access")):
            long_format_rows.append({
                "Project ID": project_id,
                "Project Name": "",
                "Site ID": site_id,
                "Site Name": site_name,
                "LatitudeY": lat,
                "LongitudeX": lon,
                "Destination": row.get("Nearest Highway Access", ""),
                "Destination group": "Nearest Highway",
                "Distance (km)": row.get("Distance to Highway (km)", ""),
                "Time (min)": row.get("Time to Highway (min)", ""),
                "Accessibility": 1,
                "NUTS3 Code": nuts3_code
            })
        
        # Reference location (renamed to "Outbound", Accessibility: 0)
        if ref_name:
            ref_dist_col = f"Distance to {ref_name} (km)"
            ref_time_col = f"Time to {ref_name} (min)"
            if ref_dist_col in row and pd.notna(row[ref_dist_col]):
                long_format_rows.append({
                    "Project ID": project_id,
                    "Project Name": "",
                    "Site ID": site_id,
                    "Site Name": site_name,
                    "LatitudeY": lat,
                    "LongitudeX": lon,
                    "Destination": ref_name,
                    "Destination group": "Outbound",
                    "Distance (km)": row.get(ref_dist_col, ""),
                    "Time (min)": row.get(ref_time_col, ""),
                    "Accessibility": 0,
                    "NUTS3 Code": nuts3_code
                })
        
        # Nearest city (100k+) (Accessibility: 1)
        if pd.notna(row.get("Nearest City (100k+)")):
            long_format_rows.append({
                "Project ID": project_id,
                "Project Name": "",
                "Site ID": site_id,
                "Site Name": site_name,
                "LatitudeY": lat,
                "LongitudeX": lon,
                "Destination": row.get("Nearest City (100k+)", ""),
                "Destination group": "Nearest City",
                "Distance (km)": row.get("Distance to City (km)", ""),
                "Time (min)": row.get("Time to City (min)", ""),
                "Accessibility": 1,
                "NUTS3 Code": nuts3_code
            })
    
    return pd.DataFrame(long_format_rows)

# ---------------------- NUTS Loading (Fixed) ----------------------
@st.cache_resource(show_spinner=False)
def _load_nuts_index(url: str) -> Dict[str, Any]:
    """Load NUTS geometries and build spatial index"""
    if not _HAS_SHAPELY:
        return {"ok": False, "msg": "Shapely not installed", "tree": None, "geoms": [], "props": [], "count": 0}
    
    try:
        # Download with retries
        max_retries = 3
        for attempt in range(max_retries):
            try:
                r = requests.get(url, timeout=120)
                r.raise_for_status()
                gj = r.json()
                break
            except requests.exceptions.Timeout:
                if attempt == max_retries - 1:
                    raise
                time.sleep(2 ** attempt)
        
        geoms = []
        props = []
        
        for feat in gj.get("features", []):
            try:
                geom_data = feat.get("geometry")
                if not geom_data:
                    continue
                
                g = shape(geom_data)
                
                # Repair invalid geometries
                if not g.is_valid:
                    try:
                        g = make_valid(g)
                    except:
                        g = g.buffer(0)
                
                if g.is_empty:
                    continue
                
                pr = feat.get("properties", {})
                prop_dict = {
                    "NUTS_ID": pr.get("NUTS_ID", ""),
                    "NAME_LATN": pr.get("NAME_LATN", ""),
                    "LEVL_CODE": pr.get("LEVL_CODE", ""),
                    "CNTR_CODE": pr.get("CNTR_CODE", ""),
                }
                
                geoms.append(g)
                props.append(prop_dict)
            except Exception:
                continue
        
        if not geoms:
            return {"ok": False, "msg": "No valid geometries found", "tree": None, "geoms": [], "props": [], "count": 0}
        
        tree = STRtree(geoms)
        return {"ok": True, "msg": "Success", "tree": tree, "geoms": geoms, "props": props, "count": len(geoms)}
        
    except Exception as e:
        return {"ok": False, "msg": str(e), "tree": None, "geoms": [], "props": [], "count": 0}

@st.cache_resource(show_spinner=False)
def load_nuts2_index() -> Dict[str, Any]:
    return _load_nuts_index(NUTS2_URL)

@st.cache_resource(show_spinner=False)
def load_nuts3_index() -> Dict[str, Any]:
    return _load_nuts_index(NUTS3_URL)

def _nuts_lookup_generic(idx: Dict[str, Any], lat: float, lon: float) -> Dict[str, Any]:
    """Improved NUTS point-in-polygon lookup"""
    if not idx.get("ok") or not idx.get("tree"):
        return {}
    
    try:
        pt = Point(float(lon), float(lat))
        
        # Try direct query
        candidates_indices = []
        try:
            candidates_indices = list(idx["tree"].query(pt, predicate="intersects"))
        except TypeError:
            candidates = idx["tree"].query(pt)
            if hasattr(candidates, '__iter__'):
                for cand in candidates:
                    for i, geom in enumerate(idx["geoms"]):
                        if cand is geom or (hasattr(cand, 'equals') and cand.equals(geom)):
                            candidates_indices.append(i)
                            break
        except:
            pass
        
        for idx_num in candidates_indices:
            if 0 <= idx_num < len(idx["props"]):
                return idx["props"][idx_num]
        
        # Try with buffer for boundary points
        if not candidates_indices:
            try:
                buffered_pt = pt.buffer(0.0001)
                candidates_indices = list(idx["tree"].query(buffered_pt, predicate="intersects"))
            except:
                pass
            
            for idx_num in candidates_indices:
                if 0 <= idx_num < len(idx["props"]):
                    if idx["geoms"][idx_num].contains(pt) or idx["geoms"][idx_num].intersects(pt):
                        return idx["props"][idx_num]
        
        # Direct iteration fallback
        for i, geom in enumerate(idx["geoms"]):
            try:
                if geom.contains(pt) or geom.intersects(pt):
                    return idx["props"][i]
            except:
                continue
    except:
        pass
    
    return {}

@st.cache_data(show_spinner=False)
def nuts2_lookup(lat: float, lon: float) -> Dict[str, Any]:
    idx = load_nuts2_index()
    if not idx.get("ok"):
        return {}
    return _nuts_lookup_generic(idx, lat, lon)

@st.cache_data(show_spinner=False)
def nuts3_lookup(lat: float, lon: float) -> Dict[str, Any]:
    idx = load_nuts3_index()
    if not idx.get("ok"):
        return {}
    return _nuts_lookup_generic(idx, lat, lon)

# ---------------------- Highway/Expressway Detection ----------------------
@st.cache_data(show_spinner=False, ttl=3600)
def find_nearest_highway_access(lat: float, lon: float, radius_km: float = 50) -> Dict[str, Any]:
    """Find nearest highway/expressway access point using Overpass API"""
    overpass_query = f"""
    [out:json][timeout:25];
    (
      node["highway"="motorway_junction"](around:{radius_km * 1000},{lat},{lon});
      way["highway"~"motorway_link|trunk_link"](around:{radius_km * 1000},{lat},{lon});
      node(w);
    );
    out body;
    >;
    out skel qt;
    """
    
    try:
        response = requests.post(
            OVERPASS_URL,
            data=overpass_query,
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            timeout=30
        )
        response.raise_for_status()
        data = response.json()
        
        if not data.get('elements'):
            # Fallback to major roads
            fallback_query = f"""
            [out:json][timeout:25];
            (
              way["highway"~"primary|trunk"](around:{radius_km * 1000},{lat},{lon});
              node(w);
            );
            out body;
            >;
            out skel qt;
            """
            response = requests.post(OVERPASS_URL, data=fallback_query, 
                                    headers={'Content-Type': 'application/x-www-form-urlencoded'}, timeout=30)
            response.raise_for_status()
            data = response.json()
        
        min_dist = float('inf')
        nearest = None
        
        for element in data.get('elements', []):
            if element['type'] == 'node' and 'lat' in element and 'lon' in element:
                node_lat = element['lat']
                node_lon = element['lon']
                dist = haversine_km(lat, lon, node_lat, node_lon)
                
                if dist < min_dist:
                    min_dist = dist
                    nearest = {
                        'lat': node_lat,
                        'lon': node_lon,
                        'distance_straight_km': round(dist, 2),
                        'name': element.get('tags', {}).get('name', ''),
                        'ref': element.get('tags', {}).get('ref', ''),
                        'highway_type': element.get('tags', {}).get('highway', 'junction'),
                        'id': element.get('id')
                    }
        
        return nearest if nearest else {}
    except:
        return {}

def get_highway_distance(site_lat: float, site_lon: float, route_cache: Dict = None) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    """Calculate road distance to nearest highway/expressway access"""
    if route_cache is None:
        route_cache = {}
    
    highway_access = find_nearest_highway_access(site_lat, site_lon)
    
    if not highway_access:
        return None, None, None
    
    try:
        origin = (site_lat, site_lon)
        dest = (highway_access['lat'], highway_access['lon'])
        
        dist_km, dur_min = get_route(origin, dest, route_cache=route_cache)
        
        access_name = ""
        if highway_access.get('name'):
            access_name = highway_access['name']
        elif highway_access.get('ref'):
            access_name = f"Junction {highway_access['ref']}"
        else:
            access_name = f"Highway Access ({highway_access['highway_type']})"
        
        return dist_km, dur_min, access_name
    except:
        return highway_access.get('distance_straight_km'), None, "Highway Access"

# ---------------------- Eurostat API Integration ----------------------
@st.cache_data(show_spinner=False, ttl=86400)
def fetch_eurostat_data(dataset_code: str, filters: Dict[str, List[str]] = None) -> pd.DataFrame:
    """Fetch data from Eurostat API"""
    try:
        params = {"format": "JSON", "lang": "en"}
        filter_str = ""
        if filters:
            filter_parts = []
            for key, values in filters.items():
                if values:
                    filter_parts.append(f"{key}={'+'.join(values)}")
            if filter_parts:
                filter_str = "?" + "&".join(filter_parts)
        
        url = f"{EUROSTAT_DATA_V2}/{dataset_code}{filter_str}"
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        dimensions = data.get("dimension", {})
        values = data.get("value", {})
        
        dim_data = {}
        dim_positions = {}
        
        for dim_name, dim_info in dimensions.items():
            dim_data[dim_name] = dim_info.get("category", {}).get("index", {})
            dim_positions[dim_name] = dim_info.get("category", {}).get("label", {})
        
        records = []
        for idx_str, value in values.items():
            idx = int(idx_str)
            record = {"value": value}
            
            temp_idx = idx
            for dim_name in reversed(list(dimensions.keys())):
                dim_size = len(dim_data[dim_name])
                dim_idx = temp_idx % dim_size
                temp_idx = temp_idx // dim_size
                
                for key, pos in dim_data[dim_name].items():
                    if pos == dim_idx:
                        record[dim_name] = key
                        if dim_name in dim_positions and key in dim_positions[dim_name]:
                            record[f"{dim_name}_label"] = dim_positions[dim_name][key]
                        break
            
            records.append(record)
        
        return pd.DataFrame(records)
    except:
        return pd.DataFrame()

@st.cache_data(show_spinner=False, ttl=86400)
def get_nuts3_population(nuts3_codes: List[str], year: str = "2023") -> Dict[str, float]:
    """Get population for NUTS3 regions"""
    if not nuts3_codes:
        return {}
    
    filters = {
        "geo": nuts3_codes,
        "time": [year],
        "age": ["TOTAL"],
        "sex": ["T"],
        "unit": ["NR"]
    }
    
    df = fetch_eurostat_data(POPULATION_DATASET, filters)
    
    if df.empty:
        filters["time"] = [str(int(year) - 1)]
        df = fetch_eurostat_data(POPULATION_DATASET, filters)
    
    population_map = {}
    for _, row in df.iterrows():
        if "geo" in row and "value" in row:
            population_map[row["geo"]] = float(row["value"])
    
    return population_map

@st.cache_data(show_spinner=False, ttl=86400)
def get_nuts3_unemployed_persons(nuts3_codes: List[str], year: str = "2023") -> Dict[str, float]:
    """Get total unemployed persons for NUTS3 regions"""
    if not nuts3_codes:
        return {}
    
    filters = {
        "geo": nuts3_codes,
        "time": [year],
        "age": ["Y15-74"],
        "sex": ["T"],
        "unit": ["THS_PER"]  # Thousand persons
    }
    
    df = fetch_eurostat_data(UNEMPLOYMENT_DATASET, filters)
    
    if df.empty:
        filters["time"] = [str(int(year) - 1)]
        df = fetch_eurostat_data(UNEMPLOYMENT_DATASET, filters)
    
    unemployed_map = {}
    for _, row in df.iterrows():
        if "geo" in row and "value" in row:
            unemployed_map[row["geo"]] = float(row["value"]) * 1000  # Convert from thousands
    
    return unemployed_map

@st.cache_data(show_spinner=False, ttl=86400)
def get_nuts3_active_population(nuts3_codes: List[str], year: str = "2023") -> Dict[str, float]:
    """Get active population for NUTS3 regions"""
    if not nuts3_codes:
        return {}
    
    filters = {
        "geo": nuts3_codes,
        "time": [year],
        "age": ["Y15-74"],
        "sex": ["T"],
        "unit": ["THS_PER"]
    }
    
    df = fetch_eurostat_data(ACTIVE_POP_DATASET, filters)
    
    if df.empty:
        filters["time"] = [str(int(year) - 1)]
        df = fetch_eurostat_data(ACTIVE_POP_DATASET, filters)
    
    active_map = {}
    for _, row in df.iterrows():
        if "geo" in row and "value" in row:
            active_map[row["geo"]] = float(row["value"]) * 1000
    
    return active_map

def calculate_catchment_area(site_lat: float, site_lon: float, radius_km: float = 50, year: str = "2023") -> Dict[str, Any]:
    """Calculate catchment area statistics with total unemployed persons"""
    results = {
        "catchment_radius_km": radius_km,
        "total_population": 0,
        "unemployed_persons": 0,
        "active_population": 0,
        "employed_persons": 0,
        "nuts3_regions": [],
        "data_year": year
    }
    
    try:
        nuts3_idx = load_nuts3_index()
        
        if not nuts3_idx.get("ok"):
            return results
        
        nearby_nuts3 = []
        nearby_distances = []
        
        for i, geom in enumerate(nuts3_idx["geoms"]):
            try:
                centroid = geom.centroid
                dist_km = haversine_km(site_lat, site_lon, centroid.y, centroid.x)
                
                if dist_km <= radius_km:
                    nuts3_code = nuts3_idx["props"][i].get("NUTS_ID")
                    if nuts3_code:
                        nearby_nuts3.append(nuts3_code)
                        nearby_distances.append(dist_km)
            except:
                continue
        
        if not nearby_nuts3:
            containing = nuts3_lookup(site_lat, site_lon)
            if containing and containing.get("NUTS_ID"):
                nearby_nuts3 = [containing["NUTS_ID"]]
                nearby_distances = [0]
        
        if nearby_nuts3:
            pop_data = get_nuts3_population(nearby_nuts3, year)
            unemployed_data = get_nuts3_unemployed_persons(nearby_nuts3, year)
            active_pop_data = get_nuts3_active_population(nearby_nuts3, year)
            
            total_pop = 0
            total_unemployed = 0
            total_active = 0
            weights = []
            
            for nuts3_code, dist in zip(nearby_nuts3, nearby_distances):
                weight = 1.0 / (1.0 + dist / 10.0)
                weights.append(weight)
                
                if nuts3_code in pop_data:
                    total_pop += pop_data[nuts3_code] * weight
                
                if nuts3_code in unemployed_data:
                    total_unemployed += unemployed_data[nuts3_code] * weight
                
                if nuts3_code in active_pop_data:
                    total_active += active_pop_data[nuts3_code] * weight
                elif nuts3_code in pop_data:
                    total_active += pop_data[nuts3_code] * 0.65 * weight
            
            if weights:
                total_weight = sum(weights)
                total_pop = total_pop / total_weight
                total_unemployed = total_unemployed / total_weight
                total_active = total_active / total_weight
            
            results["total_population"] = int(total_pop)
            results["unemployed_persons"] = int(total_unemployed)
            results["active_population"] = int(total_active)
            results["employed_persons"] = int(total_active - total_unemployed)
            results["nuts3_regions"] = nearby_nuts3[:5]
    except:
        pass
    
    return results

# ---------------------- OSM Geocoding ----------------------
@st.cache_data(show_spinner=False)
def osm_reverse(lat: float, lon: float) -> Dict[str, Any]:
    """Reverse geocode coordinates to get administrative information"""
    params = {"format": "jsonv2", "lat": float(lat), "lon": float(lon), "addressdetails": 1, "extratags": 1}
    headers = {"User-Agent": "RoadDistanceFinder/2.0"}
    try:
        r = requests.get(NOMINATIM_REVERSE, params=params, headers=headers, timeout=12)
        r.raise_for_status()
        data = r.json()
        addr = data.get("address", {})
        ex = data.get("extratags", {})
        municipality = addr.get("municipality") or addr.get("city") or addr.get("town") or addr.get("village") or addr.get("suburb")
        county = addr.get("county") or addr.get("state_district")
        voivodeship = addr.get("state")
        muni_code = ex.get("ref:teryt:simc") or ex.get("ref:teryt") or ""
        county_code = ex.get("ref:teryt:powiat") or ""
        voiv_code = ex.get("ref:teryt:wojewodztwo") or addr.get("ISO3166-2-lvl4") or ""
        return {
            "municipality": municipality or "",
            "municipality_code": muni_code,
            "county": county or "",
            "county_code": county_code,
            "voivodeship": voivodeship or "",
            "voivodeship_code": voiv_code,
        }
    except:
        return {"municipality": "", "municipality_code": "", "county": "", "county_code": "", 
                "voivodeship": "", "voivodeship_code": ""}

@st.cache_data(show_spinner=False)
def osm_search(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Search for places by name"""
    if not query:
        return []
    params = {"q": query, "format": "json", "addressdetails": 1, "limit": limit}
    headers = {"User-Agent": "RoadDistanceFinder/2.0"}
    try:
        r = requests.get(NOMINATIM_SEARCH, params=params, headers=headers, timeout=12)
        r.raise_for_status()
        results = r.json()
        out = []
        for res in results:
            try:
                out.append({
                    "display_name": str(res.get("display_name", "")), 
                    "lat": float(res.get("lat")), 
                    "lon": float(res.get("lon"))
                })
            except:
                continue
        return out
    except:
        return []

# ---------------------- OSRM Routing ----------------------
def route_via_osrm(origin: Tuple[float, float], dest: Tuple[float, float], timeout_s: int = 20) -> Tuple[float, float]:
    """Get road distance and time via OSRM"""
    url = OSRM_URL.format(lon1=origin[1], lat1=origin[0], lon2=dest[1], lat2=dest[0])
    r = requests.get(url, timeout=timeout_s)
    if r.status_code != 200:
        raise RuntimeError(f"OSRM HTTP {r.status_code}")
    data = r.json()
    if data.get("code") != "Ok":
        raise RuntimeError(f"OSRM error: {data.get('code')}")
    route = data["routes"][0]
    dist_km = float(route["distance"]) / 1000.0
    dur_min = float(route["duration"]) / 60.0
    return dist_km, dur_min

@st.cache_data(show_spinner=False)
def _route_key(origin: Tuple[float, float], dest: Tuple[float, float]) -> str:
    return f"OSRM:{origin[0]:.6f},{origin[1]:.6f}->{dest[0]:.6f},{dest[1]:.6f}"

def get_route(origin: Tuple[float, float], dest: Tuple[float, float], route_cache: Dict = None) -> Tuple[float, float]:
    """Get route with caching"""
    if route_cache is None:
        route_cache = {}
    key = _route_key(origin, dest)
    if key in route_cache:
        v = route_cache[key]
        return v["distance_km"], v["duration_min"]
    dist_km, dur_min = route_via_osrm(origin, dest)
    route_cache[key] = {"distance_km": dist_km, "duration_min": dur_min}
    return dist_km, dur_min

# ---------------------- National Admin Boundaries ----------------------
class AdminIndex:
    def __init__(self, geoms: List[Any], props: List[Dict[str, Any]]):
        self.geoms = geoms
        self.props = props
        self.tree = STRtree(geoms) if (geoms and _HAS_SHAPELY) else None

    def lookup(self, lat: float, lon: float) -> Dict[str, Any]:
        if not self.tree:
            return {}
        pt = Point(float(lon), float(lat))
        try:
            cands = self.tree.query(pt)
        except:
            cands = []
        for g in cands:
            try:
                if g.covers(pt) or g.contains(pt) or g.intersects(pt):
                    try:
                        ix = self.geoms.index(g)
                    except:
                        ix = None
                    if ix is not None:
                        return self.props[ix]
            except:
                continue
        for ix, g in enumerate(self.geoms):
            try:
                if g.covers(pt) or g.contains(pt) or g.intersects(pt):
                    return self.props[ix]
            except:
                continue
        return {}

def build_admin_index_from_geojson(gj: Dict[str, Any], code_field: str, name_field: str, 
                                  alt_code_fields=None, alt_name_fields=None) -> Optional[AdminIndex]:
    if not _HAS_SHAPELY:
        return None
    try:
        geoms = []
        props = []
        for feat in gj.get("features", []):
            pr = feat.get("properties", {})
            try:
                g = shape(feat.get("geometry"))
                if g.is_empty:
                    continue
                code_val = pr.get(code_field)
                name_val = pr.get(name_field)
                if (not code_val) and alt_code_fields:
                    for cf in alt_code_fields:
                        if pr.get(cf):
                            code_val = pr.get(cf)
                            break
                if (not name_val) and alt_name_fields:
                    for nf in alt_name_fields:
                        if pr.get(nf):
                            name_val = pr.get(nf)
                            break
                geoms.append(g)
                props.append({"code": str(code_val or ""), "name": str(name_val or "")})
            except:
                continue
        if not geoms:
            return None
        return AdminIndex(geoms, props)
    except:
        return None

@st.cache_resource(show_spinner=False)
def load_official_PL() -> Dict[str, Any]:
    """Load Polish administrative boundaries"""
    if not _HAS_SHAPELY:
        return {}
    urls = {
        "gmina": "https://mapy.geoportal.gov.pl/wss/service/PZGIK/PRG/WFS/AdministrativeBoundaries?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature&TYPENAMES=prg:gminy&OUTPUTFORMAT=application/json",
        "powiat": "https://mapy.geoportal.gov.pl/wss/service/PZGIK/PRG/WFS/AdministrativeBoundaries?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature&TYPENAMES=prg:powiaty&OUTPUTFORMAT=application/json",
        "woj": "https://mapy.geoportal.gov.pl/wss/service/PZGIK/PRG/WFS/AdministrativeBoundaries?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature&TYPENAMES=prg:wojewodztwa&OUTPUTFORMAT=application/json",
    }
    out = {}
    for level, url in urls.items():
        try:
            r = requests.get(url, timeout=60)
            r.raise_for_status()
            gj = r.json()
            idx = build_admin_index_from_geojson(
                gj, code_field="JPT_KOD_JE", name_field="JPT_NAZWA_",
                alt_code_fields=["TERYT", "TERC"], alt_name_fields=["NAZWA"]
            )
            if idx:
                out[level] = idx
        except:
            continue
    return out

if "official_admin" not in st.session_state:
    st.session_state["official_admin"] = load_official_PL()
    st.session_state["official_admin_country"] = "PL"

@st.cache_resource(show_spinner=False)
def load_index_from_url(url: str, code_field: str, name_field: str, 
                        alt_code_fields: List[str] = None, alt_name_fields: List[str] = None) -> Optional[AdminIndex]:
    try:
        r = requests.get(url, timeout=90)
        r.raise_for_status()
        gj = r.json()
        return build_admin_index_from_geojson(gj, code_field, name_field, alt_code_fields, alt_name_fields)
    except:
        return None

# ---------------------- Validation ----------------------
def _validate_columns(df: pd.DataFrame, required_cols: List[str]) -> List[str]:
    return [c for c in required_cols if c not in df.columns]

def _validate_latlon(lat: pd.Series, lon: pd.Series) -> str:
    try:
        if not (np.isfinite(lat).all() and np.isfinite(lon).all()):
            return "Latitude/Longitude contain non-numeric values"
        if not (((lat >= -90) & (lat <= 90)).all() and ((lon >= -180) & (lon <= 180)).all()):
            return "Latitude must be in [-90,90] and Longitude in [-180,180]"
        return ""
    except:
        return "Latitude/Longitude validation failed"

# ---------------------- Main Processing Function ----------------------
def process_batch(
    sites: pd.DataFrame,
    airports: pd.DataFrame,
    seaports: pd.DataFrame,
    topn: int,
    include_ref: bool,
    ref_lat: float,
    ref_lon: float,
    ref_name: str,
    pause_every: int,
    pause_secs: float,
    progress_hook=None,
    enrich_nuts3: bool = True,
    enrich_osm_admin: bool = True,
    include_highway: bool = True,
    include_catchment: bool = True,
    catchment_radius: float = 50,
) -> Tuple[pd.DataFrame, List[Dict[str, Any]], int]:
    """Main processing function with all features"""
    
    sites = sites.copy()
    airports = airports.copy()
    seaports = seaports.copy()
    
    # Coerce numeric
    for col in ["Latitude", "Longitude"]:
        sites[col] = pd.to_numeric(sites[col], errors="coerce")
        airports[col] = pd.to_numeric(airports[col], errors="coerce")
        seaports[col] = pd.to_numeric(seaports[col], errors="coerce")
    
    # Validate
    err = (_validate_latlon(sites["Latitude"], sites["Longitude"]) or
           _validate_latlon(airports["Latitude"], airports["Longitude"]) or
           _validate_latlon(seaports["Latitude"], seaports["Longitude"]))
    if err:
        raise ValueError(err)
    
    a_lat = airports["Latitude"].to_numpy()
    a_lon = airports["Longitude"].to_numpy()
    p_lat = seaports["Latitude"].to_numpy()
    p_lon = seaports["Longitude"].to_numpy()
    
    route_cache = st.session_state.get("route_cache", {})
    results = []
    logs = []
    api_calls = 0
    total = len(sites)
    
    for idx, row in sites.iterrows():
        project_id = str(row.get("Project ID", "")).strip()
        site_id = str(row.get("Site ID", "")).strip()
        site_name = str(row["Site Name"]).strip()
        slat = float(row["Latitude"])
        slon = float(row["Longitude"])
        site_origin = (slat, slon)
        
        log_rec = {"site": site_name, "steps": []}
        out_rec = {
            "Project ID": project_id,
            "Site ID": site_id,
            "Site Name": site_name,
            "Latitude": round(slat, 6),
            "Longitude": round(slon, 6),
            "Nearest Airport": None,
            "Nearest Airport Code": None,
            "Distance to Airport (km)": None,
            "Time to Airport (min)": None,
            "Nearest Seaport": None,
            "Distance to Seaport (km)": None,
            "Time to Seaport (min)": None,
            "Nearest Highway Access": None,
            "Distance to Highway (km)": None,
            "Time to Highway (min)": None,
            "Municipality": None,
            "Municipality Code": None,
            "County": None,
            "County Code": None,
            "Voivodeship": None,
            "Voivodeship Code": None,
            "NUTS2 Code": None,
            "NUTS2 Name": None,
            "NUTS3 Code": None,
            "NUTS3 Name": None,
        }
        
        # Add catchment fields
        if include_catchment:
            out_rec[f"Catchment Population ({int(catchment_radius)}km)"] = None
            out_rec[f"Catchment Unemployed ({int(catchment_radius)}km)"] = None
            out_rec[f"Catchment Active Pop ({int(catchment_radius)}km)"] = None
            out_rec[f"Catchment Employed ({int(catchment_radius)}km)"] = None
            out_rec["Catchment NUTS3 Regions"] = None
        
        if include_ref:
            out_rec[f"Distance to {ref_name} (km)"] = None
            out_rec[f"Time to {ref_name} (min)"] = None
        
        # Add nearest city (100k+) fields
        out_rec["Nearest City (100k+)"] = None
        out_rec["City Population"] = None
        out_rec["Distance to City (km)"] = None
        out_rec["Time to City (min)"] = None
        
        try:
            # Find nearest airport
            dists_a = haversine_km(slat, slon, a_lat, a_lon)
            idxs_a = np.argsort(dists_a)[:min(topn, len(airports))]
            cand_airports = airports.iloc[idxs_a].copy()
            
            best_air, best_air_d, best_air_t = None, math.inf, math.inf
            for _, a in cand_airports.iterrows():
                dest = (float(a["Latitude"]), float(a["Longitude"]))
                try:
                    if api_calls and pause_every and api_calls % pause_every == 0:
                        if progress_hook:
                            progress_hook(f"Pausing {pause_secs}s...")
                        time.sleep(pause_secs)
                    dist_km, dur_min = get_route(site_origin, dest, route_cache=route_cache)
                    api_calls += 1
                    if dist_km < best_air_d:
                        best_air, best_air_d, best_air_t = a, dist_km, dur_min
                except Exception as e:
                    log_rec["steps"].append({"error": f"Airport '{a['Airport Name']}': {e}"})
            
            if best_air is not None:
                out_rec["Nearest Airport"] = str(best_air.get("Airport Name"))
                out_rec["Nearest Airport Code"] = str(best_air.get("IATA") or best_air.get("ICAO") or "")
                out_rec["Distance to Airport (km)"] = round(best_air_d, 1)
                out_rec["Time to Airport (min)"] = round(best_air_t, 1)
            
            # Find nearest seaport
            dists_p = haversine_km(slat, slon, p_lat, p_lon)
            idxs_p = np.argsort(dists_p)[:min(topn, len(seaports))]
            cand_ports = seaports.iloc[idxs_p].copy()
            
            best_port, best_port_d, best_port_t = None, math.inf, math.inf
            for _, p in cand_ports.iterrows():
                dest = (float(p["Latitude"]), float(p["Longitude"]))
                try:
                    if api_calls and pause_every and api_calls % pause_every == 0:
                        if progress_hook:
                            progress_hook(f"Pausing {pause_secs}s...")
                        time.sleep(pause_secs)
                    dist_km, dur_min = get_route(site_origin, dest, route_cache=route_cache)
                    api_calls += 1
                    if dist_km < best_port_d:
                        best_port, best_port_d, best_port_t = p, dist_km, dur_min
                except Exception as e:
                    log_rec["steps"].append({"error": f"Seaport '{p['Seaport Name']}': {e}"})
            
            if best_port is not None:
                out_rec["Nearest Seaport"] = str(best_port.get("Seaport Name"))
                out_rec["Distance to Seaport (km)"] = round(best_port_d, 1)
                out_rec["Time to Seaport (min)"] = round(best_port_t, 1)
            
            # Highway distance
            if include_highway:
                try:
                    if api_calls and pause_every and api_calls % pause_every == 0:
                        if progress_hook:
                            progress_hook(f"Pausing {pause_secs}s...")
                        time.sleep(pause_secs)
                    
                    highway_dist, highway_time, highway_name = get_highway_distance(slat, slon, route_cache=route_cache)
                    api_calls += 1
                    
                    if highway_dist is not None:
                        out_rec["Nearest Highway Access"] = highway_name
                        out_rec["Distance to Highway (km)"] = round(highway_dist, 1)
                        if highway_time is not None:
                            out_rec["Time to Highway (min)"] = round(highway_time, 1)
                except Exception as e:
                    log_rec["steps"].append({"error": f"Highway: {e}"})
            
            # Reference distance
            if include_ref:
                try:
                    if api_calls and pause_every and api_calls % pause_every == 0:
                        if progress_hook:
                            progress_hook(f"Pausing {pause_secs}s...")
                        time.sleep(pause_secs)
                    dist_km, dur_min = get_route(site_origin, (ref_lat, ref_lon), route_cache=route_cache)
                    api_calls += 1
                    out_rec[f"Distance to {ref_name} (km)"] = round(dist_km, 1)
                    out_rec[f"Time to {ref_name} (min)"] = round(dur_min, 1)
                except Exception as e:
                    log_rec["steps"].append({"error": f"Reference: {e}"})
            
            # Nearest city (100k+ population)
            if _HAS_CITIES_DB:
                try:
                    city_info = get_nearest_city(slat, slon, max_distance=200)
                    if city_info is not None and city_info.get("name"):
                        city_name = city_info.get("name")
                        city_pop = city_info.get("pop", 0)
                        city_lat = float(city_info.get("lat"))
                        city_lon = float(city_info.get("lon"))
                        
                        out_rec["Nearest City (100k+)"] = city_name
                        out_rec["City Population"] = int(city_pop) if city_pop else None
                        
                        try:
                            # Calculate route distance to city
                            if api_calls and pause_every and api_calls % pause_every == 0:
                                if progress_hook:
                                    progress_hook(f"Pausing {pause_secs}s...")
                                time.sleep(pause_secs)
                            
                            dist_km, dur_min = get_route(site_origin, (city_lat, city_lon), route_cache=route_cache)
                            api_calls += 1
                            
                            out_rec["Distance to City (km)"] = round(dist_km, 1)
                            out_rec["Time to City (min)"] = round(dur_min, 1)
                            
                            # Format log message safely
                            pop_str = f"{int(city_pop):,}" if city_pop else "unknown"
                            log_rec["steps"].append({"msg": f"Nearest city: {city_name} ({pop_str} pop), {dist_km:.1f} km, {dur_min:.0f} min"})
                        except Exception as route_err:
                            log_rec["steps"].append({"error": f"Route to {city_name}: {str(route_err)}"})
                    else:
                        log_rec["steps"].append({"msg": "No nearby city found within 200km"})
                except Exception as e:
                    log_rec["steps"].append({"error": f"Nearest City lookup: {str(e)}"})
            
            # NUTS enrichment
            if _HAS_SHAPELY:
                try:
                    n2 = nuts2_lookup(slat, slon)
                    if n2:
                        out_rec["NUTS2 Code"] = n2.get("NUTS_ID")
                        out_rec["NUTS2 Name"] = n2.get("NAME_LATN")
                except:
                    pass
                
                try:
                    n3 = nuts3_lookup(slat, slon)
                    if n3:
                        out_rec["NUTS3 Code"] = n3.get("NUTS_ID")
                        out_rec["NUTS3 Name"] = n3.get("NAME_LATN")
                except:
                    pass
            
            # Catchment area
            if include_catchment:
                try:
                    catchment = calculate_catchment_area(slat, slon, radius_km=catchment_radius)
                    
                    if catchment["total_population"] > 0:
                        out_rec[f"Catchment Population ({int(catchment_radius)}km)"] = catchment["total_population"]
                        out_rec[f"Catchment Unemployed ({int(catchment_radius)}km)"] = catchment["unemployed_persons"]
                        out_rec[f"Catchment Active Pop ({int(catchment_radius)}km)"] = catchment["active_population"]
                        out_rec[f"Catchment Employed ({int(catchment_radius)}km)"] = catchment["employed_persons"]
                        out_rec["Catchment NUTS3 Regions"] = ", ".join(catchment["nuts3_regions"][:3])
                except:
                    pass
            
            # Admin boundaries
            have_official = False
            try:
                auto = st.session_state.get("official_admin", {})
                idx_woj = auto.get("woj")
                idx_pow = auto.get("powiat")
                idx_gmi = auto.get("gmina")
                
                if idx_woj:
                    w = idx_woj.lookup(slat, slon)
                    if w:
                        out_rec["Voivodeship"] = w.get("name")
                        out_rec["Voivodeship Code"] = w.get("code")
                        have_official = True
                
                if idx_pow:
                    p = idx_pow.lookup(slat, slon)
                    if p:
                        out_rec["County"] = p.get("name")
                        out_rec["County Code"] = p.get("code")
                        have_official = True
                
                if idx_gmi:
                    g = idx_gmi.lookup(slat, slon)
                    if g:
                        out_rec["Municipality"] = g.get("name")
                        out_rec["Municipality Code"] = g.get("code")
                        have_official = True
            except:
                pass
            
            if enrich_osm_admin and not have_official:
                try:
                    adm = osm_reverse(slat, slon)
                    out_rec["Municipality"] = adm.get("municipality") or out_rec.get("Municipality")
                    out_rec["Municipality Code"] = adm.get("municipality_code") or out_rec.get("Municipality Code")
                    out_rec["County"] = adm.get("county") or out_rec.get("County")
                    out_rec["County Code"] = adm.get("county_code") or out_rec.get("County Code")
                    out_rec["Voivodeship"] = adm.get("voivodeship") or out_rec.get("Voivodeship")
                    out_rec["Voivodeship Code"] = adm.get("voivodeship_code") or out_rec.get("Voivodeship Code")
                except:
                    pass
        
        except Exception as e:
            log_rec["steps"].append({"fatal": str(e)})
        
        logs.append(log_rec)
        results.append(out_rec)
        
        if progress_hook:
            progress_hook(f"Processed {len(results)}/{total}")
    
    st.session_state["route_cache"] = route_cache
    df_res = pd.DataFrame(results)
    return df_res, logs, api_calls

# ---------------------- UI Components ----------------------
def sidebar():
    """Sidebar with all configuration options"""
    st.sidebar.header("⚙️ Settings")

    # Dataset status
    with st.sidebar.expander("📊 Dataset Status", expanded=False):
        active_iso = st.session_state.get("official_admin_country", "PL")
        st.markdown(f"**Active national source**: `{active_iso}`")
        oa = st.session_state.get("official_admin", {})
        st.markdown(f"**LAU/municipalities**: {'✅ Ready' if oa.get('gmina') else '❌ Not available'}")
        st.markdown(f"**Counties**: {'✅ Ready' if oa.get('powiat') else '❌ Not available'}")
        st.markdown(f"**Regions**: {'✅ Ready' if oa.get('woj') else '❌ Not available'}")
        
        n2 = load_nuts2_index()
        n3 = load_nuts3_index()
        st.markdown(f"**NUTS-2**: {'✅ ' + str(n2.get('count', 0)) + ' regions' if n2.get('ok') else '❌ Failed'}")
        st.markdown(f"**NUTS-3**: {'✅ ' + str(n3.get('count', 0)) + ' regions' if n3.get('ok') else '❌ Failed'}")

    # Reference location
    st.sidebar.subheader("📍 Reference Location")
    ref_search = st.sidebar.text_input("Search by name (OpenStreetMap)", value="")
    if st.sidebar.button("🔍 Search") and ref_search.strip():
        preds = osm_search(ref_search.strip(), limit=8)
        if not preds:
            st.sidebar.warning("No results found")
        else:
            labels = [p["display_name"] for p in preds]
            choice = st.sidebar.selectbox("Select place", labels, index=0)
            if choice:
                det = preds[labels.index(choice)]
                st.session_state["ref_name"] = det.get("display_name", DEFAULT_REF["name"])
                st.session_state["ref_lat"] = det.get("lat")
                st.session_state["ref_lon"] = det.get("lon")
                st.sidebar.success("✅ Reference updated")

    use_ref = st.sidebar.checkbox("Calculate reference distance", value=True)
    ref_name = st.sidebar.text_input("Reference name", 
                                     value=st.session_state.get("ref_name", DEFAULT_REF['name']), 
                                     key="ref_name")
    ref_lat = st.sidebar.number_input("Latitude", 
                                      value=float(st.session_state.get("ref_lat", DEFAULT_REF['lat'])), 
                                      format="%.6f", key="ref_lat")
    ref_lon = st.sidebar.number_input("Longitude", 
                                      value=float(st.session_state.get("ref_lon", DEFAULT_REF['lon'])), 
                                      format="%.6f", key="ref_lon")

    # Processing options
    st.sidebar.subheader("🎯 Processing Options")
    topn = st.sidebar.slider("Top-N candidates", min_value=1, max_value=10, value=3,
                             help="Number of nearest facilities to check by road distance")
    
    # Feature toggles
    st.sidebar.subheader("✨ Features")
    include_highway = st.sidebar.checkbox("🛣️ Highway distance", value=True,
                                          help="Calculate distance to nearest highway/expressway")
    include_catchment = st.sidebar.checkbox("👥 Catchment analysis", value=True,
                                           help="Analyze population and labor market in surrounding area")
    
    catchment_radius = 50
    if include_catchment:
        catchment_radius = st.sidebar.slider("Catchment radius (km)", 
                                            min_value=10, max_value=100, value=50, step=10)
    
    enrich_osm_admin = st.sidebar.checkbox("🏛️ Admin boundaries", value=True,
                                          help="Add municipality/county/region information")

    # Rate limiting
    st.sidebar.subheader("⏱️ Rate Limiting")
    pause_every = st.sidebar.number_input("Pause after N calls", min_value=0, max_value=100, value=0,
                                         help="0 = no pausing")
    pause_secs = st.sidebar.number_input("Pause duration (seconds)", min_value=0.0, max_value=30.0, 
                                        value=0.0, step=1.0)

    # Admin data loader
    with st.sidebar.expander("🌍 Load Custom Admin Data"):
        iso2 = st.text_input("Country ISO-2", value=st.session_state.get("official_admin_country", "PL"), 
                           max_chars=2).upper()
        url_g = st.text_input("Municipalities GeoJSON URL", value="")
        url_p = st.text_input("Counties GeoJSON URL", value="")
        url_w = st.text_input("Regions GeoJSON URL", value="")
        code_field = st.text_input("Code field name", value="")
        name_field = st.text_input("Name field name", value="")
        if st.button("Load Data") and code_field and name_field:
            new_idx = {}
            if url_g:
                idxg = load_index_from_url(url_g, code_field, name_field)
                if idxg: new_idx["gmina"] = idxg
            if url_p:
                idxp = load_index_from_url(url_p, code_field, name_field)
                if idxp: new_idx["powiat"] = idxp
            if url_w:
                idxw = load_index_from_url(url_w, code_field, name_field)
                if idxw: new_idx["woj"] = idxw
            if new_idx:
                st.session_state["official_admin"] = new_idx
                st.session_state["official_admin_country"] = iso2
                st.success("✅ Admin data loaded")

    # Test connectivity
    if st.sidebar.button("🧪 Test OSRM Connection"):
        try:
            o = (DEFAULT_REF['lat'], DEFAULT_REF['lon'])
            d = (50.1109, 8.6821)
            dist_km, dur_min = route_via_osrm(o, d)
            st.sidebar.success(f"✅ Connected: {dist_km:.1f} km, {dur_min:.0f} min")
        except Exception as e:
            st.sidebar.error(f"❌ Failed: {str(e)[:100]}")

    # Cache management
    if st.sidebar.button("🗑️ Clear Route Cache"):
        st.session_state["route_cache"] = {}
        st.sidebar.success("✅ Cache cleared")

    return (topn, pause_every, pause_secs, use_ref, ref_name, ref_lat, ref_lon, 
            enrich_osm_admin, include_highway, include_catchment, catchment_radius)

def download_buttons_area():
    """Template download section"""
    st.subheader("📁 Templates")
    st.caption("Download Excel templates with correct headers and example data")
    
    files = template_files()
    cols = st.columns(3)
    
    with cols[0]:
        st.download_button("📋 Sites.xlsx", data=files["Sites.xlsx"], 
                          file_name="Sites.xlsx", use_container_width=True)
    with cols[1]:
        st.download_button("✈️ Airports.xlsx", data=files["Airports.xlsx"], 
                          file_name="Airports.xlsx", use_container_width=True)
    with cols[2]:
        st.download_button("🚢 Seaports.xlsx", data=files["Seaports.xlsx"], 
                          file_name="Seaports.xlsx", use_container_width=True)

def upload_area() -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """File upload section"""
    st.subheader("📤 Upload Your Data")
    
    c1, c2, c3 = st.columns(3)
    sites_file = c1.file_uploader("Sites.xlsx", type=["xlsx"], key="sites_up")
    airports_file = c2.file_uploader("Airports.xlsx", type=["xlsx"], key="airports_up")
    seaports_file = c3.file_uploader("Seaports.xlsx", type=["xlsx"], key="seaports_up")

    sites_df = airports_df = seaports_df = None

    def _read_xlsx(up: UploadedFile, sheet: str) -> pd.DataFrame:
        return pd.read_excel(up, engine="openpyxl", sheet_name=sheet)

    if sites_file is not None:
        try:
            sites_df = _read_xlsx(sites_file, "Sites")
            miss = _validate_columns(sites_df, REQUIRED_SITES_COLS)
            if miss:
                st.error(f"❌ Sites.xlsx missing: {', '.join(miss)}")
                sites_df = None
            else:
                c1.success(f"✅ {len(sites_df)} sites loaded")
        except Exception as e:
            st.error(f"❌ Error reading Sites.xlsx: {str(e)}")

    if airports_file is not None:
        try:
            airports_df = _read_xlsx(airports_file, "Airports")
            miss = _validate_columns(airports_df, REQUIRED_AIRPORTS_COLS)
            if miss:
                st.error(f"❌ Airports.xlsx missing: {', '.join(miss)}")
                airports_df = None
            else:
                c2.success(f"✅ {len(airports_df)} airports loaded")
        except Exception as e:
            st.error(f"❌ Error reading Airports.xlsx: {str(e)}")

    if seaports_file is not None:
        try:
            seaports_df = _read_xlsx(seaports_file, "Seaports")
            miss = _validate_columns(seaports_df, REQUIRED_SEAPORTS_COLS)
            if miss:
                st.error(f"❌ Seaports.xlsx missing: {', '.join(miss)}")
                seaports_df = None
            else:
                c3.success(f"✅ {len(seaports_df)} seaports loaded")
        except Exception as e:
            st.error(f"❌ Error reading Seaports.xlsx: {str(e)}")

    return sites_df, airports_df, seaports_df

def results_downloads(df: pd.DataFrame, ref_name: str = None, catchment_radius: int = 50, 
                     filename_prefix: str = "results"):
    """Download section with multiple export formats"""
    st.subheader("💾 Download Results")
    
    col1, col2, col3 = st.columns(3)
    
    # CSV export
    with col1:
        csv_bytes = df.to_csv(index=False).encode("utf-8")
        st.download_button("📄 CSV Format", data=csv_bytes, 
                          file_name=f"{filename_prefix}.csv",
                          use_container_width=True)
    
    # Excel export
    with col2:
        bio = io.BytesIO()
        with pd.ExcelWriter(bio, engine="xlsxwriter") as xw:
            df.to_excel(xw, index=False, sheet_name="Results")
        st.download_button("📊 Excel Format", data=bio.getvalue(), 
                          file_name=f"{filename_prefix}.xlsx",
                          use_container_width=True)
    
    # Site Selection Tool format
    with col3:
        df_long = create_site_selection_format(df, ref_name=ref_name, catchment_radius=catchment_radius)
        bio_long = io.BytesIO()
        with pd.ExcelWriter(bio_long, engine="xlsxwriter") as xw:
            df_long.to_excel(xw, index=False, sheet_name="SiteSelection")
        st.download_button("🎯 Site Selection Format", 
                          data=bio_long.getvalue(),
                          file_name=f"{filename_prefix}_site_selection.xlsx",
                          help="Long format with one row per site-destination pair",
                          use_container_width=True)

def display_catchment_summary(df: pd.DataFrame, catchment_radius: int):
    """Display catchment area summary statistics"""
    st.subheader("👥 Labor Market Analysis")
    
    # Calculate totals
    pop_col = f"Catchment Population ({catchment_radius}km)"
    unemployed_col = f"Catchment Unemployed ({catchment_radius}km)"
    active_col = f"Catchment Active Pop ({catchment_radius}km)"
    employed_col = f"Catchment Employed ({catchment_radius}km)"
    
    if pop_col in df.columns:
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            total_pop = df[pop_col].sum()
            st.metric("Total Population", f"{total_pop:,.0f}")
        
        with col2:
            if unemployed_col in df.columns:
                total_unemployed = df[unemployed_col].sum()
                st.metric("Total Unemployed", f"{total_unemployed:,.0f}")
        
        with col3:
            if active_col in df.columns:
                total_active = df[active_col].sum()
                st.metric("Total Active Population", f"{total_active:,.0f}")
        
        with col4:
            if employed_col in df.columns:
                total_employed = df[employed_col].sum()
                st.metric("Total Employed", f"{total_employed:,.0f}")
        
        # Create ranking table
        st.subheader("📊 Site Rankings by Labor Market Potential")
        
        summary_data = []
        for _, row in df.iterrows():
            if pop_col in row:
                summary_data.append({
                    "Site": row["Site Name"],
                    "Population": row.get(pop_col, 0),
                    "Unemployed": row.get(unemployed_col, 0),
                    "Active Pop": row.get(active_col, 0),
                    "Score": 0
                })
        
        if summary_data:
            summary_df = pd.DataFrame(summary_data)
            
            # Calculate score
            if summary_df["Population"].max() > 0:
                max_pop = summary_df["Population"].max()
                max_unemployed = summary_df["Unemployed"].max() if summary_df["Unemployed"].max() > 0 else 1
                
                summary_df["Score"] = (
                    (summary_df["Population"] / max_pop) * 60 +
                    (summary_df["Unemployed"] / max_unemployed) * 40
                )
                summary_df["Score"] = summary_df["Score"].round(1)
                summary_df = summary_df.sort_values("Score", ascending=False)
                
                st.dataframe(summary_df, use_container_width=True, hide_index=True)

def maybe_map(df: pd.DataFrame, airports: pd.DataFrame, seaports: pd.DataFrame):
    """Create interactive map with all locations"""
    if not _HAS_MAP:
        st.info("Map preview requires folium and streamlit-folium packages")
        return
    
    if df is None or df.empty:
        return
    
    mean_lat = float(df["Latitude"].mean())
    mean_lon = float(df["Longitude"].mean())
    m = folium.Map(location=[mean_lat, mean_lon], zoom_start=5)
    
    # Add fullscreen button
    try:
        Fullscreen(position="topleft").add_to(m)
    except:
        pass
    
    # Add layer groups
    site_group = folium.FeatureGroup(name="Sites", show=True)
    airport_group = folium.FeatureGroup(name="Airports", show=True)
    seaport_group = folium.FeatureGroup(name="Seaports", show=True)
    
    # Add sites
    for _, r in df.iterrows():
        folium.CircleMarker(
            [float(r["Latitude"]), float(r["Longitude"])],
            radius=5,
            popup=folium.Popup(f"""
                <b>{r['Site Name']}</b><br>
                Project: {r.get('Project ID', '')}<br>
                Site ID: {r.get('Site ID', '')}<br>
                Airport: {r.get('Distance to Airport (km)', 'N/A')} km<br>
                Seaport: {r.get('Distance to Seaport (km)', 'N/A')} km<br>
                Highway: {r.get('Distance to Highway (km)', 'N/A')} km
            """, max_width=300),
            tooltip=str(r["Site Name"]),
            fill=True,
            color='blue',
            fillColor='lightblue'
        ).add_to(site_group)
    
    # Add unique airports
    added_airports = set()
    for _, r in df.iterrows():
        a_name = r.get("Nearest Airport")
        if isinstance(a_name, str) and a_name not in added_airports:
            added_airports.add(a_name)
            arow = airports[airports["Airport Name"] == a_name]
            if not arow.empty:
                alat = float(arow.iloc[0]["Latitude"])
                alon = float(arow.iloc[0]["Longitude"])
                folium.Marker(
                    [alat, alon],
                    icon=folium.Icon(icon="plane", prefix="fa", color='red'),
                    popup=f"✈️ {a_name}",
                    tooltip=f"✈️ {a_name}"
                ).add_to(airport_group)
    
    # Add unique seaports
    added_seaports = set()
    for _, r in df.iterrows():
        p_name = r.get("Nearest Seaport")
        if isinstance(p_name, str) and p_name not in added_seaports:
            added_seaports.add(p_name)
            prow = seaports[seaports["Seaport Name"] == p_name]
            if not prow.empty:
                plat = float(prow.iloc[0]["Latitude"])
                plon = float(prow.iloc[0]["Longitude"])
                folium.Marker(
                    [plat, plon],
                    icon=folium.Icon(icon="ship", prefix="fa", color='darkblue'),
                    popup=f"🚢 {p_name}",
                    tooltip=f"🚢 {p_name}"
                ).add_to(seaport_group)
    
    # Add reference location
    ref_lat = st.session_state.get("ref_lat")
    ref_lon = st.session_state.get("ref_lon")
    ref_name = st.session_state.get("ref_name")
    if isinstance(ref_lat, (int, float)) and isinstance(ref_lon, (int, float)):
        folium.Marker(
            [float(ref_lat), float(ref_lon)],
            icon=folium.Icon(icon="star", color="green"),
            popup=f"⭐ {ref_name}",
            tooltip=f"⭐ Reference: {ref_name}"
        ).add_to(m)
    
    # Add groups to map
    site_group.add_to(m)
    airport_group.add_to(m)
    seaport_group.add_to(m)
    
    # Add layer control
    folium.LayerControl().add_to(m)
    
    st_folium(m, height=500, use_container_width=True)

# ---------------------- Main Application ----------------------
def main():
    st.set_page_config(page_title=APP_TITLE, layout="wide", page_icon="🗺️")
    
    st.title(APP_TITLE)
    st.caption(APP_SUBTITLE)
    
    # Get sidebar settings
    (topn, pause_every, pause_secs, use_ref, ref_name, ref_lat, ref_lon, 
     enrich_osm_admin, include_highway, include_catchment, catchment_radius) = sidebar()
    
    # Templates and upload
    download_buttons_area()
    sites_df, airports_df, seaports_df = upload_area()
    
    # Process button
    run = st.button("🚀 Run Analysis", type="primary", use_container_width=True)
    
    if run:
        if sites_df is None or airports_df is None or seaports_df is None:
            st.error("Please upload all three required files")
            return
        
        if len(sites_df) == 0 or len(airports_df) == 0 or len(seaports_df) == 0:
            st.error("Files must contain at least one row of data")
            return
        
        status = st.empty()
        pbar = st.progress(0)
        
        def progress_hook(msg: str):
            if "Processed" in msg:
                try:
                    parts = msg.split()
                    done = int(parts[1].split("/")[0])
                    total = int(parts[1].split("/")[1])
                    pbar.progress(min(done / max(total, 1), 1.0))
                except:
                    pass
            status.info(msg)
        
        try:
            df_res, logs, api_calls = process_batch(
                sites_df, airports_df, seaports_df,
                topn=int(topn),
                include_ref=use_ref,
                ref_lat=float(ref_lat),
                ref_lon=float(ref_lon),
                ref_name=ref_name,
                pause_every=int(pause_every),
                pause_secs=float(pause_secs),
                progress_hook=progress_hook,
                enrich_nuts3=True,
                enrich_osm_admin=enrich_osm_admin,
                include_highway=include_highway,
                include_catchment=include_catchment,
                catchment_radius=catchment_radius,
            )
            
            pbar.progress(1.0)
            status.success(f"✅ Analysis complete! API calls: {api_calls}, Cached: {len(st.session_state.get('route_cache', {}))}")
            
            # Store results in session
            st.session_state["last_results"] = df_res
            st.session_state["last_logs"] = logs
            st.session_state["last_airports"] = airports_df
            st.session_state["last_seaports"] = seaports_df
            st.session_state["last_ref_name"] = ref_name if use_ref else None
            st.session_state["last_catchment_radius"] = catchment_radius
            
            # Display results
            st.subheader("📊 Results")
            st.dataframe(df_res, use_container_width=True)
            
            # Downloads
            results_downloads(df_res, ref_name=ref_name if use_ref else None, 
                            catchment_radius=int(catchment_radius),
                            filename_prefix="road_distance_results")
            
            # Catchment summary
            if include_catchment:
                display_catchment_summary(df_res, int(catchment_radius))
            
            # Processing log
            with st.expander("📋 Processing Log"):
                for rec in logs:
                    st.write(f"**{rec['site']}**")
                    for step in rec["steps"]:
                        if "msg" in step:
                            st.write(f"- {step['msg']}")
                        if "error" in step:
                            st.error(f"- {step['error']}")
            
            # Map
            if st.checkbox("🗺️ Show Interactive Map", key="show_map"):
                maybe_map(df_res, airports_df, seaports_df)
        
        except Exception as e:
            st.error(f"Processing failed: {str(e)}")
            st.exception(e)
    
    # Show last results if available
    elif st.session_state.get("last_results") is not None:
        df_res = st.session_state["last_results"]
        airports_df = st.session_state.get("last_airports")
        seaports_df = st.session_state.get("last_seaports")
        ref_name_cached = st.session_state.get("last_ref_name")
        catchment_radius_cached = st.session_state.get("last_catchment_radius", 50)
        
        st.subheader("📊 Results (Previous Run)")
        st.dataframe(df_res, use_container_width=True)
        
        results_downloads(df_res, ref_name=ref_name_cached,
                        catchment_radius=catchment_radius_cached,
                        filename_prefix="road_distance_results")
        
        if f"Catchment Population ({catchment_radius_cached}km)" in df_res.columns:
            display_catchment_summary(df_res, catchment_radius_cached)
        
        with st.expander("📋 Processing Log"):
            for rec in st.session_state.get("last_logs", []):
                st.write(f"**{rec['site']}**")
                for step in rec.get("steps", []):
                    if "msg" in step:
                        st.write(f"- {step['msg']}")
                    if "error" in step:
                        st.error(f"- {step['error']}")
        
        if st.checkbox("🗺️ Show Interactive Map", key="show_map"):
            if airports_df is not None and seaports_df is not None:
                maybe_map(df_res, airports_df, seaports_df)

if __name__ == "__main__":
    main()