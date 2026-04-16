"""Contractor Setup — profile, home base, work rates, costs, equipment."""
import streamlit as st
from utils.data_models import save_data, OPERATION_TYPES, DEFAULT_WORK_RATES, DEFAULT_COSTS, DEFAULT_FUEL


def _geocode(address: str):
    """Geocode an address using Nominatim (free, no key)."""
    import requests
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": address, "format": "json", "limit": 1},
            headers={"User-Agent": "AgriRoute/1.0"},
            timeout=8,
        )
        results = r.json()
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])
    except Exception:
        pass
    return None, None


def render(data: dict):
    st.title("Contractor Setup")
    st.markdown("Configure your contractor profile, home base, work rates and equipment.")

    contractor = data.get("contractor", {})
    work_rates = data.get("work_rates", DEFAULT_WORK_RATES.copy())
    costs      = data.get("costs",      DEFAULT_COSTS.copy())

    # ── Profile ───────────────────────────────────────────────────────────────
    with st.expander("Contractor Profile", expanded=not bool(contractor.get("name"))):
        with st.form("form_profile"):
            name    = st.text_input("Business / Contractor Name", value=contractor.get("name", ""))
            address = st.text_input("Business Address",            value=contractor.get("address", ""))
            cert    = st.text_input("PA1/PA2 Certificate Number",  value=contractor.get("cert_number", ""))
            phone   = st.text_input("Phone",                       value=contractor.get("phone", ""))
            email   = st.text_input("Email",                       value=contractor.get("email", ""))

            st.markdown("**Default Operator Name(s)**")
            operators_raw = st.text_area(
                "One per line",
                value="\n".join(contractor.get("operators", [])),
                height=80,
            )

            st.markdown("**Home Base Location**")
            home_address = st.text_input(
                "Home address (will be geocoded)",
                value=contractor.get("home_address", ""),
                placeholder="e.g. Grantham, Lincolnshire",
            )
            col1, col2 = st.columns(2)
            home_lat = col1.number_input("Home Lat (override)", value=contractor.get("home_coords", {}).get("lat", 0.0), format="%.6f")
            home_lon = col2.number_input("Home Lon (override)", value=contractor.get("home_coords", {}).get("lon", 0.0), format="%.6f")

            if st.form_submit_button("Save Profile", type="primary"):
                # Try geocoding if address changed
                if home_address and home_address != contractor.get("home_address"):
                    lat, lon = _geocode(home_address)
                    if lat:
                        home_lat, home_lon = lat, lon
                        st.success(f"Geocoded: {home_lat:.5f}, {home_lon:.5f}")
                    else:
                        st.warning("Could not geocode address — enter coordinates manually.")

                data["contractor"].update({
                    "name":         name,
                    "address":      address,
                    "cert_number":  cert,
                    "phone":        phone,
                    "email":        email,
                    "operators":    [o.strip() for o in operators_raw.splitlines() if o.strip()],
                    "home_address": home_address,
                    "home_location": home_address or f"{home_lat:.4f},{home_lon:.4f}",
                    "home_coords":  {"lat": home_lat, "lon": home_lon},
                })
                save_data(data)
                st.success("Profile saved.")

    # ── Work Rates ────────────────────────────────────────────────────────────
    with st.expander("Work Rates & Costs per Operation", expanded=True):
        st.markdown("Set your **work rate (ha/hr)** and **charge (£/ha)** per operation type.")
        with st.form("form_rates"):
            cols = st.columns(4)
            new_rates = {}
            new_costs = {}
            for i, op in enumerate(OPERATION_TYPES):
                with cols[i]:
                    st.markdown(f"**{op}**")
                    new_rates[op] = st.number_input(
                        "ha/hr", value=float(work_rates.get(op, DEFAULT_WORK_RATES[op])),
                        min_value=0.1, step=0.5, key=f"rate_{op}",
                    )
                    new_costs[op] = st.number_input(
                        "£/ha",  value=float(costs.get(op, DEFAULT_COSTS[op])),
                        min_value=0.0, step=1.0, key=f"cost_{op}",
                    )

            avg_speed = st.number_input(
                "Average road speed (km/h) — used for travel time estimates",
                value=float(data.get("avg_speed_kmh", 50)),
                min_value=10.0, max_value=120.0, step=5.0,
            )
            max_day_hrs = st.number_input(
                "Max working hours per day",
                value=float(data.get("max_day_hours", 10)),
                min_value=4.0, max_value=16.0, step=0.5,
            )
            start_hr = st.number_input(
                "Default start time (hour, 24h)",
                value=float(data.get("default_start_hr", 7)),
                min_value=4.0, max_value=12.0, step=0.5,
            )

            if st.form_submit_button("Save Rates & Settings", type="primary"):
                data["work_rates"]       = new_rates
                data["costs"]            = new_costs
                data["avg_speed_kmh"]    = avg_speed
                data["max_day_hours"]    = max_day_hrs
                data["default_start_hr"] = start_hr
                save_data(data)
                st.success("Rates & settings saved.")

    # ── Fuel & Running Costs ──────────────────────────────────────────────────
    with st.expander("Fuel & Running Costs", expanded=False):
        st.markdown(
            "Set your current fuel price and consumption rates. These are used in the "
            "Day Planner to calculate fuel costs for road travel between fields and "
            "for in-field operations, feeding into your ROI."
        )
        fuel = data.get("fuel", {})

        with st.form("form_fuel"):
            fc1, fc2 = st.columns(2)
            fuel_price = fc1.number_input(
                "Fuel price (£/litre)",
                value=float(fuel.get("price_per_litre", DEFAULT_FUEL["price_per_litre"])),
                min_value=0.50, max_value=5.00, step=0.01, format="%.2f",
                help="Update this regularly to match current pump prices",
            )
            road_consumption = fc2.number_input(
                "Road fuel use (L/100 km)",
                value=float(fuel.get("road_litres_per_100km", DEFAULT_FUEL["road_litres_per_100km"])),
                min_value=1.0, max_value=100.0, step=0.5,
                help="Fuel consumption of your vehicle/tractor travelling between fields on the road",
            )

            st.markdown("**In-field fuel consumption (L/ha) per operation**")
            st.caption("Covers engine hours while working in the field, not road travel.")
            op_cols = st.columns(4)
            op_fuel_in = {}
            op_defaults = DEFAULT_FUEL["op_litres_per_ha"]
            saved_op_fuel = fuel.get("op_litres_per_ha", {})
            for i, op in enumerate(OPERATION_TYPES):
                op_fuel_in[op] = op_cols[i].number_input(
                    op,
                    value=float(saved_op_fuel.get(op, op_defaults.get(op, 10.0))),
                    min_value=0.0, max_value=200.0, step=0.5,
                    key=f"fuel_op_{op}",
                )

            if st.form_submit_button("Save Fuel Settings", type="primary"):
                data["fuel"] = {
                    "price_per_litre":       fuel_price,
                    "road_litres_per_100km": road_consumption,
                    "op_litres_per_ha":      op_fuel_in,
                }
                save_data(data)
                st.success("Fuel settings saved.")

        # Live cost preview
        fuel_now = data.get("fuel", {})
        if fuel_now.get("price_per_litre"):
            st.markdown("**Cost preview at current price:**")
            price = fuel_now["price_per_litre"]
            road  = fuel_now.get("road_litres_per_100km", DEFAULT_FUEL["road_litres_per_100km"])
            prev_cols = st.columns(5)
            prev_cols[0].metric("Road (per 10 km)", f"£{road * 10/100 * price:.2f}")
            for i, op in enumerate(OPERATION_TYPES):
                lpha = fuel_now.get("op_litres_per_ha", {}).get(op, DEFAULT_FUEL["op_litres_per_ha"][op])
                prev_cols[i+1].metric(f"{op} (per ha)", f"£{lpha * price:.2f}")

    # ── Equipment Register ────────────────────────────────────────────────────
    with st.expander("Equipment Register"):
        st.markdown("List your machinery (used to auto-populate completion reports).")
        equipment = data.get("equipment", [])

        with st.form("form_equipment"):
            equip_raw = st.text_area(
                "One item per line  (e.g. 'Amazone UX5200 — 24m boom')",
                value="\n".join(equipment),
                height=150,
            )
            if st.form_submit_button("Save Equipment"):
                data["equipment"] = [e.strip() for e in equip_raw.splitlines() if e.strip()]
                save_data(data)
                st.success("Equipment list saved.")

    # ── Agronomist Register ───────────────────────────────────────────────────
    with st.expander("Agronomist / Advisor Register"):
        st.markdown("Save your agronomists' details so they can be selected quickly in completion reports.")
        agronomists = data.get("agronomists", [])

        # Display existing
        if agronomists:
            import pandas as pd
            ag_df = pd.DataFrame(agronomists)
            st.dataframe(ag_df[["name","company","email","phone"]].rename(columns={
                "name":"Name","company":"Company","email":"Email","phone":"Phone"
            }), use_container_width=True, hide_index=True)

        st.markdown("**Add / Update Agronomist**")
        with st.form("form_agronomist"):
            ac1, ac2 = st.columns(2)
            ag_name    = ac1.text_input("Name",    placeholder="Dr. Jane Smith")
            ag_company = ac2.text_input("Company", placeholder="ADAS / Hutchinsons etc.")
            ac3, ac4 = st.columns(2)
            ag_email   = ac3.text_input("Email",   placeholder="jane@example.com")
            ag_phone   = ac4.text_input("Phone",   placeholder="07700 000000")
            ag_notes   = st.text_input("Notes",    placeholder="BASIS P1 — cereals specialist")

            if st.form_submit_button("Add Agronomist"):
                if ag_name:
                    entry = {
                        "name":    ag_name,
                        "company": ag_company,
                        "email":   ag_email,
                        "phone":   ag_phone,
                        "notes":   ag_notes,
                    }
                    data.setdefault("agronomists", []).append(entry)
                    save_data(data)
                    st.success(f"Agronomist '{ag_name}' saved.")
                    st.rerun()

        if agronomists:
            del_name = st.selectbox("Remove agronomist", ["—"] + [a["name"] for a in agronomists])
            if del_name != "—" and st.button("Remove", type="secondary"):
                data["agronomists"] = [a for a in agronomists if a["name"] != del_name]
                save_data(data)
                st.rerun()

    # ── Current config summary ────────────────────────────────────────────────
    if contractor.get("name"):
        st.markdown("---")
        st.subheader("Current Configuration")
        c1, c2 = st.columns(2)
        c1.markdown(f"**Contractor:** {contractor.get('name')}")
        c1.markdown(f"**Home Base:** {contractor.get('home_location', 'Not set')}")
        c1.markdown(f"**Cert No:** {contractor.get('cert_number', '—')}")
        c2.markdown(f"**Operators:** {', '.join(contractor.get('operators', ['—']))}")
        c2.markdown(f"**Road Speed:** {data.get('avg_speed_kmh', 50)} km/h")
        c2.markdown(f"**Max Day:** {data.get('max_day_hours', 10)} hrs")
