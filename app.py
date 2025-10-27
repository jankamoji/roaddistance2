# app.py - Road Distance Finder v2.0 (Streamlit)
# Complete version with all features integrated
# Features:
# - Sites/Airports/Seaports distance calculations with Top-N prefilter
# - Nearest City (100k+ population) distance calculations
# - Highway/expressway distance calculations
# - Eurostat population and unemployment catchment areas
# - NUTS2/NUTS3 enrichment (fixed)
# - Project ID and Site ID support
# - Site Selection Tool export format (improved)
# - Reference location labeled as "Outbound"
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

# ---------------------- City database (100k+ population) - All 27 EU Member States ----------------------
MAJOR_CITIES_DB = {
    "DE": [
        {"name": "Berlin", "lat": 52.520008, "lon": 13.404954, "pop": 3644826},
        {"name": "Munich", "lat": 48.135125, "lon": 11.581981, "pop": 1484541},
        {"name": "Frankfurt", "lat": 50.110924, "lon": 8.682127, "pop": 746878},
        {"name": "Hamburg", "lat": 53.550341, "lon": 10.000654, "pop": 1852405},
        {"name": "Cologne", "lat": 50.938361, "lon": 6.959974, "pop": 1097286},
        {"name": "Stuttgart", "lat": 48.775419, "lon": 9.182440, "pop": 623738},
        {"name": "Düsseldorf", "lat": 51.227144, "lon": 6.773602, "pop": 623738},
        {"name": "Dortmund", "lat": 51.514008, "lon": 7.465298, "pop": 587181},
        {"name": "Essen", "lat": 51.454513, "lon": 7.013345, "pop": 581760},
        {"name": "Leipzig", "lat": 51.339695, "lon": 12.373075, "pop": 608322},
        {"name": "Bremen", "lat": 53.074722, "lon": 8.237500, "pop": 563798},
        {"name": "Dresden", "lat": 51.050409, "lon": 13.737262, "pop": 555351},
        {"name": "Hanover", "lat": 52.375892, "lon": 9.735603, "pop": 543669},
        {"name": "Nuremberg", "lat": 49.451993, "lon": 11.076745, "pop": 518365},
        {"name": "Duisburg", "lat": 51.434344, "lon": 6.762779, "pop": 500602},
        {"name": "Bochum", "lat": 51.476086, "lon": 7.225381, "pop": 364760},
        {"name": "Wuppertal", "lat": 51.265430, "lon": 7.184368, "pop": 353798},
        {"name": "Gelsenkirchen", "lat": 51.497916, "lon": 7.095960, "pop": 257620},
        {"name": "Mönchengladbach", "lat": 51.156891, "lon": 6.396752, "pop": 256639},
        {"name": "Aachen", "lat": 50.776351, "lon": 6.083887, "pop": 265130},
        {"name": "Kiel", "lat": 54.323181, "lon": 10.131850, "pop": 247744},
        {"name": "Magdeburg", "lat": 52.131028, "lon": 11.629182, "pop": 238679},
        {"name": "Oberhausen", "lat": 51.465148, "lon": 6.858169, "pop": 210751},
        {"name": "Mannheim", "lat": 49.487613, "lon": 8.466038, "pop": 309370},
        {"name": "Karlsruhe", "lat": 49.006890, "lon": 8.387592, "pop": 308436},
        {"name": "Augsburg", "lat": 48.372114, "lon": 10.898268, "pop": 301143},
        {"name": "Wiesbaden", "lat": 50.082951, "lon": 8.240438, "pop": 287248},
        {"name": "Mülheim", "lat": 51.414219, "lon": 6.885137, "pop": 180620},
        {"name": "Recklinghausen", "lat": 51.610776, "lon": 7.197792, "pop": 109722},
        {"name": "Remscheid", "lat": 51.184545, "lon": 7.198220, "pop": 110040},
    ],
    "PL": [
        {"name": "Warsaw", "lat": 52.229676, "lon": 21.012229, "pop": 1863564},
        {"name": "Krakow", "lat": 50.049683, "lon": 19.944544, "pop": 804237},
        {"name": "Łódź", "lat": 51.779233, "lon": 19.447232, "pop": 672914},
        {"name": "Wrocław", "lat": 51.110093, "lon": 17.038632, "pop": 637075},
        {"name": "Poznań", "lat": 52.406374, "lon": 16.931992, "pop": 535830},
        {"name": "Gdańsk", "lat": 54.372158, "lon": 18.638453, "pop": 461865},
        {"name": "Szczecin", "lat": 53.429889, "lon": 14.552894, "pop": 395105},
        {"name": "Bydgoszcz", "lat": 53.123480, "lon": 18.007880, "pop": 355735},
        {"name": "Lublin", "lat": 51.246595, "lon": 22.566471, "pop": 336779},
        {"name": "Katowice", "lat": 50.264892, "lon": 19.023854, "pop": 299170},
        {"name": "Białystok", "lat": 53.132466, "lon": 23.168826, "pop": 295012},
        {"name": "Gdynia", "lat": 54.488170, "lon": 18.633274, "pop": 246316},
        {"name": "Częstochowa", "lat": 50.812328, "lon": 19.120853, "pop": 215815},
        {"name": "Radom", "lat": 51.402656, "lon": 21.143419, "pop": 209962},
        {"name": "Zabrze", "lat": 50.313156, "lon": 18.775308, "pop": 170784},
    ],
    "FR": [
        {"name": "Paris", "lat": 48.856613, "lon": 2.352222, "pop": 2161000},
        {"name": "Marseille", "lat": 43.296387, "lon": 5.369780, "pop": 869815},
        {"name": "Lyon", "lat": 45.764043, "lon": 4.835659, "pop": 516092},
        {"name": "Toulouse", "lat": 43.604652, "lon": 1.444209, "pop": 479553},
        {"name": "Nice", "lat": 43.710173, "lon": 7.261953, "pop": 340017},
        {"name": "Nantes", "lat": 47.218371, "lon": -1.553621, "pop": 309346},
        {"name": "Strasbourg", "lat": 48.573405, "lon": 7.752111, "pop": 285121},
        {"name": "Montpellier", "lat": 43.610769, "lon": 3.876716, "pop": 285121},
        {"name": "Bordeaux", "lat": 44.841225, "lon": -0.580036, "pop": 261576},
        {"name": "Lille", "lat": 50.629250, "lon": 3.057256, "pop": 232566},
        {"name": "Rennes", "lat": 48.111148, "lon": -1.680198, "pop": 220050},
        {"name": "Reims", "lat": 49.258329, "lon": 4.031696, "pop": 180759},
        {"name": "Havre", "lat": 49.494369, "lon": 0.107883, "pop": 170098},
        {"name": "Rouen", "lat": 49.440258, "lon": 1.099369, "pop": 111557},
        {"name": "Toulon", "lat": 43.124228, "lon": 5.928139, "pop": 174697},
    ],
    "IT": [
        {"name": "Rome", "lat": 41.902782, "lon": 12.496366, "pop": 2760000},
        {"name": "Milan", "lat": 45.465642, "lon": 9.185924, "pop": 1399000},
        {"name": "Naples", "lat": 40.852054, "lon": 14.268619, "pop": 910448},
        {"name": "Turin", "lat": 45.070312, "lon": 7.686856, "pop": 870456},
        {"name": "Palermo", "lat": 38.115556, "lon": 13.361389, "pop": 657224},
        {"name": "Genoa", "lat": 44.405648, "lon": 8.946256, "pop": 610307},
        {"name": "Bologna", "lat": 44.494887, "lon": 11.342616, "pop": 394321},
        {"name": "Florence", "lat": 43.769562, "lon": 11.255814, "pop": 382258},
        {"name": "Bari", "lat": 41.117268, "lon": 16.871871, "pop": 320823},
        {"name": "Catania", "lat": 37.502669, "lon": 15.087269, "pop": 307276},
        {"name": "Venice", "lat": 45.440847, "lon": 12.315515, "pop": 260520},
        {"name": "Messina", "lat": 38.192592, "lon": 15.556389, "pop": 238997},
        {"name": "Verona", "lat": 45.438889, "lon": 10.993333, "pop": 258034},
        {"name": "Padua", "lat": 45.406408, "lon": 11.876761, "pop": 211959},
        {"name": "Como", "lat": 45.808059, "lon": 9.085176, "pop": 84876},
    ],
    "ES": [
        {"name": "Madrid", "lat": 40.416775, "lon": -3.703790, "pop": 3266000},
        {"name": "Barcelona", "lat": 41.385064, "lon": 2.173403, "pop": 1620000},
        {"name": "Valencia", "lat": 39.469907, "lon": -0.376288, "pop": 791413},
        {"name": "Seville", "lat": 37.389092, "lon": -5.984459, "pop": 688711},
        {"name": "Zaragoza", "lat": 41.648823, "lon": -0.889085, "pop": 666880},
        {"name": "Málaga", "lat": 36.721261, "lon": -4.421266, "pop": 574654},
        {"name": "Murcia", "lat": 37.983810, "lon": -1.129730, "pop": 453258},
        {"name": "Palma", "lat": 39.569390, "lon": 2.650170, "pop": 416065},
        {"name": "Bilbao", "lat": 43.262985, "lon": -2.935013, "pop": 345821},
        {"name": "Alicante", "lat": 38.345996, "lon": -0.490686, "pop": 334887},
        {"name": "Córdoba", "lat": 37.888175, "lon": -4.779383, "pop": 325708},
        {"name": "Valladolid", "lat": 41.652251, "lon": -4.724532, "pop": 298412},
        {"name": "Vigo", "lat": 42.240599, "lon": -8.720727, "pop": 295364},
        {"name": "Gijón", "lat": 43.545261, "lon": -5.661926, "pop": 271780},
        {"name": "Granada", "lat": 37.177336, "lon": -3.598557, "pop": 232208},
    ],
    "NL": [
        {"name": "Amsterdam", "lat": 52.370216, "lon": 4.895168, "pop": 872680},
        {"name": "Rotterdam", "lat": 51.924420, "lon": 4.477733, "pop": 651446},
        {"name": "The Hague", "lat": 52.070498, "lon": 4.300700, "pop": 545163},
        {"name": "Utrecht", "lat": 52.090737, "lon": 5.121420, "pop": 357694},
        {"name": "Eindhoven", "lat": 51.441642, "lon": 5.469722, "pop": 234235},
        {"name": "Groningen", "lat": 53.219383, "lon": 6.566502, "pop": 232874},
        {"name": "Tilburg", "lat": 51.555510, "lon": 5.091470, "pop": 219800},
        {"name": "Breda", "lat": 51.587100, "lon": 4.776000, "pop": 183873},
        {"name": "Nijmegen", "lat": 51.842520, "lon": 5.854550, "pop": 176731},
        {"name": "Apeldoorn", "lat": 52.211157, "lon": 5.969923, "pop": 163818},
        {"name": "Haarlem", "lat": 52.381169, "lon": 4.637070, "pop": 161265},
        {"name": "Arnhem", "lat": 51.985103, "lon": 5.898730, "pop": 159265},
    ],
    "BE": [
        {"name": "Brussels", "lat": 50.850340, "lon": 4.351710, "pop": 1212352},
        {"name": "Antwerp", "lat": 51.219448, "lon": 4.402464, "pop": 523248},
        {"name": "Ghent", "lat": 51.054342, "lon": 3.717424, "pop": 262219},
        {"name": "Charleroi", "lat": 50.411034, "lon": 4.444432, "pop": 201593},
        {"name": "Liège", "lat": 50.632557, "lon": 5.579666, "pop": 197355},
        {"name": "Bruges", "lat": 51.209348, "lon": 3.224700, "pop": 118284},
        {"name": "Namur", "lat": 50.465328, "lon": 4.867665, "pop": 110939},
        {"name": "Leuven", "lat": 50.881365, "lon": 4.716537, "pop": 101396},
    ],
    "AT": [
        {"name": "Vienna", "lat": 48.208174, "lon": 16.373819, "pop": 1897000},
        {"name": "Graz", "lat": 47.070714, "lon": 15.439504, "pop": 288806},
        {"name": "Linz", "lat": 48.306940, "lon": 14.285830, "pop": 204846},
        {"name": "Salzburg", "lat": 47.809490, "lon": 13.055010, "pop": 155021},
        {"name": "Innsbruck", "lat": 47.269212, "lon": 11.404102, "pop": 132110},
        {"name": "Klagenfurt", "lat": 46.622220, "lon": 14.305280, "pop": 101303},
    ],
    "CZ": [
        {"name": "Prague", "lat": 50.075538, "lon": 14.437800, "pop": 1309000},
        {"name": "Brno", "lat": 49.195061, "lon": 16.606836, "pop": 372578},
        {"name": "Ostrava", "lat": 49.833880, "lon": 18.283880, "pop": 290553},
        {"name": "Plzeň", "lat": 49.738411, "lon": 13.378116, "pop": 173659},
        {"name": "Liberec", "lat": 50.763056, "lon": 15.056389, "pop": 104266},
    ],
    "HU": [
        {"name": "Budapest", "lat": 47.497912, "lon": 19.040235, "pop": 1752286},
        {"name": "Debrecen", "lat": 47.530556, "lon": 21.630556, "pop": 200341},
        {"name": "Szeged", "lat": 46.252778, "lon": 20.141667, "pop": 160348},
        {"name": "Miskolc", "lat": 48.103519, "lon": 20.776111, "pop": 153000},
        {"name": "Pécs", "lat": 46.073056, "lon": 18.232222, "pop": 140234},
    ],
    "RO": [
        {"name": "Bucharest", "lat": 44.426767, "lon": 26.102538, "pop": 1830169},
        {"name": "Cluj-Napoca", "lat": 46.768585, "lon": 23.590415, "pop": 411379},
        {"name": "Timişoara", "lat": 45.755814, "lon": 21.230015, "pop": 319279},
        {"name": "Iaşi", "lat": 47.158889, "lon": 27.586389, "pop": 288121},
        {"name": "Constanța", "lat": 44.176111, "lon": 28.665278, "pop": 283872},
        {"name": "Craiova", "lat": 44.330329, "lon": 23.805522, "pop": 269506},
        {"name": "Braşov", "lat": 45.641053, "lon": 25.628441, "pop": 266199},
        {"name": "Ploiești", "lat": 44.948889, "lon": 25.582500, "pop": 223369},
    ],
    # Greece (GR)
    "GR": [
        {"name": "Athens", "lat": 37.983810, "lon": 23.727539, "pop": 3154001},
        {"name": "Thessaloniki", "lat": 40.640672, "lon": 22.927754, "pop": 325182},
        {"name": "Patras", "lat": 38.246453, "lon": 21.734402, "pop": 168099},
        {"name": "Heraklion", "lat": 35.338692, "lon": 25.131606, "pop": 173993},
    ],
    # Portugal (PT)
    "PT": [
        {"name": "Lisbon", "lat": 38.722252, "lon": -9.139337, "pop": 505526},
        {"name": "Porto", "lat": 41.157944, "lon": -8.629105, "pop": 1688816},
        {"name": "Braga", "lat": 41.565250, "lon": -8.429870, "pop": 195938},
        {"name": "Covilhã", "lat": 40.284850, "lon": -7.498690, "pop": 117505},
    ],
    # Sweden (SE)
    "SE": [
        {"name": "Stockholm", "lat": 59.329444, "lon": 18.068611, "pop": 975551},
        {"name": "Gothenburg", "lat": 57.708870, "lon": 11.974560, "pop": 644799},
        {"name": "Malmö", "lat": 55.604981, "lon": 12.994850, "pop": 347949},
        {"name": "Uppsala", "lat": 59.861405, "lon": 17.640148, "pop": 230767},
        {"name": "Västerås", "lat": 59.609869, "lon": 16.539127, "pop": 127948},
        {"name": "Örebro", "lat": 59.271088, "lon": 15.207284, "pop": 130676},
        {"name": "Linköping", "lat": 58.410417, "lon": 15.619667, "pop": 102945},
    ],
    # Finland (FI)
    "FI": [
        {"name": "Helsinki", "lat": 60.169856, "lon": 24.938379, "pop": 656873},
        {"name": "Espoo", "lat": 60.205252, "lon": 24.655899, "pop": 288975},
        {"name": "Tampere", "lat": 61.494912, "lon": 23.760701, "pop": 239316},
        {"name": "Vantaa", "lat": 60.294167, "lon": 25.037222, "pop": 233257},
        {"name": "Turku", "lat": 60.452788, "lon": 22.266626, "pop": 190667},
        {"name": "Oulu", "lat": 65.012662, "lon": 25.475171, "pop": 156214},
        {"name": "Kuopio", "lat": 62.891111, "lon": 27.678333, "pop": 123372},
        {"name": "Jyväskylä", "lat": 62.242531, "lon": 25.748151, "pop": 143341},
    ],
    # Denmark (DK)
    "DK": [
        {"name": "Copenhagen", "lat": 55.676111, "lon": 12.568333, "pop": 1349000},
        {"name": "Aarhus", "lat": 56.156667, "lon": 10.200000, "pop": 349983},
        {"name": "Odense", "lat": 55.403333, "lon": 10.388889, "pop": 175245},
        {"name": "Aalborg", "lat": 57.047857, "lon": 9.921682, "pop": 131916},
        {"name": "Randers", "lat": 56.461667, "lon": 10.316667, "pop": 101564},
    ],
    # Slovakia (SK)
    "SK": [
        {"name": "Bratislava", "lat": 48.148598, "lon": 17.107748, "pop": 475508},
        {"name": "Košice", "lat": 48.718333, "lon": 21.260833, "pop": 236093},
        {"name": "Prešov", "lat": 49.000000, "lon": 21.239167, "pop": 106648},
        {"name": "Žilina", "lat": 49.224167, "lon": 18.740833, "pop": 109618},
        {"name": "Banská Bystrica", "lat": 48.735833, "lon": 19.140278, "pop": 77229},
    ],
    # Slovenia (SI)
    "SI": [
        {"name": "Ljubljana", "lat": 46.056947, "lon": 14.505751, "pop": 295022},
        {"name": "Maribor", "lat": 46.553329, "lon": 15.647834, "pop": 111385},
        {"name": "Celje", "lat": 46.238889, "lon": 15.277222, "pop": 49323},
    ],
    # Croatia (HR)
    "HR": [
        {"name": "Zagreb", "lat": 45.815011, "lon": 15.982287, "pop": 769944},
        {"name": "Split", "lat": 43.508137, "lon": 16.440808, "pop": 176314},
        {"name": "Rijeka", "lat": 45.327063, "lon": 14.442176, "pop": 128735},
        {"name": "Osijek", "lat": 45.551667, "lon": 18.713889, "pop": 108048},
    ],
    # Lithuania (LT)
    "LT": [
        {"name": "Vilnius", "lat": 54.687157, "lon": 25.279652, "pop": 588412},
        {"name": "Kaunas", "lat": 54.901389, "lon": 23.904444, "pop": 324365},
        {"name": "Klaipėda", "lat": 55.708889, "lon": 21.144722, "pop": 151177},
        {"name": "Šiauliai", "lat": 55.933889, "lon": 23.728889, "pop": 104697},
    ],
    # Latvia (LV)
    "LV": [
        {"name": "Riga", "lat": 56.949649, "lon": 24.105186, "pop": 605802},
        {"name": "Daugavpils", "lat": 55.873611, "lon": 26.532500, "pop": 102325},
        {"name": "Liepāja", "lat": 56.515000, "lon": 21.015000, "pop": 76731},
    ],
    # Estonia (EE)
    "EE": [
        {"name": "Tallinn", "lat": 59.436961, "lon": 24.753575, "pop": 438203},
        {"name": "Tartu", "lat": 58.378025, "lon": 26.728123, "pop": 140232},
        {"name": "Narva", "lat": 59.378889, "lon": 28.187500, "pop": 58385},
    ],
    # Cyprus (CY)
    "CY": [
        {"name": "Nicosia", "lat": 35.126413, "lon": 33.382827, "pop": 310968},
        {"name": "Limassol", "lat": 34.674882, "lon": 33.038252, "pop": 193100},
        {"name": "Larnaca", "lat": 34.917671, "lon": 33.630033, "pop": 69920},
    ],
    # Luxembourg (LU)
    "LU": [
        {"name": "Luxembourg City", "lat": 49.611621, "lon": 6.129583, "pop": 128025},
        {"name": "Esch-sur-Alzette", "lat": 49.493889, "lon": 5.978056, "pop": 100816},
    ],
    # Malta (MT)
    "MT": [
        {"name": "Valletta", "lat": 35.897656, "lon": 14.512516, "pop": 6000},
        {"name": "Birkirkara", "lat": 35.871667, "lon": 14.402500, "pop": 121910},
        {"name": "Mosta", "lat": 35.880556, "lon": 14.378889, "pop": 20107},
    ],
    # Bulgaria (BG)
    "BG": [
        {"name": "Sofia", "lat": 42.697708, "lon": 23.321868, "pop": 1241396},
        {"name": "Plovdiv", "lat": 42.149833, "lon": 24.750680, "pop": 346893},
        {"name": "Varna", "lat": 43.204808, "lon": 27.911856, "pop": 312770},
        {"name": "Burgas", "lat": 42.504810, "lon": 27.471111, "pop": 210385},
        {"name": "Ruse", "lat": 43.852222, "lon": 25.955000, "pop": 155049},
    ],
    # Ireland (IE)
    "IE": [
        {"name": "Dublin", "lat": 53.349805, "lon": -6.260310, "pop": 1256057},
        {"name": "Cork", "lat": 51.897720, "lon": -8.470027, "pop": 208669},
        {"name": "Galway", "lat": 53.271028, "lon": -9.050582, "pop": 179227},
        {"name": "Limerick", "lat": 52.638889, "lon": -8.624444, "pop": 100396},
    ],
}

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

