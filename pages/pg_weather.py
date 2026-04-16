"""Weather — 7-day forecast per farm with operation suitability."""
import streamlit as st
import pandas as pd
from utils.data_models import OPERATION_TYPES
from utils.weather import (get_forecast, get_daily_suitability,
                            check_operation_window, wind_direction_label, THRESHOLDS)


def render(data: dict):
    st.title("Weather Forecast")

    farms = data.get("farms", {})

    if not farms:
        st.info("Add farms in **Farms & Fields** to view weather forecasts.")
        return

    # ── Location selector ─────────────────────────────────────────────────────
    farm_options = {f["name"]: fid for fid, f in farms.items()}
    c1, c2, c3 = st.columns([2, 2, 1])
    sel_farm_name = c1.selectbox("Farm location", list(farm_options.keys()))
    sel_op        = c2.selectbox("Operation type", OPERATION_TYPES)
    sel_farm_id   = farm_options[sel_farm_name]
    farm          = farms[sel_farm_id]
    lat, lon      = farm["lat"], farm["lon"]

    if c3.button("Refresh", use_container_width=True):
        st.cache_data.clear()

    st.caption(f"Location: {lat:.4f}, {lon:.4f} | Timezone: Europe/London | Source: Open-Meteo (free)")

    # ── 7-day suitability overview ────────────────────────────────────────────
    st.subheader(f"7-Day Suitability — {sel_op}")
    with st.spinner("Fetching forecast..."):
        days = get_daily_suitability(lat, lon, sel_op)

    if not days:
        st.error("Could not retrieve weather data. Check your internet connection.")
        return

    thresh = THRESHOLDS.get(sel_op, {})

    # Build colour-coded day cards
    day_cols = st.columns(len(days))
    for i, (col, day) in enumerate(zip(day_cols, days)):
        ok = day["ok"]
        bg = "#d4edda" if ok else "#ffd6d6"
        icon = "✅" if ok else "⚠️"
        col.markdown(
            f"""<div style="background:{bg};border-radius:8px;padding:8px;text-align:center;font-size:12px;">
            <b>{day['date'][5:]}</b><br>
            {icon}<br>
            💨 {day['max_wind_mph']} mph<br>
            🌧 {day['rain_mm']} mm<br>
            🌡 {day['min_temp']}–{day['max_temp']} °C<br>
            <small>{day['description']}</small>
            </div>""",
            unsafe_allow_html=True,
        )

    st.markdown("---")
    st.caption(
        f"Thresholds for {sel_op}: "
        f"Wind ≤ {thresh.get('wind_max_ms',99)} m/s ({thresh.get('wind_max_ms',99)*2.237:.0f} mph) | "
        f"Rain ≤ {thresh.get('rain_max_mm',99)} mm | "
        f"Temp {thresh.get('temp_min_c',-99)}–{thresh.get('temp_max_c',99)} °C"
    )

    # ── Day detail ────────────────────────────────────────────────────────────
    st.subheader("Hourly Detail")
    sel_date = st.date_input("Select day for hourly view",
                              value=pd.Timestamp(days[1]["date"]).date() if len(days) > 1 else pd.Timestamp(days[0]["date"]).date())

    wx = check_operation_window(lat, lon, sel_op,
                                 start_hour=int(data.get("default_start_hr", 7)),
                                 duration_hours=int(data.get("max_day_hours", 10)),
                                 target_date=str(sel_date))

    for w in wx["warnings"]:
        if wx["ok"]:
            st.success(w)
        else:
            st.warning(w)

    if wx["hourly"]:
        hourly_rows = [{
            "Time":      h["time"][11:16],
            "Temp (°C)": h["temp"],
            "Wind m/s":  h["wind"],
            "Wind mph":  round(h["wind"] * 2.237, 1),
            "Direction": wind_direction_label(h["wind_dir"]) if h["wind_dir"] is not None else "",
            "Rain (mm)": h["precip"],
            "Humidity %": h["humidity"],
            "Conditions": h["description"],
        } for h in wx["hourly"]]

        df_h = pd.DataFrame(hourly_rows)

        def style_wind(val):
            lim = thresh.get("wind_max_ms", 99)
            if val > lim: return "background-color: #ffd6d6"
            return ""

        def style_rain(val):
            lim = thresh.get("rain_max_mm", 99)
            if val > lim: return "background-color: #ffd6d6"
            return ""

        styled_h = df_h.style.map(style_wind, subset=["Wind m/s"]).map(style_rain, subset=["Rain (mm)"])
        st.dataframe(styled_h, use_container_width=True, hide_index=True)

        # Chart
        import plotly.graph_objects as go
        times = [h["time"][11:16] for h in wx["hourly"]]
        fig = go.Figure()
        fig.add_trace(go.Bar(x=times, y=[h["wind"] * 2.237 for h in wx["hourly"]],
                              name="Wind (mph)", marker_color="#2D6A4F", opacity=0.6))
        fig.add_trace(go.Bar(x=times, y=[h["precip"] for h in wx["hourly"]],
                              name="Rain (mm)", marker_color="#1565C0", opacity=0.6, yaxis="y2"))
        fig.add_hline(y=thresh.get("wind_max_ms", 99) * 2.237,
                      line_dash="dot", line_color="red",
                      annotation_text=f"Wind limit ({thresh.get('wind_max_ms',99)*2.237:.0f} mph)")
        fig.update_layout(
            barmode="group",
            yaxis=dict(title="Wind (mph)"),
            yaxis2=dict(title="Rain (mm)", overlaying="y", side="right"),
            height=300, margin=dict(t=30, b=30),
            legend=dict(orientation="h"),
        )
        st.plotly_chart(fig, use_container_width=True)

    # ── All operations suitability matrix ─────────────────────────────────────
    st.markdown("---")
    st.subheader("7-Day Operation Suitability Matrix")

    matrix_rows = []
    for day in days:
        row = {"Date": day["date"], "Conditions": day["description"]}
        for op in OPERATION_TYPES:
            day_suits = get_daily_suitability(lat, lon, op)
            for d in day_suits:
                if d["date"] == day["date"]:
                    row[op] = "✅" if d["ok"] else "⚠️"
                    break
            else:
                row[op] = "—"
        matrix_rows.append(row)

    st.dataframe(pd.DataFrame(matrix_rows), use_container_width=True, hide_index=True)
