"""
Live UK fuel prices via the mandatory CMA transparency scheme.
Major retailers (5+ forecourts) must publish real-time prices in a standard
JSON format since late 2023. No API key required.

Prices are in pence per litre (e.g. 149.9 = £1.499/L).
B7 = diesel (DERV), E10 = unleaded petrol.
"""
import requests
from typing import List, Tuple, Optional
from utils.routing import haversine_km

# ── Retailer feeds (standard CMA format unless noted) ─────────────────────────
CMA_FEEDS = [
    {"retailer": "Asda",        "url": "https://storelocator.asda.com/fuel_prices_data.json"},
    {"retailer": "Tesco",       "url": "https://www.tesco.com/fuel_prices/fuel_prices_data.json"},
    {"retailer": "Morrisons",   "url": "https://www.morrisons.com/fuel-prices/fuel_prices_data.json"},
    {"retailer": "Sainsbury's", "url": "https://api.sainsburys.co.uk/v1/exports/latest/fuel_prices_data.json"},
    {"retailer": "BP",          "url": "https://www.bp.com/en_gb/united-kingdom/home/fuelprices/fuel_prices_data.json"},
    {"retailer": "Esso/EG",     "url": "https://fuelprices.esso.co.uk/latestdata.json"},
    {"retailer": "JET",         "url": "https://jetlocal.co.uk/fuel_prices_data.json"},
    {"retailer": "MFG",         "url": "https://fuel.motorfuelgroup.com/fuel_prices_data.json"},
    {"retailer": "Gulf",        "url": "https://www.gulf.co.uk/fuel-prices/fuel_prices_data.json"},
    {"retailer": "Rontec",      "url": "https://www.rontec-servicestations.co.uk/fuel-prices/data/fuel_prices_data.json"},
    {"retailer": "Applegreen",  "url": "https://applegreenstores.com/fuel-prices/data.json"},
    {"retailer": "Ascona",      "url": "https://fuelprices.asconagroup.co.uk/newfuel.json"},
    {"retailer": "SGN",         "url": "https://www.sgnretail.uk/files/data/SGN_daily_fuel_prices.json"},
]


# ── Parser ─────────────────────────────────────────────────────────────────────
def _parse_feed(raw: dict, retailer: str) -> List[dict]:
    """Normalise a CMA-format feed into standard dicts."""
    stations = []
    for s in raw.get("stations", []):
        loc = s.get("location", {})
        lat = loc.get("latitude") or loc.get("lat")
        lon = loc.get("longitude") or loc.get("lng") or loc.get("lon")
        if lat is None or lon is None:
            continue
        try:
            lat, lon = float(lat), float(lon)
        except (TypeError, ValueError):
            continue

        prices = s.get("prices", {})
        # Diesel: B7 is the CMA standard key; some use "diesel"
        diesel_ppl = prices.get("B7") or prices.get("diesel") or prices.get("Diesel")
        petrol_ppl = prices.get("E10") or prices.get("E5") or prices.get("petrol") or prices.get("Petrol")

        stations.append({
            "site_id":    str(s.get("site_id", "")),
            "brand":      s.get("brand", retailer),
            "retailer":   retailer,
            "name":       s.get("name") or s.get("brand") or retailer,
            "address":    s.get("address", ""),
            "postcode":   s.get("postcode", ""),
            "lat":        lat,
            "lon":        lon,
            "diesel_ppl": float(diesel_ppl) if diesel_ppl is not None else None,
            "petrol_ppl": float(petrol_ppl) if petrol_ppl is not None else None,
        })
    return stations


