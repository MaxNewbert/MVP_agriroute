"""
AgriRoute - Data Models & State Management
All farm, field, operation and session data structures
"""
import json
import os
from datetime import datetime
from typing import Dict, List, Optional

# ── Default data path ─────────────────────────────────────────────────────────
DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "agriroute_data.json")

# ── BBCH Growth Stage Reference ───────────────────────────────────────────────
BBCH_STAGES = {
    0:  "Dry seed",
    10: "Seedling / First leaf",
    20: "Tillering begins",
    21: "1 Tiller",
    22: "2 Tillers",
    23: "3 Tillers",
    25: "5 Tillers",
    30: "Stem elongation",
    31: "1st node detectable",
    32: "2nd node detectable",
    37: "Flag leaf just visible",
    39: "Flag leaf ligule visible",
    41: "Early boot",
    49: "First awns visible",
    51: "Beginning of heading",
    59: "End of heading",
    61: "Beginning of flowering",
    65: "Full flowering",
    69: "End of flowering",
    71: "Watery ripe",
    73: "Early milk",
    75: "Medium milk",
    77: "Late milk",
    83: "Early dough",
    85: "Soft dough",
    87: "Hard dough",
    89: "Nearly ripe",
    91: "Ripening / Caryopsis hard",
    92: "Caryopsis hard",
    99: "Harvest ripe",
}

# ── Crop Types ────────────────────────────────────────────────────────────────
CROP_TYPES = [
    "Winter Wheat", "Spring Wheat", "Winter Barley", "Spring Barley",
    "Winter Oilseed Rape", "Spring Oilseed Rape", "Winter Oats", "Spring Oats",
    "Maize", "Sugar Beet", "Potatoes", "Peas", "Beans", "Rye",
    "Triticale", "Linseed", "Other",
]

# ── Operation Types ───────────────────────────────────────────────────────────
OPERATION_TYPES = ["Spraying", "Seeding / Drilling", "Fertiliser", "Harvest"]

# ── Default work rates (ha/hr) ────────────────────────────────────────────────
DEFAULT_WORK_RATES = {
    "Spraying":          25.0,
    "Seeding / Drilling": 8.0,
    "Fertiliser":        30.0,
    "Harvest":            6.0,
}

# ── Default costs (£/ha) ─────────────────────────────────────────────────────
DEFAULT_COSTS = {
    "Spraying":          8.0,
    "Seeding / Drilling": 35.0,
    "Fertiliser":        12.0,
    "Harvest":           75.0,
}


# ── Priority scoring ──────────────────────────────────────────────────────────
def calc_priority_score(field: dict, operation: str) -> float:
    """Returns a 0–100 urgency score for a field+operation combination."""
    score = 0.0
    bbch  = field.get("bbch_stage", 0)
    crop  = field.get("crop_type", "")
    dis   = field.get("disease_risk", "Low")
    mat   = field.get("variety_maturity", "Mid")
    days  = field.get("days_since_last_op", {}).get(operation, 999)

    if operation == "Spraying":
        if   31 <= bbch <= 32: score += 40
        elif bbch == 37:        score += 35
        elif 39 <= bbch <= 41: score += 30
        elif 59 <= bbch <= 65: score += 20
        elif bbch > 65:        score += 5
        score += {"Low": 0, "Medium": 15, "High": 30}.get(dis, 0)

    elif operation == "Seeding / Drilling":
        if   bbch == 0:  score += 50
        elif bbch < 10:  score += 30
        elif days > 7:   score += 20

    elif operation == "Fertiliser":
        if   20 <= bbch <= 25: score += 40
        elif 30 <= bbch <= 37: score += 35
        elif bbch < 20:        score += 20

    elif operation == "Harvest":
        if   bbch >= 91: score += 60
        elif bbch >= 87: score += 40
        elif bbch >= 83: score += 20
        if mat == "Early":   score += 15
        elif mat == "Mid":   score += 5

    if days > 14:  score += 10
    elif days > 7: score += 5

    if crop == "Winter Oilseed Rape" and operation == "Spraying":
        score += 5

    return min(score, 100.0)


# ── JSON persistence ──────────────────────────────────────────────────────────
def load_data() -> dict:
    path = os.path.abspath(DATA_FILE)
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return {
        "contractor": {},
        "farms": {},
        "operations_log": [],
        "work_rates": DEFAULT_WORK_RATES.copy(),
        "costs": DEFAULT_COSTS.copy(),
    }


def save_data(data: dict):
    path = os.path.abspath(DATA_FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


# ── Factory helpers ───────────────────────────────────────────────────────────
def _uid() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S%f")


def new_farm(name: str, client_name: str, lat: float, lon: float,
             address: str = "") -> dict:
    return {
        "id":          f"farm_{_uid()}",
        "name":        name,
        "client_name": client_name,
        "address":     address,
        "lat":         lat,
        "lon":         lon,
        "fields":      {},
        "created":     datetime.now().isoformat(),
    }


def new_field(name: str, hectares: float, crop: str, variety: str,
              bbch: int, lat: float, lon: float,
              disease_risk: str = "Low", maturity: str = "Mid",
              sow_date: str = "") -> dict:
    return {
        "id":                 f"field_{_uid()}",
        "name":               name,
        "hectares":           hectares,
        "crop_type":          crop,
        "variety":            variety,
        "bbch_stage":         bbch,
        "disease_risk":       disease_risk,
        "variety_maturity":   maturity,
        "sow_date":           sow_date,
        "lat":                lat,
        "lon":                lon,
        "days_since_last_op": {op: 999 for op in OPERATION_TYPES},
        "completed_operations": [],
        "files":              [],
        "created":            datetime.now().isoformat(),
    }


def new_operation_log(farm_id: str, field_id: str, farm_name: str,
                      field_name: str, operation: str,
                      date: str, operator: str, hectares: float,
                      revenue: float, **kwargs) -> dict:
    return {
        "id":           f"op_{_uid()}",
        "farm_id":      farm_id,
        "field_id":     field_id,
        "farm_name":    farm_name,
        "field_name":   field_name,
        "operation":    operation,
        "date":         date,
        "operator":     operator,
        "hectares":     hectares,
        "revenue":      revenue,
        "products":     kwargs.get("products", []),
        "application":  kwargs.get("application", {}),
        "weather":      kwargs.get("weather", {}),
        "weather_warnings": kwargs.get("weather_warnings", []),
        "buffer_zones": kwargs.get("buffer_zones", []),
        "equipment":    kwargs.get("equipment", ""),
        "gps_system":   kwargs.get("gps_system", ""),
        "notes":        kwargs.get("notes", ""),
        "justification": kwargs.get("justification", {}),
        "created":      datetime.now().isoformat(),
    }