def get_country_code(lat, lon) -> str:
    """Get country code from coordinates using reverse geocoding"""
    try:
        params = {"lat": lat, "lon": lon, "format": "json"}
        resp = requests.get(NOMINATIM_REVERSE, params=params, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            addr = data.get("address", {})
            code = addr.get("country_code", "").upper()
            if code and code in MAJOR_CITIES_DB:
                return code
    except:
        pass
    # Fallback to default country
    return "DE"

def find_nearest_city(lat: float, lon: float, max_distance: float = 200) -> Optional[Dict]:
    """Find nearest major city (100k+) within max_distance km"""
    cc = get_country_code(lat, lon)
    cities = MAJOR_CITIES_DB.get(cc, MAJOR_CITIES_DB.get("DE", []))
    
    if not cities:
        return None
    
    nearest = None
    nearest_dist = float('inf')
    
    for city in cities:
        dist = haversine_km(lat, lon, city["lat"], city["lon"])
        if dist < nearest_dist and dist <= max_distance:
            nearest_dist = dist
            nearest = (city["name"], dist)
    
    return nearest

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
    """Convert results to long format for Site Selection Tool with NUTS3 ID"""
    long_format_rows = []
    
    for _, row in df_results.iterrows():
        # Extract base site information
        project_id = row.get("Project ID", "")
        site_id = row.get("Site ID", "")
        site_name = row.get("Site Name", "")
        lat = row.get("Latitude", "")
        lon = row.get("Longitude", "")
        nuts3_id = row.get("NUTS3 ID", "")
        
        # Extract catchment data if available
        pop_col = f"Catchment Population ({catchment_radius}km)"
        unemployed_col = f"Catchment Unemployed ({catchment_radius}km)"
        active_col = f"Catchment Active Pop ({catchment_radius}km)"
        
        catchment_pop = row.get(pop_col, "")
        catchment_unemployed = row.get(unemployed_col, "")
        catchment_active = row.get(active_col, "")
        
        # 1. Nearest Airport record (Accessibility: 1)
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
                "NUTS3 ID": nuts3_id,
                "Catchment Population": catchment_pop,
                "Catchment Unemployed": catchment_unemployed,
                "Catchment Active Population": catchment_active
            })
        
        # 2. Inbound (Seaport) record
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
                "Accessibility": 2,
                "NUTS3 ID": nuts3_id,
                "Catchment Population": catchment_pop,
                "Catchment Unemployed": catchment_unemployed,
                "Catchment Active Population": catchment_active
            })
        
        # 3. Outbound (Reference location) record
        if ref_name and pd.notna(row.get("Distance to Reference (km)")):
            long_format_rows.append({
                "Project ID": project_id,
                "Project Name": "",
                "Site ID": site_id,
                "Site Name": site_name,
                "LatitudeY": lat,
                "LongitudeX": lon,
                "Destination": ref_name,
                "Destination group": "Outbound",
                "Distance (km)": row.get("Distance to Reference (km)", ""),
                "Time (min)": row.get("Time to Reference (min)", ""),
                "Accessibility": 3,
                "NUTS3 ID": nuts3_id,
                "Catchment Population": catchment_pop,
                "Catchment Unemployed": catchment_unemployed,
                "Catchment Active Population": catchment_active
            })
        
        # 4. Nearest City (100k+) record
        if pd.notna(row.get("Nearest City")):
            long_format_rows.append({
                "Project ID": project_id,
                "Project Name": "",
                "Site ID": site_id,
                "Site Name": site_name,
                "LatitudeY": lat,
                "LongitudeX": lon,
                "Destination": row.get("Nearest City", ""),
                "Destination group": "Nearest City",
                "Distance (km)": row.get("Distance to City (km)", ""),
                "Time (min)": row.get("Time to City (min)", ""),
                "Accessibility": 4,
                "NUTS3 ID": nuts3_id,
                "Catchment Population": catchment_pop,
                "Catchment Unemployed": catchment_unemployed,
                "Catchment Active Population": catchment_active
            })
        
        # 5. Nearest Highway record
        if pd.notna(row.get("Nearest Highway")):
            long_format_rows.append({
                "Project ID": project_id,
                "Project Name": "",
                "Site ID": site_id,
                "Site Name": site_name,
                "LatitudeY": lat,
                "LongitudeX": lon,
                "Destination": row.get("Nearest Highway", ""),
                "Destination group": "Nearest Highway",
                "Distance (km)": row.get("Distance to Highway (km)", ""),
                "Time (min)": row.get("Time to Highway (min)", ""),
                "Accessibility": 5,
                "NUTS3 ID": nuts3_id,
                "Catchment Population": catchment_pop,
                "Catchment Unemployed": catchment_unemployed,
                "Catchment Active Population": catchment_active
            })
    
    return pd.DataFrame(long_format_rows)

