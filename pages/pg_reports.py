"""Completion Reports — build and download PDF reports for growers."""
import streamlit as st
from datetime import date
from utils.data_models import (save_data, OPERATION_TYPES, CROP_TYPES,
                                BBCH_STAGES, new_operation_log, DEFAULT_COSTS)
from utils.report_generator import generate_completion_report
from utils.weather import check_operation_window, wind_direction_label


def render(data: dict):
    st.title("Completion Reports")
    st.markdown("Generate a professional PDF report for a grower after completing a field operation.")

    farms      = data.get("farms", {})
    contractor = data.get("contractor", {})
    equipment  = data.get("equipment", [])
    operators  = contractor.get("operators", [])

    if not farms:
        st.info("Add farms and fields first.")
        return

    # ── Farm / Field selector ─────────────────────────────────────────────────
    st.subheader("1. Select Farm & Field")
    c1, c2 = st.columns(2)
    farm_options = {f["name"]: fid for fid, f in farms.items()}
    sel_farm_name = c1.selectbox("Farm", list(farm_options.keys()))
    sel_farm_id   = farm_options[sel_farm_name]
    farm          = farms[sel_farm_id]
    fields        = farm.get("fields", {})

    if not fields:
        st.warning("No fields in this farm.")
        return

    field_options = {f["name"]: fid for fid, f in fields.items()}
    sel_field_name = c2.selectbox("Field", list(field_options.keys()))
    sel_field_id   = field_options[sel_field_name]
    field          = fields[sel_field_id]

    # ── Operation Details ─────────────────────────────────────────────────────
    st.subheader("2. Operation Details")
    c3, c4, c5 = st.columns(3)
    op_type   = c3.selectbox("Operation Type", OPERATION_TYPES)
    op_date   = c4.date_input("Date of Operation", value=date.today())
    op_start  = c5.time_input("Start Time", value=None)

    c6, c7, c8 = st.columns(3)
    op_finish = c6.time_input("Finish Time", value=None)
    operator  = c7.selectbox("Operator", operators + ["Other"]) if operators else c7.text_input("Operator")
    if operator == "Other":
        operator = st.text_input("Operator Name")

    equip_options = equipment + ["Other / Type manually"]
    equip_sel = c8.selectbox("Equipment", equip_options) if equipment else c8.text_input("Equipment")
    if equip_sel == "Other / Type manually":
        equip_sel = st.text_input("Equipment (manual entry)")

    gps = st.text_input("GPS / Auto-steer System", placeholder="John Deere StarFire, Trimble, etc.")

    # ── Products ──────────────────────────────────────────────────────────────
    st.subheader("3. Products Applied")
    st.markdown("Add one row per product.")

    field_ha = float(field.get("hectares", 0))

    if "report_products" not in st.session_state:
        st.session_state.report_products = [{"name": "", "mapp_no": "", "rate": "", "unit": "L/ha", "total_used": ""}]

    st.caption(f"Total Used is calculated automatically from Rate × {field_ha} ha. Edit the value if actual usage differed.")

    products = st.session_state.report_products
    updated_products = []
    for i, prod in enumerate(products):
        pc1, pc2, pc3, pc4, pc5, pc6 = st.columns([3, 2, 1.5, 1.5, 1.5, 0.8])
        name = pc1.text_input("Product",  value=prod["name"],      key=f"p_name_{i}")
        mapp = pc2.text_input("MAPP No.", value=prod["mapp_no"],   key=f"p_mapp_{i}")
        rate = pc3.text_input("Rate",     value=str(prod["rate"]), key=f"p_rate_{i}")
        unit = pc4.selectbox("Unit", ["L/ha","kg/ha","g/ha","t/ha","units/ha"],
                              index=["L/ha","kg/ha","g/ha","t/ha","units/ha"].index(prod.get("unit","L/ha")),
                              key=f"p_unit_{i}")

        # Auto-calculate total unless the user has already overridden it
        try:
            auto_total = round(float(rate) * field_ha, 2)
            auto_str   = str(auto_total)
        except (ValueError, TypeError):
            auto_str   = ""

        # Detect whether the stored value is a user override (differs from last auto)
        stored = str(prod.get("total_used", ""))
        is_user_override = stored and stored != prod.get("_auto_total", "")

        # Force the widget state to the auto value when not overridden.
        # (Streamlit ignores value= on re-renders, so we must write to session state directly.)
        if not is_user_override:
            st.session_state[f"p_total_{i}"] = auto_str

        total_used = pc5.text_input(
            f"Total Used ({unit.split('/')[0]})",
            key=f"p_total_{i}",
        )

        if pc6.button("🗑", key=f"del_prod_{i}", help="Remove") and len(products) > 1:
            st.session_state.report_products.pop(i)
            st.rerun()

        updated_products.append({
            "name": name, "mapp_no": mapp, "rate": rate, "unit": unit,
            "total_used": total_used, "_auto_total": auto_str,
        })

    st.session_state.report_products = updated_products

    if st.button("+ Add Product Row"):
        st.session_state.report_products.append({"name": "", "mapp_no": "", "rate": "", "unit": "L/ha", "total_used": ""})
        st.rerun()

    # ── Application Settings ──────────────────────────────────────────────────
    st.subheader("4. Application Settings")
    ac1, ac2, ac3, ac4 = st.columns(4)
    nozzle      = ac1.text_input("Nozzle Type", placeholder="TeeJet TT110-03")
    pressure    = ac2.number_input("Pressure (bar)", min_value=0.0, value=2.0, step=0.1)
    fwd_speed   = ac3.number_input("Forward Speed (km/h)", min_value=0.0, value=12.0, step=0.5)
    water_vol   = ac4.number_input("Water Volume (L/ha)", min_value=0.0, value=100.0, step=5.0)

    # ── Weather During Operation ──────────────────────────────────────────────
    st.subheader("5. Weather During Operation")
    use_auto_wx = st.checkbox("Fetch weather from forecast (uses field coordinates)", value=True)

    wx_data = {}
    wx_warnings = []

    if use_auto_wx:
        with st.spinner("Fetching weather..."):
            wx_result = check_operation_window(
                field["lat"], field["lon"], op_type,
                target_date=str(op_date),
                start_hour=op_start.hour if op_start else 7,
                duration_hours=8,
            )
        wx_warnings = wx_result["warnings"]
        s = wx_result.get("summary", {})
        if s:
            wx_data = {
                "wind_ms":      s.get("max_wind_ms", ""),
                "wind_mph":     s.get("max_wind_mph", ""),
                "wind_dir":     "",
                "temp_c":       f"{s.get('min_temp','')}–{s.get('max_temp','')}",
                "humidity_pct": "",
                "rainfall_mm":  s.get("total_rain_mm", ""),
            }
            if wx_result.get("hourly"):
                h0 = wx_result["hourly"][0]
                wx_data["wind_dir"] = wind_direction_label(h0["wind_dir"]) if h0.get("wind_dir") else ""
                wx_data["humidity_pct"] = h0.get("humidity", "")

        for w in wx_warnings:
            if wx_result["ok"]:
                st.success(w)
            else:
                st.warning(w)

    wc1, wc2, wc3, wc4, wc5 = st.columns(5)
    wind_ms   = wc1.text_input("Wind (m/s)",   value=str(wx_data.get("wind_ms", "")))
    wind_mph  = wc2.text_input("Wind (mph)",   value=str(wx_data.get("wind_mph", "")))
    wind_dir  = wc3.text_input("Wind Dir",     value=str(wx_data.get("wind_dir", "")))
    temp_c    = wc4.text_input("Temp (°C)",    value=str(wx_data.get("temp_c", "")))
    humidity  = wc5.text_input("Humidity (%)", value=str(wx_data.get("humidity_pct", "")))
    rainfall  = st.text_input("Rainfall (mm)", value=str(wx_data.get("rainfall_mm", "")))

    # ── Buffer Zones ──────────────────────────────────────────────────────────
    st.subheader("6. Buffer Zone Compliance")
    st.markdown("Record buffer zone compliance for watercourses, hedgerows, occupied buildings etc.")

    if "buffer_zones" not in st.session_state:
        st.session_state.buffer_zones = []

    buffers = st.session_state.buffer_zones
    updated_buffers = []
    for i, bz in enumerate(buffers):
        bc1, bc2, bc3, bc4, bc5 = st.columns([3, 1.5, 1.5, 1.5, 0.8])
        feature    = bc1.text_input("Feature",          value=bz.get("feature", ""), key=f"bz_feat_{i}")
        dist_m     = bc2.number_input("Dist. (m)",      value=float(bz.get("distance_m", 0)), min_value=0.0, key=f"bz_dist_{i}")
        req_m      = bc3.number_input("Required (m)",   value=float(bz.get("required_m", 0)), min_value=0.0, key=f"bz_req_{i}")
        compliant  = bc4.checkbox("Compliant",          value=bz.get("compliant", True), key=f"bz_comp_{i}")
        if bc5.button("🗑", key=f"del_bz_{i}"):
            st.session_state.buffer_zones.pop(i)
            st.rerun()
        updated_buffers.append({"feature": feature, "distance_m": dist_m, "required_m": req_m, "compliant": compliant})

    st.session_state.buffer_zones = updated_buffers

    if st.button("+ Add Buffer Zone"):
        st.session_state.buffer_zones.append({"feature": "Watercourse", "distance_m": 10, "required_m": 5, "compliant": True})
        st.rerun()

    # ── Justification for Operation ────────────────────────────────────────────
    st.subheader("7. Justification for Operation")
    st.markdown("Explain why this operation was carried out and link supporting evidence.")

    just_type = st.selectbox("Basis for Application", [
        "— Select —",
        "Disease model / forecast (link below)",
        "VRA map from remote sensing (link below)",
        "Agronomist / advisor recommendation",
        "Routine programme",
        "Crop monitoring / scouting observation",
        "Regulatory requirement",
        "Other",
    ])

    just_detail = st.text_area("Detail / Explanation",
                                placeholder="e.g. Septoria risk index 78% on AHDB disease monitor — T2 timing",
                                height=80)
    just_link = st.text_input("Reference URL / Report Link",
                               placeholder="https://... or local file path")

    # Agronomist — pick from register or type manually
    agronomists = data.get("agronomists", [])
    jc1, jc2, jc3 = st.columns(3)

    if agronomists:
        ag_options = ["— Select or type manually —"] + [
            f"{a['name']} ({a.get('company','')})" for a in agronomists
        ]
        ag_sel = jc1.selectbox("Advisor / Agronomist", ag_options)
        if ag_sel != "— Select or type manually —":
            ag_idx = ag_options.index(ag_sel) - 1
            sel_ag = agronomists[ag_idx]
            adv_name  = jc1.text_input("Name (editable)", value=sel_ag["name"])
            adv_email = jc2.text_input("Email",            value=sel_ag.get("email",""))
        else:
            adv_name  = jc1.text_input("Name")
            adv_email = jc2.text_input("Email")
    else:
        adv_name  = jc1.text_input("Advisor / Agronomist Name",
                                    help="Add agronomists in Contractor Setup to pick from a list")
        adv_email = jc2.text_input("Advisor Email")

    adv_date = jc3.date_input("Date of Advice", value=None)

    justification = {
        "type":         just_type if just_type != "— Select —" else "",
        "detail":       just_detail,
        "link":         just_link,
        "advisor_name": adv_name,
        "advisor_email": adv_email,
        "advice_date":  str(adv_date) if adv_date else "",
    }

    # ── Notes ─────────────────────────────────────────────────────────────────
    st.subheader("8. Additional Notes")
    notes = st.text_area("Notes", height=80,
                          placeholder="Any additional information relevant to the operation.")

    # ── Generate Report ────────────────────────────────────────────────────────
    st.markdown("---")
    col_gen, col_save = st.columns(2)

    with col_gen:
        if st.button("Generate PDF Report", type="primary"):
            report_data = {
                "contractor_name":    contractor.get("name", ""),
                "contractor_address": contractor.get("address", ""),
                "cert_number":        contractor.get("cert_number", ""),
                "grower_name":        farm.get("client_name", ""),
                "grower_address":     farm.get("address", ""),
                "farm_name":          farm["name"],
                "field_name":         field["name"],
                "field_ha":           field.get("hectares", ""),
                "crop_type":          field.get("crop_type", ""),
                "variety":            field.get("variety", ""),
                "bbch_stage":         f"{field.get('bbch_stage','')} — {BBCH_STAGES.get(field.get('bbch_stage',0),'')}" ,
                "operation_type":     op_type,
                "operation_date":     op_date.strftime("%d/%m/%Y"),
                "start_time":         op_start.strftime("%H:%M") if op_start else "",
                "finish_time":        op_finish.strftime("%H:%M") if op_finish else "",
                "operator_name":      operator,
                "equipment":          equip_sel,
                "gps_system":         gps,
                "products":           [{k: v for k, v in p.items() if k != "_auto_total"}
                                       for p in st.session_state.report_products if p["name"]],
                "application": {
                    "nozzle":            nozzle,
                    "pressure_bar":      pressure,
                    "forward_speed_kph": fwd_speed,
                    "water_vol_lha":     water_vol,
                },
                "weather": {
                    "wind_ms":     wind_ms,
                    "wind_mph":    wind_mph,
                    "wind_dir":    wind_dir,
                    "temp_c":      temp_c,
                    "humidity_pct": humidity,
                    "rainfall_mm": rainfall,
                },
                "weather_warnings": wx_warnings,
                "buffer_zones":     st.session_state.buffer_zones,
                "justification":    justification,
                "notes":            notes,
            }
            with st.spinner("Generating PDF..."):
                pdf_bytes = generate_completion_report(report_data)
            filename = f"AgriRoute_{farm['name']}_{field['name']}_{op_type}_{op_date}.pdf".replace(" ", "_")
            st.download_button(
                "Download PDF Report",
                data=pdf_bytes,
                file_name=filename,
                mime="application/pdf",
                type="primary",
            )

    with col_save:
        if st.button("Save to Operations Log"):
            log_entry = new_operation_log(
                farm_id=sel_farm_id, field_id=sel_field_id,
                farm_name=farm["name"], field_name=field["name"],
                operation=op_type,
                date=str(op_date),
                operator=operator,
                hectares=field.get("hectares", 0),
                revenue=field.get("hectares", 0) * data.get("costs", DEFAULT_COSTS).get(op_type, 0),
                products=[{k: v for k, v in p.items() if k != "_auto_total"}
                          for p in st.session_state.report_products if p["name"]],
                application={"nozzle": nozzle, "pressure_bar": pressure,
                             "forward_speed_kph": fwd_speed, "water_vol_lha": water_vol},
                weather={"wind_ms": wind_ms, "wind_mph": wind_mph, "wind_dir": wind_dir,
                         "temp_c": temp_c, "humidity_pct": humidity, "rainfall_mm": rainfall},
                weather_warnings=wx_warnings,
                buffer_zones=st.session_state.buffer_zones,
                equipment=equip_sel,
                gps_system=gps,
                notes=notes,
                justification=justification,
            )
            data.setdefault("operations_log", []).append(log_entry)
            if sel_farm_id in data["farms"] and sel_field_id in data["farms"][sel_farm_id]["fields"]:
                data["farms"][sel_farm_id]["fields"][sel_field_id]["days_since_last_op"][op_type] = 0
                data["farms"][sel_farm_id]["fields"][sel_field_id]["completed_operations"].append(log_entry["id"])
            save_data(data)
            st.success("Saved to operations log.")

    # ── Previous reports ───────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("Previous Operations for this Field")
    prev = [op for op in data.get("operations_log", [])
            if op.get("field_id") == sel_field_id]
    if prev:
        import pandas as pd
        prev_df = pd.DataFrame([{
            "Date":      op["date"],
            "Operation": op["operation"],
            "Operator":  op.get("operator", ""),
            "Ha":        op.get("hectares", ""),
            "Revenue":   f"£{op.get('revenue',0):,.2f}",
        } for op in sorted(prev, key=lambda x: x.get("date",""), reverse=True)])
        st.dataframe(prev_df, use_container_width=True, hide_index=True)
    else:
        st.info("No previous operations recorded for this field.")
