"""
AgriRoute - Routing & Day Plan Optimiser
Uses OSRM public API for road routing and a greedy TSP for field ordering.
Uses Overpass API to find fuel stations on route.
"""
import requests
import math
from typing import List, Dict, Tuple, Optional

OSRM_URL       = "http://router.project-osrm.org/route/v1/driving"
OVERPASS_URL   = "https://overpass-api.de/api/interpreter"


# ── Geometry ──────────────────────────────────────────────────────────────────
def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def route_midpoint(coords: List[Tuple[float, float]]) -> Tuple[float, float]:
    lats = [c[0] for c in coords]
    lons = [c[1] for c in coords]
    return sum(lats) / len(lats), sum(lons) / len(lons)


# ── OSRM ──────────────────────────────────────────────────────────────────────
def get_osrm_route(coords: List[Tuple[float, float]]) -> Optional[dict]:
    """
    Road route from OSRM for a list of (lat, lon) waypoints.
    Returns distance_km, duration_min, geometry [[lon, lat], ...].
    """
    if len(coords) < 2:
        return None
    coord_str = ";".join(f"{lon},{lat}" for lat, lon in coords)
    url = f"{OSRM_URL}/{coord_str}"
    params = {"overview": "simplified", "geometries": "geojson", "steps": "false"}
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        if data.get("code") == "Ok" and data.get("routes"):
            route = data["routes"][0]
            return {
                "distance_km":  route["distance"] / 1000,
                "duration_min": route["duration"] / 60,
                "geometry":     route["geometry"]["coordinates"],
            }
    except Exception as e:
        print(f"OSRM error: {e}")
    return None


# ── Fuel Stations ─────────────────────────────────────────────────────────────
def find_fuel_stations(lat: float, lon: float, radius_m: int = 15000) -> List[dict]:
    """
    Find fuel stations within radius_m metres of (lat, lon) using Overpass API.
    Returns list of dicts with name, lat, lon, brand, distance_km.
    """
    query = f"""
    [out:json][timeout:15];
    (
      node["amenity"="fuel"](around:{radius_m},{lat},{lon});
      way["amenity"="fuel"](around:{radius_m},{lat},{lon});
    );
    out center;
    """
    try:
        r = requests.post(OVERPASS_URL, data={"data": query}, timeout=20)
        r.raise_for_status()
        elements = r.json().get("elements", [])
        stations = []
        for el in elements:
            slat = el.get("lat") or el.get("center", {}).get("lat")
            slon = el.get("lon") or el.get("center", {}).get("lon")
            if slat is None or slon is None:
                continue
            tags  = el.get("tags", {})
            brand = tags.get("brand") or tags.get("name") or tags.get("operator") or "Fuel Station"
            dist  = haversine_km(lat, lon, slat, slon)
            stations.append({
                "name":        tags.get("name", brand),
                "brand":       brand,
                "lat":         slat,
                "lon":         slon,
                "distance_km": round(dist, 1),
                "address":     tags.get("addr:street", ""),
            })
        stations.sort(key=lambda s: s["distance_km"])
        return stations[:10]
    except Exception as e:
        print(f"Overpass fuel error: {e}")
        return []


# ── TSP / Day Plan ────────────────────────────────────────────────────────────
def greedy_tsp(home: Tuple[float, float], fields: List[dict]) -> List[dict]:
    """Greedy nearest-neighbour TSP weighted by priority + distance."""
    if not fields:
        return []
    remaining, ordered = fields.copy(), []
    current = home
    while remaining:
        best, best_val = None, -9999.0
        for f in remaining:
            dist = haversine_km(current[0], current[1], f["lat"], f["lon"])
            dist_penalty = max(0.0, (dist - 5.0) * 2.0)
            val = f.get("_priority_score", 50.0) - dist_penalty
            if val > best_val:
                best_val, best = val, f
        ordered.append(best)
        current = (best["lat"], best["lon"])
        remaining.remove(best)
    return ordered


