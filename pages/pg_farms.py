"""Farms & Fields — add/edit farms and fields, view on interactive map."""
import streamlit as st
from utils.data_models import (save_data, new_farm, new_field,
                                CROP_TYPES, OPERATION_TYPES, BBCH_STAGES,
                                calc_priority_score)


def _geocode(address: str):
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


def _all_fields(farms: dict) -> list:
    out = []
    for farm_id, farm in farms.items():
        for fid, field in farm.get("fields", {}).items():
            f = field.copy()
            f["farm_id"]   = farm_id
            f["farm_name"] = farm["name"]
            out.append(f)
    return out


def render(data: dict):
    st.title("Farms & Fields")

    farms = data.get("farms", {})

    tab_map, tab_add_farm, tab_add_field, tab_edit = st.tabs(
        ["Map View", "Add Farm", "Add Field", "Edit / Delete"]
    )

    # ── MAP ────────────────────────────────────────────────────────────────────
    with tab_map:
        all_f = _all_fields(farms)
        if not all_f:
            st.info("No fields yet. Add a farm and fields using the tabs above.")
        else:
            op_col = st.selectbox("Colour markers by priority for:", OPERATION_TYPES, key="map_op")
            try:
                import folium
                from streamlit_folium import st_folium

                mid_lat = sum(f["lat"] for f in all_f) / len(all_f)
                mid_lon = sum(f["lon"] for f in all_f) / len(all_f)
                m = folium.Map(location=[mid_lat, mid_lon], zoom_start=11, tiles="OpenStreetMap")

                home = data.get("contractor", {}).get("home_coords")
                if home:
                    folium.Marker(
                        [home["lat"], home["lon"]],
                        popup="Home Base",
                        icon=folium.Icon(color="red", icon="home", prefix="fa"),
                    ).add_to(m)

                # Farm clusters
                farm_fg = folium.FeatureGroup(name="Farm Pins")
                for fid, farm in farms.items():
                    folium.Marker(
                        [farm["lat"], farm["lon"]],
                        popup=f"<b>{farm['name']}</b><br>{farm.get('client_name','')}",
                        tooltip=farm["name"],
                        icon=folium.Icon(color="blue", icon="tractor", prefix="fa"),
                    ).add_to(farm_fg)
                farm_fg.add_to(m)

                # Fields
                field_fg = folium.FeatureGroup(name="Fields")
                for f in all_f:
                    score = calc_priority_score(f, op_col)
                    col   = "red" if score >= 70 else ("orange" if score >= 40 else "green")
                    popup_html = (
                        f"<b>{f['name']}</b><br>"
                        f"Farm: {f['farm_name']}<br>"
                        f"Crop: {f.get('crop_type','')} {f.get('variety','')}<br>"
                        f"BBCH: {f.get('bbch_stage',0)} — {BBCH_STAGES.get(f.get('bbch_stage',0),'')}<br>"
                        f"Area: {f.get('hectares',0)} ha<br>"
                        f"Disease Risk: {f.get('disease_risk','Low')}<br>"
                        f"Priority ({op_col}): {score:.0f}"
                    )
                    folium.CircleMarker(
                        [f["lat"], f["lon"]],
                        radius=9,
                        popup=folium.Popup(popup_html, max_width=260),
                        tooltip=f"{f['name']} — {score:.0f}",
                        color=col, fill=True, fill_color=col, fill_opacity=0.75,
                    ).add_to(field_fg)
                field_fg.add_to(m)

                folium.LayerControl().add_to(m)
                st_folium(m, width=None, height=500, use_container_width=True)
            except ImportError:
                st.info("Install streamlit-folium for the interactive map.")

            # Summary table
            rows = []
            for f in all_f:
                rows.append({
                    "Farm":    f["farm_name"],
                    "Field":   f["name"],
                    "Crop":    f.get("crop_type", ""),
                    "Variety": f.get("variety", ""),
                    "Ha":      f.get("hectares", 0),
                    "BBCH":    f.get("bbch_stage", 0),
                    "Disease": f.get("disease_risk", "Low"),
                    "Sown":    f.get("sow_date", ""),
                })
            import pandas as pd
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # ── ADD FARM ────────────────────────────────────────────────────────────────
    with tab_add_farm:
        st.subheader("Register a new farm / client")
        with st.form("form_add_farm"):
            farm_name    = st.text_input("Farm Name", placeholder="Manor Farm")
            client_name  = st.text_input("Grower / Client Name", placeholder="J. Smith")
            farm_address = st.text_input("Farm Address (will be geocoded)",
                                          placeholder="e.g. Sleaford, Lincolnshire")
            col1, col2 = st.columns(2)
            farm_lat = col1.number_input("Latitude (override)",  value=0.0, format="%.6f")
            farm_lon = col2.number_input("Longitude (override)", value=0.0, format="%.6f")

            submitted = st.form_submit_button("Add Farm", type="primary")

        if submitted:
            if not farm_name or not client_name:
                st.error("Farm name and client name are required.")
            else:
                lat, lon = farm_lat, farm_lon
                if farm_address:
                    glat, glon = _geocode(farm_address)
                    if glat:
                        lat, lon = glat, glon
                        st.success(f"Geocoded to {lat:.5f}, {lon:.5f}")
                    else:
                        st.warning("Could not geocode — using manual coordinates.")
                if lat == 0.0 and lon == 0.0:
                    st.error("Please provide a valid address or coordinates.")
                else:
                    farm = new_farm(farm_name, client_name, lat, lon, farm_address)
                    data["farms"][farm["id"]] = farm
                    save_data(data)
                    st.success(f"Farm '{farm_name}' added.")
                    st.rerun()

    # ── ADD FIELD ──────────────────────────────────────────────────────────────
    with tab_add_field:
        st.subheader("Add a field to an existing farm")
        if not farms:
            st.warning("Add a farm first.")
        else:
            farm_options = {f["name"]: fid for fid, f in farms.items()}
            selected_farm_name = st.selectbox("Select Farm", list(farm_options.keys()), key="add_field_farm")
            selected_farm_id   = farm_options[selected_farm_name]

            with st.form("form_add_field"):
                c1, c2 = st.columns(2)
                field_name = c1.text_input("Field Name", placeholder="Top Field")
                hectares   = c2.number_input("Area (ha)", min_value=0.1, value=10.0, step=0.5)

                c3, c4 = st.columns(2)
                crop    = c3.selectbox("Crop Type", CROP_TYPES)
                variety = c4.text_input("Variety", placeholder="KWS Zyatt")

                c5, c6 = st.columns(2)
                bbch_options = [f"{k} — {v}" for k, v in BBCH_STAGES.items()]
                bbch_sel = c5.selectbox("BBCH Growth Stage", bbch_options, index=0)
                bbch_val = int(bbch_sel.split(" — ")[0])

                sow_date = c6.date_input("Sow / Drilling Date", value=None)

                c7, c8 = st.columns(2)
                disease_risk = c7.selectbox("Disease Risk", ["Low", "Medium", "High"])
                maturity     = c8.selectbox("Variety Maturity", ["Early", "Mid", "Late"])

                st.markdown("**Field Location**")
                loc_address = st.text_input("Field address / nearest town (geocoded)",
                                             placeholder="Leave blank to use farm coordinates")
                col_a, col_b = st.columns(2)
                field_lat = col_a.number_input("Field Lat", value=farms[selected_farm_id]["lat"], format="%.6f")
                field_lon = col_b.number_input("Field Lon", value=farms[selected_farm_id]["lon"], format="%.6f")

                submitted = st.form_submit_button("Add Field", type="primary")

            if submitted:
                if not field_name:
                    st.error("Field name is required.")
                else:
                    lat, lon = field_lat, field_lon
                    if loc_address:
                        glat, glon = _geocode(loc_address)
                        if glat:
                            lat, lon = glat, glon

                    field = new_field(
                        name=field_name, hectares=float(hectares),
                        crop=crop, variety=variety, bbch=bbch_val,
                        lat=lat, lon=lon,
                        disease_risk=disease_risk, maturity=maturity,
                        sow_date=str(sow_date) if sow_date else "",
                    )
                    data["farms"][selected_farm_id]["fields"][field["id"]] = field
                    save_data(data)
                    st.success(f"Field '{field_name}' added to {selected_farm_name}.")
                    st.rerun()

    # ── EDIT / DELETE ──────────────────────────────────────────────────────────
    with tab_edit:
        st.subheader("Edit or delete farms and fields")
        if not farms:
            st.info("No farms to manage yet.")
            return

        farm_options = {f["name"]: fid for fid, f in farms.items()}
        sel_farm_name = st.selectbox("Farm", list(farm_options.keys()), key="edit_farm")
        sel_farm_id   = farm_options[sel_farm_name]
        farm          = data["farms"][sel_farm_id]

        # Edit farm
        with st.expander(f"Edit farm: {sel_farm_name}"):
            with st.form("form_edit_farm"):
                e_name   = st.text_input("Farm Name",    value=farm["name"])
                e_client = st.text_input("Client Name",  value=farm.get("client_name", ""))
                e_addr   = st.text_input("Address",      value=farm.get("address", ""))
                if st.form_submit_button("Save Changes"):
                    data["farms"][sel_farm_id].update(
                        {"name": e_name, "client_name": e_client, "address": e_addr}
                    )
                    save_data(data)
                    st.success("Farm updated.")
                    st.rerun()

        if st.button(f"Delete farm '{sel_farm_name}' (and all its fields)", type="secondary"):
            del data["farms"][sel_farm_id]
            save_data(data)
            st.warning(f"Farm '{sel_farm_name}' deleted.")
            st.rerun()

        st.markdown("---")
        st.markdown("**Fields in this farm**")
        fields = farm.get("fields", {})
        if not fields:
            st.info("No fields in this farm yet.")
            return

        field_options = {f["name"]: fid for fid, f in fields.items()}
        sel_field_name = st.selectbox("Select field to edit", list(field_options.keys()), key="edit_field")
        sel_field_id   = field_options[sel_field_name]
        field          = fields[sel_field_id]

        with st.form("form_edit_field"):
            c1, c2 = st.columns(2)
            ef_name    = c1.text_input("Field Name",  value=field["name"])
            ef_ha      = c2.number_input("Ha",        value=float(field["hectares"]), min_value=0.1, step=0.5)
            c3, c4 = st.columns(2)
            ef_crop    = c3.selectbox("Crop",         CROP_TYPES, index=CROP_TYPES.index(field.get("crop_type", CROP_TYPES[0])) if field.get("crop_type") in CROP_TYPES else 0)
            ef_variety = c4.text_input("Variety",     value=field.get("variety", ""))
            c5, c6 = st.columns(2)
            bbch_keys  = list(BBCH_STAGES.keys())
            cur_bbch   = field.get("bbch_stage", 0)
            bbch_idx   = bbch_keys.index(cur_bbch) if cur_bbch in bbch_keys else 0
            bbch_options = [f"{k} — {v}" for k, v in BBCH_STAGES.items()]
            ef_bbch_sel  = c5.selectbox("BBCH Stage", bbch_options, index=bbch_idx)
            ef_bbch      = int(ef_bbch_sel.split(" — ")[0])
            ef_dis     = c6.selectbox("Disease Risk", ["Low","Medium","High"],
                                       index=["Low","Medium","High"].index(field.get("disease_risk","Low")))
            c7, c8 = st.columns(2)
            ef_mat     = c7.selectbox("Maturity", ["Early","Mid","Late"],
                                       index=["Early","Mid","Late"].index(field.get("variety_maturity","Mid")))
            ef_lat     = c8.number_input("Lat", value=float(field["lat"]), format="%.6f")
            ef_lon     = st.number_input("Lon",  value=float(field["lon"]), format="%.6f")

            if st.form_submit_button("Save Field Changes"):
                data["farms"][sel_farm_id]["fields"][sel_field_id].update({
                    "name": ef_name, "hectares": ef_ha, "crop_type": ef_crop,
                    "variety": ef_variety, "bbch_stage": ef_bbch,
                    "disease_risk": ef_dis, "variety_maturity": ef_mat,
                    "lat": ef_lat, "lon": ef_lon,
                })
                save_data(data)
                st.success("Field updated.")
                st.rerun()

        if st.button(f"Delete field '{sel_field_name}'", type="secondary"):
            del data["farms"][sel_farm_id]["fields"][sel_field_id]
            save_data(data)
            st.warning(f"Field '{sel_field_name}' deleted.")
            st.rerun()