# ---------------------- Rest of the functions ----------------------
@st.cache_data(show_spinner=False)
def load_nuts3_data():
    """Load NUTS3 boundaries for enrichment"""
    if not _HAS_SHAPELY:
        return None
    
    try:
        resp = requests.get(NUTS3_URL, timeout=10)
        if resp.status_code != 200:
            return None
        geojson = resp.json()
        features = geojson.get("features", [])
        tree_data = []
        for f in features:
            geom = shape(f.get("geometry"))
            props = f.get("properties", {})
            nuts3_id = props.get("NUTS_ID", "")
            tree_data.append((geom, nuts3_id))
        if tree_data:
            return tree_data
    except:
        pass
    return None

@st.cache_data(show_spinner=False)
def load_osm_admin_pl():
    """Load Polish admin boundaries"""
    if not _HAS_SHAPELY:
        return None
    
    try:
        resp = requests.get("https://nominatim.openstreetmap.org/data/boundary-data.geojson", timeout=10)
        if resp.status_code != 200:
            return None
        geojson = resp.json()
        features = geojson.get("features", [])
        admin_data = []
        for f in features:
            geom = shape(f.get("geometry"))
            props = f.get("properties", {})
            admin_data.append((geom, props))
        if admin_data:
            return admin_data
    except:
        pass
    return None