def build_day_plan(home_lat: float, home_lon: float,
                   fields: List[dict],
                   operation: str,
                   work_rate_ha_hr: float,
                   cost_per_ha: float,
                   start_time_hr: float = 7.0,
                   max_hours: float = 10.0,
                   avg_speed_kmh: float = 50.0,
                   setup_time_min: float = 0.0) -> dict:
    """
    Build optimised day plan.
    setup_time_min: fixed time added per field visit (filling, checks etc.)
    Returns ordered field list with timings, travel, ROI + all waypoints for map.
    """
    home = (home_lat, home_lon)
    sorted_fields = sorted(fields, key=lambda f: f.get("_priority_score", 0), reverse=True)
    ordered       = greedy_tsp(home, sorted_fields)

    plan       = []
    hour       = start_time_hr
    total_ha   = 0.0
    total_rev  = 0.0
    prev_coord = home
    waypoints  = [home]

    for f in ordered:
        if hour >= start_time_hr + max_hours:
            break

        dist_km    = haversine_km(prev_coord[0], prev_coord[1], f["lat"], f["lon"])
        travel_min = (dist_km / avg_speed_kmh) * 60

        work_hr  = f["hectares"] / work_rate_ha_hr
        work_min = work_hr * 60

        # Total time needed for this stop: travel + setup + fieldwork
        total_stop_hr = (travel_min + setup_time_min + work_min) / 60

        if hour + total_stop_hr > start_time_hr + max_hours:
            # How much working time is actually left after travel + setup?
            available_hr = (start_time_hr + max_hours) - hour - (travel_min + setup_time_min) / 60
            if available_hr <= 0:
                break
            ha_possible = min(available_hr * work_rate_ha_hr, f["hectares"])
            partial = True
        else:
            ha_possible = f["hectares"]
            partial     = False

        revenue       = ha_possible * cost_per_ha
        arrive_hr     = hour + travel_min / 60
        work_start_hr = arrive_hr + setup_time_min / 60
        finish_hr     = work_start_hr + ha_possible / work_rate_ha_hr

        plan.append({
            "field_id":        f.get("id", ""),
            "farm_id":         f.get("farm_id", ""),
            "field_name":      f["name"],
            "farm_name":       f.get("farm_name", ""),
            "crop_type":       f.get("crop_type", ""),
            "bbch_stage":      f.get("bbch_stage", 0),
            "hectares":        round(ha_possible, 1),
            "full_field":      not partial,
            "priority_score":  round(f.get("_priority_score", 0), 1),
            "distance_km":     round(dist_km, 1),
            "travel_min":      round(travel_min),
            "setup_min":       round(setup_time_min),
            "work_min":        round(ha_possible / work_rate_ha_hr * 60),
            "arrive_time":     _hr_to_hhmm(arrive_hr),
            "work_start_time": _hr_to_hhmm(work_start_hr),
            "finish_time":     _hr_to_hhmm(finish_hr),
            "revenue":         round(revenue, 2),
            "lat":             f["lat"],
            "lon":             f["lon"],
        })

        total_ha  += ha_possible
        total_rev += revenue
        hour        = finish_hr
        prev_coord  = (f["lat"], f["lon"])
        waypoints.append((f["lat"], f["lon"]))

    return_dist = haversine_km(prev_coord[0], prev_coord[1], home_lat, home_lon)
    return_min  = (return_dist / avg_speed_kmh) * 60
    waypoints.append(home)

    # Suggested fuel stop: find stations near route midpoint
    mid = route_midpoint(waypoints) if len(waypoints) > 1 else home
    fuel_stations = find_fuel_stations(mid[0], mid[1], radius_m=20000)

    return {
        "plan":           plan,
        "total_ha":       round(total_ha, 1),
        "total_revenue":  round(total_rev, 2),
        "fields_count":   len(plan),
        "finish_time":    _hr_to_hhmm(hour),
        "return_time":    _hr_to_hhmm(hour + return_min / 60),
        "return_dist_km": round(return_dist, 1),
        "operation":      operation,
        "waypoints":      waypoints,
        "fuel_stations":  fuel_stations,
    }


def _hr_to_hhmm(hr: float) -> str:
    h = int(hr) % 24
    m = int((hr % 1) * 60)
    return f"{h:02d}:{m:02d}"
