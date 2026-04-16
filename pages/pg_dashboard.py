"""Dashboard — Overview of all farms, fields, priorities and map."""
import streamlit as st
import pandas as pd
from utils.data_models import calc_priority_score, OPERATION_TYPES


def render(data: dict):
    st.title("Dashboard")

    farms      = data.get("farms", {})
    contractor = data.get("contractor", {})

    if not contractor:
        st.warning("Welcome to AgriRoute! Start by setting up your contractor profile in **Contractor Setup**.")
        return

    if not farms:
        st.info("No farms registered yet. Head to **Farms & Fields** to add your first farm.")
        return

    # Flatten all fields
    all_fields = []
    for farm_id, farm in farms.items():
        for fid, field in farm.get("fields", {}).items():
            f = field.copy()
            f["farm_name"] = farm["name"]
            f["farm_id"]   = farm_id
            all_fields.append(f)

    total_ha  = sum(f.get("hectares", 0) for f in all_fields)
    ops_log   = data.get("operations_log", [])
    total_rev = sum(op.get("revenue", 0) for op in ops_log)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Farms",         len(farms))
    c2.metric("Fields",        len(all_fields))
    c3.metric("Total Hectares", f"{total_ha:.0f} ha")
    c4.metric("Jobs Completed", len(ops_log))
    c5.metric("Total Revenue",  f"£{total_rev:,.0f}")

    st.markdown("---")

    # ── Priority table ────────────────────────────────────────────────────────
    st.subheader("Field Priority Overview")

    col_op, col_filter = st.columns([2, 2])
    with col_op:
        op_select = st.selectbox("Operation type", OPERATION_TYPES, key="dash_op")
    with col_filter:
        farm_filter = st.selectbox("Filter by farm", ["All farms"] + [f["name"] for f in farms.values()], key="dash_farm")

    rows = []
    for f in all_fields:
        if farm_filter != "All farms" and f["farm_name"] != farm_filter:
            continue
        score = calc_priority_score(f, op_select)
        rows.append({
            "Farm":           f["farm_name"],
            "Field":          f["name"],
            "Crop":           f.get("crop_type", ""),
            "Variety":        f.get("variety", ""),
            "BBCH":           f.get("bbch_stage", 0),
            "Ha":             f.get("hectares", 0),
            "Disease Risk":   f.get("disease_risk", "Low"),
            "Maturity":       f.get("variety_maturity", "Mid"),
            "Priority Score": round(score, 1),
        })

    if rows:
        df = pd.DataFrame(rows).sort_values("Priority Score", ascending=False)

        def colour_score(val):
            if val >= 70:   return "background-color: #ffd6d6"
            elif val >= 40: return "background-color: #fff3cd"
            else:           return "background-color: #d4edda"

        styled = df.style.map(colour_score, subset=["Priority Score"])
        st.dataframe(styled, use_container_width=True, hide_index=True)

        high  = len(df[df["Priority Score"] >= 70])
        med   = len(df[(df["Priority Score"] >= 40) & (df["Priority Score"] < 70)])
        low_c = len(df[df["Priority Score"] < 40])
        st.markdown(
            f"🔴 **{high} High priority** &nbsp;|&nbsp; "
            f"🟡 **{med} Medium** &nbsp;|&nbsp; "
            f"🟢 **{low_c} Low**",
            unsafe_allow_html=True,
        )

    st.markdown("---")

    # ── Map ────────────────────────────────────────────────────────────────────
    st.subheader("Farm Locations")
    try:
        import folium
        from streamlit_folium import st_folium

        if all_fields:
            mid_lat = sum(f["lat"] for f in all_fields) / len(all_fields)
            mid_lon = sum(f["lon"] for f in all_fields) / len(all_fields)
        else:
            mid_lat, mid_lon = 52.5, -1.5

        m = folium.Map(location=[mid_lat, mid_lon], zoom_start=10, tiles="OpenStreetMap")

        home = contractor.get("home_coords")
        if home:
            folium.Marker(
                [home["lat"], home["lon"]],
                popup="Home Base",
                tooltip="Home Base",
                icon=folium.Icon(color="red", icon="home", prefix="fa"),
            ).add_to(m)

        for f in all_fields:
            score = calc_priority_score(f, op_select)
            col   = "red" if score >= 70 else ("orange" if score >= 40 else "green")
            folium.CircleMarker(
                [f["lat"], f["lon"]],
                radius=8,
                popup=f"{f['name']} | {f.get('farm_name','')} | {f.get('crop_type','')} | Score: {score:.0f}",
                tooltip=f"{f['name']} ({f.get('crop_type','')}) — {score:.0f}",
                color=col, fill=True, fill_color=col, fill_opacity=0.7,
            ).add_to(m)

        st_folium(m, width=None, height=440, use_container_width=True)
    except ImportError:
        st.info("Install streamlit-folium for the interactive map: `pip install streamlit-folium`")