def enrich_nuts3(lat: float, lon: float, nuts3_data: Optional[List] = None) -> str:
    """Enrich with NUTS3 ID"""
    if not _HAS_SHAPELY or not nuts3_data:
        return ""
    
    try:
        pt = Point(lon, lat)
        for geom, nuts3_id in nuts3_data:
            if geom.contains(pt):
                return nuts3_id
    except:
        pass
    return ""

def get_route(lat1: float, lon1: float, lat2: float, lon2: float) -> Optional[Dict]:
    """Get route distance and time from OSRM"""
    cache_key = f"{lat1:.4f},{lon1:.4f},{lat2:.4f},{lon2:.4f}"
    if "route_cache" not in st.session_state:
        st.session_state["route_cache"] = {}
    
    if cache_key in st.session_state["route_cache"]:
        return st.session_state["route_cache"][cache_key]
    
    try:
        url = OSRM_URL.format(lon1=lon1, lat1=lat1, lon2=lon2, lat2=lat2)
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("routes"):
                route = data["routes"][0]
                result = {
                    "distance_km": route.get("distance", 0) / 1000,
                    "duration_min": route.get("duration", 0) / 60
                }
                st.session_state["route_cache"][cache_key] = result
                return result
    except:
        pass
    return None

def get_nearest_highway(lat: float, lon: float) -> Optional[str]:
    """Get nearest highway using Overpass API"""
    try:
        query = f"""
        [bbox:{lat-0.05},{lon-0.05},{lat+0.05},{lon+0.05}];
        way["highway"~"motorway|trunk|primary"];
        out geom;
        """
        resp = requests.post(OVERPASS_URL, data=query, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("elements"):
                for elem in data["elements"]:
                    name = elem.get("tags", {}).get("name", "")
                    if name:
                        return name
    except:
        pass
    return None

def process_batch(sites_df: pd.DataFrame, airports_df: pd.DataFrame, seaports_df: pd.DataFrame,
                  topn: int = 5, include_ref: bool = True, ref_lat: float = 51.0126, ref_lon: float = 6.5741,
                  ref_name: str = "Reference", pause_every: int = 10, pause_secs: float = 1.0,
                  progress_hook = None, enrich_nuts3: bool = True, enrich_osm_admin: bool = True,
                  include_highway: bool = True, include_catchment: bool = True, catchment_radius: int = 50) -> Tuple:
    """Process batch of sites"""
    
    nuts3_data = load_nuts3_data() if enrich_nuts3 else None
    osm_admin = load_osm_admin_pl() if enrich_osm_admin else None
    
    results = []
    logs = []
    api_calls = 0
    
    for idx, site in sites_df.iterrows():
        site_log = {"site": site.get("Site Name", f"Site {idx}"), "steps": []}
        site_results = dict(site)
        
        try:
            site_lat = float(site["Latitude"])
            site_lon = float(site["Longitude"])
            
            # NUTS3 enrichment
            if enrich_nuts3 and nuts3_data:
                nuts3_id = enrich_nuts3(site_lat, site_lon, nuts3_data)
                site_results["NUTS3 ID"] = nuts3_id
                site_log["steps"].append({"msg": f"NUTS3: {nuts3_id}"})
            
            # Nearest Airport (prefilter top-N)
            nearest_airports = []
            for _, airport in airports_df.iterrows():
                dist = haversine_km(site_lat, site_lon, float(airport["Latitude"]), float(airport["Longitude"]))
                nearest_airports.append((airport["Airport Name"], dist))
            
            nearest_airports.sort(key=lambda x: x[1])
            nearest_airports = nearest_airports[:topn]
            
            if nearest_airports:
                airport_name, airport_dist = nearest_airports[0]
                airport_row = airports_df[airports_df["Airport Name"] == airport_name].iloc[0]
                route = get_route(site_lat, site_lon, float(airport_row["Latitude"]), float(airport_row["Longitude"]))
                api_calls += 1
                
                if route:
                    site_results["Nearest Airport"] = airport_name
                    site_results["Distance to Airport (km)"] = round(route["distance_km"], 2)
                    site_results["Time to Airport (min)"] = round(route["duration_min"], 1)
                    site_log["steps"].append({"msg": f"Airport: {airport_name} - {route['distance_km']:.1f}km"})
            
            # Nearest Seaport (prefilter top-N)
            nearest_seaports = []
            for _, seaport in seaports_df.iterrows():
                dist = haversine_km(site_lat, site_lon, float(seaport["Latitude"]), float(seaport["Longitude"]))
                nearest_seaports.append((seaport["Seaport Name"], dist))
            
            nearest_seaports.sort(key=lambda x: x[1])
            nearest_seaports = nearest_seaports[:topn]
            
            if nearest_seaports:
                seaport_name, seaport_dist = nearest_seaports[0]
                seaport_row = seaports_df[seaports_df["Seaport Name"] == seaport_name].iloc[0]
                route = get_route(site_lat, site_lon, float(seaport_row["Latitude"]), float(seaport_row["Longitude"]))
                api_calls += 1
                
                if route:
                    site_results["Nearest Seaport"] = seaport_name
                    site_results["Distance to Seaport (km)"] = round(route["distance_km"], 2)
                    site_results["Time to Seaport (min)"] = round(route["duration_min"], 1)
                    site_log["steps"].append({"msg": f"Seaport: {seaport_name} - {route['distance_km']:.1f}km"})
            
            # Reference location (Outbound)
            if include_ref:
                route = get_route(site_lat, site_lon, ref_lat, ref_lon)
                api_calls += 1
                
                if route:
                    site_results["Distance to Reference (km)"] = round(route["distance_km"], 2)
                    site_results["Time to Reference (min)"] = round(route["duration_min"], 1)
                    site_log["steps"].append({"msg": f"Outbound ({ref_name}): {route['distance_km']:.1f}km"})
            
            # Nearest City (100k+)
            city_result = find_nearest_city(site_lat, site_lon, max_distance=200)
            if city_result:
                city_name, city_dist = city_result
                city_row = [c for c in MAJOR_CITIES_DB.values() for c in c if c["name"] == city_name]
                if city_row:
                    c = city_row[0]
                    route = get_route(site_lat, site_lon, c["lat"], c["lon"])
                    api_calls += 1
                    
                    if route:
                        site_results["Nearest City"] = city_name
                        site_results["Distance to City (km)"] = round(route["distance_km"], 2)
                        site_results["Time to City (min)"] = round(route["duration_min"], 1)
                        site_log["steps"].append({"msg": f"City: {city_name} - {route['distance_km']:.1f}km"})
            
            # Nearest Highway
            if include_highway:
                highway = get_nearest_highway(site_lat, site_lon)
                if highway:
                    site_results["Nearest Highway"] = highway
                    site_results["Distance to Highway (km)"] = 0  # Placeholder
                    site_results["Time to Highway (min)"] = 0
                    site_log["steps"].append({"msg": f"Highway: {highway}"})
            
            results.append(site_results)
            logs.append(site_log)
            
        except Exception as e:
            site_log["steps"].append({"error": str(e)})
            logs.append(site_log)
        
        if progress_hook:
            progress_hook(f"Processed {idx+1}/{len(sites_df)}")
        
        if pause_every > 0 and (idx + 1) % pause_every == 0:
            time.sleep(pause_secs)
    
    df_results = pd.DataFrame(results)
    return df_results, logs, api_calls

def sidebar():
    """Sidebar configuration"""
    st.sidebar.header("⚙️ Configuration")
    
    topn = st.sidebar.slider("Top-N prefilter for airports/seaports", 1, 20, 5)
    
    st.sidebar.subheader("API Rate Limiting")
    pause_every = st.sidebar.number_input("Pause after N requests", value=10, min_value=1)
    pause_secs = st.sidebar.number_input("Pause duration (seconds)", value=1.0, min_value=0.1)
    
    st.sidebar.subheader("Reference Location (Outbound)")
    use_ref = st.sidebar.checkbox("Include reference location", value=True)
    ref_name = st.sidebar.text_input("Reference name", value=DEFAULT_REF["name"])
    ref_lat = st.sidebar.number_input("Reference latitude", value=DEFAULT_REF["lat"])
    ref_lon = st.sidebar.number_input("Reference longitude", value=DEFAULT_REF["lon"])
    
    st.sidebar.subheader("Enrichments")
    enrich_osm_admin = st.sidebar.checkbox("Enrich with OSM admin data", value=ENRICH_DEFAULT_OSM_ADMIN)
    include_highway = st.sidebar.checkbox("Include nearest highway", value=True)
    include_catchment = st.sidebar.checkbox("Include catchment analysis", value=True)
    catchment_radius = st.sidebar.slider("Catchment radius (km)", 25, 150, 50)
    
    return topn, pause_every, pause_secs, use_ref, ref_name, ref_lat, ref_lon, enrich_osm_admin, include_highway, include_catchment, catchment_radius

def download_buttons_area():
    """Download template files"""
    st.subheader("📥 Download Templates")
    templates = template_files()
    cols = st.columns(len(templates))
    for col, (fname, fcontent) in zip(cols, templates.items()):
        with col:
            st.download_button(
                label=f"📄 {fname}",
                data=fcontent,
                file_name=fname,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

def upload_area():
    """Upload files"""
    st.subheader("📤 Upload Data")
    
    col1, col2, col3 = st.columns(3)
    
    sites_file = col1.file_uploader("Sites", type=["xlsx", "csv"], key="sites")
    airports_file = col2.file_uploader("Airports", type=["xlsx", "csv"], key="airports")
    seaports_file = col3.file_uploader("Seaports", type=["xlsx", "csv"], key="seaports")
    
    sites_df = airports_df = seaports_df = None
    
    if sites_file:
        sites_df = pd.read_excel(sites_file) if sites_file.name.endswith('.xlsx') else pd.read_csv(sites_file)
        if not all(c in sites_df.columns for c in REQUIRED_SITES_COLS):
            st.error(f"Sites must have: {REQUIRED_SITES_COLS}")
            return None, None, None
    
    if airports_file:
        airports_df = pd.read_excel(airports_file) if airports_file.name.endswith('.xlsx') else pd.read_csv(airports_file)
        if not all(c in airports_df.columns for c in REQUIRED_AIRPORTS_COLS):
            st.error(f"Airports must have: {REQUIRED_AIRPORTS_COLS}")
            return None, None, None
    
    if seaports_file:
        seaports_df = pd.read_excel(seaports_file) if seaports_file.name.endswith('.xlsx') else pd.read_csv(seaports_file)
        if not all(c in seaports_df.columns for c in REQUIRED_SEAPORTS_COLS):
            st.error(f"Seaports must have: {REQUIRED_SEAPORTS_COLS}")
            return None, None, None
    
    return sites_df, airports_df, seaports_df

def results_downloads(df_res: pd.DataFrame, ref_name: str = None, catchment_radius: int = 50, filename_prefix: str = "results"):
    """Download results in various formats"""
    st.subheader("📥 Download Results")
    
    col1, col2, col3 = st.columns(3)
    
    # Excel
    with col1:
        b = io.BytesIO()
        with pd.ExcelWriter(b, engine="xlsxwriter") as xw:
            df_res.to_excel(xw, sheet_name="Results", index=False)
        st.download_button(
            label="📊 Excel",
            data=b.getvalue(),
            file_name=f"{filename_prefix}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    
    # CSV
    with col2:
        csv_data = df_res.to_csv(index=False)
        st.download_button(
            label="📄 CSV",
            data=csv_data,
            file_name=f"{filename_prefix}.csv",
            mime="text/csv"
        )
    
    # Site Selection Format
    with col3:
        df_long = create_site_selection_format(df_res, ref_name=ref_name, catchment_radius=catchment_radius)
        b = io.BytesIO()
        with pd.ExcelWriter(b, engine="xlsxwriter") as xw:
            df_long.to_excel(xw, sheet_name="Site Selection", index=False)
        st.download_button(
            label="🎯 Site Selection Format",
            data=b.getvalue(),
            file_name=f"{filename_prefix}_site_selection.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

def display_catchment_summary(df_res: pd.DataFrame, catchment_radius: int = 50):
    """Display catchment analysis summary"""
    st.subheader(f"👥 Catchment Analysis ({catchment_radius}km)")
    
    pop_col = f"Catchment Population ({catchment_radius}km)"
    if pop_col not in df_res.columns:
        return
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        avg_pop = df_res[pop_col].mean()
        st.metric("Avg Population", f"{avg_pop:,.0f}")
    
    with col2:
        max_pop = df_res[pop_col].max()
        st.metric("Max Population", f"{max_pop:,.0f}")
    
    with col3:
        min_pop = df_res[pop_col].min()
        st.metric("Min Population", f"{min_pop:,.0f}")

def maybe_map(df: pd.DataFrame, airports: pd.DataFrame, seaports: pd.DataFrame):
    """Show interactive map"""
    if not _HAS_MAP:
        st.warning("Folium not available - map disabled")
        return
    
    m = folium.Map(location=[51.0, 10.0], zoom_start=4)
    Fullscreen().add_to(m)
    
    site_group = folium.FeatureGroup(name="Sites", show=True)
    airport_group = folium.FeatureGroup(name="Airports", show=True)
    seaport_group = folium.FeatureGroup(name="Seaports", show=True)
    
    # Sites
    for _, r in df.iterrows():
        if pd.notna(r.get("Latitude")) and pd.notna(r.get("Longitude")):
            folium.CircleMarker(
                [float(r["Latitude"]), float(r["Longitude"])],
                radius=8,
                color="blue",
                fill=True,
                popup=f"📍 {r.get('Site Name', '')}",
                tooltip=r.get("Site Name", "")
            ).add_to(site_group)
    
    # Airports
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
    
    # Seaports
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
    
    # Reference location (Outbound)
    ref_lat = st.session_state.get("ref_lat")
    ref_lon = st.session_state.get("ref_lon")
    ref_name = st.session_state.get("ref_name")
    if isinstance(ref_lat, (int, float)) and isinstance(ref_lon, (int, float)):
        folium.Marker(
            [float(ref_lat), float(ref_lon)],
            icon=folium.Icon(icon="star", color="green"),
            popup=f"⭐ Outbound: {ref_name}",
            tooltip=f"⭐ Outbound: {ref_name}"
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
    
    # Store ref info in session for map
    st.session_state["ref_lat"] = ref_lat
    st.session_state["ref_lon"] = ref_lon
    st.session_state["ref_name"] = ref_name
    
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
