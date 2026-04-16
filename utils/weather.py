"""
AgriRoute - Weather Utility
Uses Open-Meteo (free, no key) for forecasts.
"""
import requests
from datetime import datetime
from typing import Optional

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

THRESHOLDS = {
    "Spraying": {
        "wind_max_ms": 5.0,
        "rain_max_mm": 0.5,
        "temp_min_c":  5.0,
        "temp_max_c": 25.0,
    },
    "Seeding / Drilling": {
        "wind_max_ms": 99.0,
        "rain_max_mm":  5.0,
        "temp_min_c":  -2.0,
        "temp_max_c":  30.0,
    },
    "Fertiliser": {
        "wind_max_ms": 10.0,
        "rain_max_mm":  2.0,
        "temp_min_c":  -2.0,
        "temp_max_c":  30.0,
    },
    "Harvest": {
        "wind_max_ms": 15.0,
        "rain_max_mm":  0.0,
        "temp_min_c":   5.0,
        "temp_max_c":  40.0,
    },
}

WMO_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Foggy", 48: "Icy fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Heavy drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
    80: "Slight showers", 81: "Moderate showers", 82: "Heavy showers",
    95: "Thunderstorm", 96: "Thunderstorm + hail", 99: "Thunderstorm + heavy hail",
}


def get_forecast(lat: float, lon: float, days: int = 7) -> Optional[dict]:
    params = {
        "latitude":   lat,
        "longitude":  lon,
        "hourly": [
            "temperature_2m", "precipitation", "windspeed_10m",
            "winddirection_10m", "relativehumidity_2m", "weathercode",
        ],
        "daily": [
            "weathercode", "temperature_2m_max", "temperature_2m_min",
            "precipitation_sum", "windspeed_10m_max",
        ],
        "forecast_days": min(days, 7),
        "windspeed_unit": "ms",
        "timezone": "Europe/London",
    }
    try:
        r = requests.get(OPEN_METEO_URL, params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"Weather API error: {e}")
        return None


def check_operation_window(lat: float, lon: float, operation: str,
                            start_hour: int = 7, duration_hours: int = 10,
                            target_date: Optional[str] = None) -> dict:
    data = get_forecast(lat, lon, days=7)
    if not data:
        return {"ok": True, "warnings": ["Weather data unavailable — check manually"],
                "hourly": [], "summary": {}}

    thresholds = THRESHOLDS.get(operation, {})
    times      = data["hourly"]["time"]
    temps      = data["hourly"]["temperature_2m"]
    precip     = data["hourly"]["precipitation"]
    wind       = data["hourly"]["windspeed_10m"]
    wind_dir   = data["hourly"]["winddirection_10m"]
    humidity   = data["hourly"]["relativehumidity_2m"]
    wcode      = data["hourly"]["weathercode"]

    if target_date is None:
        target_date = datetime.now().strftime("%Y-%m-%d")

    relevant, warnings = [], []

    for i, t in enumerate(times):
        dt = datetime.fromisoformat(t)
        if dt.strftime("%Y-%m-%d") == target_date and start_hour <= dt.hour < (start_hour + duration_hours):
            relevant.append({
                "time":        t,
                "hour":        dt.hour,
                "temp":        temps[i],
                "precip":      precip[i],
                "wind":        wind[i],
                "wind_dir":    wind_dir[i],
                "humidity":    humidity[i],
                "description": WMO_CODES.get(wcode[i], ""),
            })

    if not relevant:
        return {"ok": True, "warnings": ["No forecast data for selected date"],
                "hourly": [], "summary": {}}

    max_wind   = max(h["wind"] for h in relevant)
    total_rain = sum(h["precip"] for h in relevant)
    min_temp   = min(h["temp"] for h in relevant)
    max_temp   = max(h["temp"] for h in relevant)
    ok = True

    if max_wind > thresholds.get("wind_max_ms", 99):
        mph = max_wind * 2.237
        warnings.append(
            f"⚠️ High wind: {max_wind:.1f} m/s ({mph:.0f} mph) — "
            f"limit for {operation} is {thresholds['wind_max_ms']} m/s ({thresholds['wind_max_ms']*2.237:.0f} mph)"
        )
        ok = False

    if total_rain > thresholds.get("rain_max_mm", 99):
        warnings.append(
            f"⛈️ Rainfall: {total_rain:.1f} mm forecast — limit for {operation} is {thresholds['rain_max_mm']} mm"
        )
        ok = False

    if min_temp < thresholds.get("temp_min_c", -99):
        warnings.append(f"🌡️ Low temp: {min_temp:.1f} °C — below minimum for {operation}")
        ok = False

    if max_temp > thresholds.get("temp_max_c", 99):
        warnings.append(f"🌡️ High temp: {max_temp:.1f} °C — above maximum for {operation}")
        ok = False

    if not warnings:
        warnings.append(f"✅ Conditions suitable for {operation} on {target_date}")

    return {
        "ok":       ok,
        "warnings": warnings,
        "hourly":   relevant,
        "summary": {
            "max_wind_ms":   round(max_wind, 1),
            "max_wind_mph":  round(max_wind * 2.237, 1),
            "total_rain_mm": round(total_rain, 2),
            "min_temp":      round(min_temp, 1),
            "max_temp":      round(max_temp, 1),
        },
    }


def get_daily_suitability(lat: float, lon: float, operation: str) -> list:
    """Return 7-day list with daily go/no-go for an operation."""
    data = get_forecast(lat, lon, days=7)
    if not data or "daily" not in data:
        return []

    thresholds = THRESHOLDS.get(operation, {})
    days_out   = []
    daily      = data["daily"]

    for i, date in enumerate(daily["time"]):
        max_wind   = daily["windspeed_10m_max"][i] or 0
        total_rain = daily["precipitation_sum"][i] or 0
        max_temp   = daily["temperature_2m_max"][i] or 0
        min_temp   = daily["temperature_2m_min"][i] or 0
        wcode      = daily["weathercode"][i] or 0

        ok = (
            max_wind   <= thresholds.get("wind_max_ms", 99) and
            total_rain <= thresholds.get("rain_max_mm", 99) and
            min_temp   >= thresholds.get("temp_min_c", -99) and
            max_temp   <= thresholds.get("temp_max_c", 99)
        )
        days_out.append({
            "date":        date,
            "ok":          ok,
            "max_wind_ms": round(max_wind, 1),
            "max_wind_mph": round(max_wind * 2.237, 1),
            "rain_mm":     round(total_rain, 1),
            "max_temp":    round(max_temp, 1),
            "min_temp":    round(min_temp, 1),
            "description": WMO_CODES.get(wcode, ""),
        })
    return days_out


def wind_direction_label(degrees: float) -> str:
    dirs = ["N","NNE","NE","ENE","E","ESE","SE","SSE",
            "S","SSW","SW","WSW","W","WNW","NW","NNW"]
    return dirs[round(degrees / (360 / len(dirs))) % len(dirs)]