# ── Main fetch ─────────────────────────────────────────────────────────────────
def fetch_stations_near(
    lat: float,
    lon: float,
    radius_km: float = 25.0,
    fuel_type: str = "diesel",
    per_feed_timeout: int = 7,
) -> dict:
    """
    Fetch stations with live prices within radius_km of (lat, lon).

    Returns:
        {
          "stations":      [...sorted by price...],
          "sources_ok":    ["Asda", "Tesco", ...],
          "sources_failed":["BP", ...],
          "last_updated":  "HH:MM",
        }
    """
    price_key = "diesel_ppl" if fuel_type == "diesel" else "petrol_ppl"
    all_stations: List[dict] = []
    sources_ok: List[str] = []
    sources_failed: List[str] = []

    for feed in CMA_FEEDS:
        try:
            r = requests.get(
                feed["url"],
                timeout=per_feed_timeout,
                headers={"User-Agent": "AgriRoute/1.0"},
            )
            if r.status_code != 200:
                sources_failed.append(feed["retailer"])
                continue
            raw = r.json()
            parsed = _parse_feed(raw, feed["retailer"])

            nearby = []
            for s in parsed:
                d = haversine_km(lat, lon, s["lat"], s["lon"])
                if d <= radius_km and s.get(price_key) is not None:
                    s["distance_from_centre_km"] = round(d, 1)
                    nearby.append(s)

            all_stations.extend(nearby)
            sources_ok.append(feed["retailer"])

        except Exception:
            sources_failed.append(feed["retailer"])

    # De-duplicate: stations within 200 m are the same site —
    # keep whichever has a price; prefer the cheaper one
    unique: List[dict] = []
    for s in all_stations:
        duplicate = False
        for u in unique:
            if haversine_km(s["lat"], s["lon"], u["lat"], u["lon"]) < 0.2:
                duplicate = True
                # Replace if this one has a better price
                if s.get(price_key) and (not u.get(price_key) or s[price_key] < u[price_key]):
                    unique.remove(u)
                    unique.append(s)
                break
        if not duplicate:
            unique.append(s)

    # Sort cheapest first (for the chosen fuel type)
    with_prices = [s for s in unique if s.get(price_key) is not None]
    with_prices.sort(key=lambda s: s[price_key])

    from datetime import datetime
    return {
        "stations":       with_prices,
        "sources_ok":     sources_ok,
        "sources_failed": sources_failed,
        "last_updated":   datetime.now().strftime("%H:%M"),
    }


# ── ROI scoring ────────────────────────────────────────────────────────────────
def score_refuel_stop(
    station: dict,
    waypoints: List[Tuple[float, float]],
    litres_needed: float,
    work_rate_ha_hr: float,
    cost_per_ha: float,
    avg_speed_kmh: float,
    fuel_type: str = "diesel",
) -> dict:
    """
    Quantify the ROI impact of stopping at a given fuel station.

    Metrics returned (added to station dict):
        ppl             — price in pence per litre
        fill_cost       — £ to fill up here
        detour_km       — extra km vs skipping station
        time_lost_min   — minutes lost to detour
        ha_lost         — hectares not worked due to detour time
        revenue_lost    — £ revenue foregone
        net_roi_impact  — total cost of stop (fill + opportunity)
        savings_vs_base — £ saved vs using configured price (negative = cost)
        best_insertion  — index of waypoint leg to insert station into
    """
    price_key = "diesel_ppl" if fuel_type == "diesel" else "petrol_ppl"
    ppl = station.get(price_key, 0) or 0
    fill_cost = round(litres_needed * ppl / 100, 2)  # pence → £

    # Find the route leg where inserting this station adds least extra distance
    if len(waypoints) >= 2:
        min_detour = float("inf")
        best_leg = 0
        for i in range(len(waypoints) - 1):
            a, b = waypoints[i], waypoints[i + 1]
            direct = haversine_km(a[0], a[1], b[0], b[1])
            via = (
                haversine_km(a[0], a[1], station["lat"], station["lon"])
                + haversine_km(station["lat"], station["lon"], b[0], b[1])
            )
            extra = max(0.0, via - direct)
            if extra < min_detour:
                min_detour = extra
                best_leg = i
        detour_km = round(min_detour, 1)
    else:
        detour_km = station.get("distance_from_centre_km", 5.0) * 2
        best_leg = 0

    time_lost_min = round(detour_km / max(avg_speed_kmh, 1) * 60, 1)
    ha_lost = round(time_lost_min / 60 * work_rate_ha_hr, 2)
    revenue_lost = round(ha_lost * cost_per_ha, 2)
    net_roi_impact = round(fill_cost + revenue_lost, 2)

    return {
        **station,
        "litres":           round(litres_needed, 0),
        "ppl":              ppl,
        "fill_cost":        fill_cost,
        "detour_km":        detour_km,
        "time_lost_min":    time_lost_min,
        "ha_lost":          ha_lost,
        "revenue_lost":     revenue_lost,
        "net_roi_impact":   net_roi_impact,
        "best_insertion":   best_leg,
    }


def cheapest_nearby(
    stations: List[dict],
    fuel_type: str = "diesel",
) -> Optional[dict]:
    """Return the cheapest station from a pre-fetched list."""
    price_key = "diesel_ppl" if fuel_type == "diesel" else "petrol_ppl"
    with_prices = [s for s in stations if s.get(price_key)]
    if not with_prices:
        return None
    return min(with_prices, key=lambda s: s[price_key])
