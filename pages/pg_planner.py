"""Day Planner — optimised route + ROI + fuel stop suggestions."""
import streamlit as st
import pandas as pd
from datetime import date, timedelta
from utils.data_models import (save_data, calc_priority_score,
                                OPERATION_TYPES, DEFAULT_WORK_RATES, DEFAULT_COSTS,
                                DEFAULT_FUEL, DEFAULT_SETUP_TIMES)
from utils.routing import build_day_plan, get_osrm_route, haversine_km
from utils.weather import check_operation_window, THRESHOLDS
from utils.fuel_prices import fetch_stations_near, score_refuel_stop


@st.cache_data(ttl=1800, show_spinner=False)
def _cached_fuel_prices(lat: float, lon: float, radius_km: float, fuel_type: str) -> dict:
    """Cached wrapper — prices refreshed at most every 30 minutes."""
    return fetch_stations_near(lat, lon, radius_km=radius_km, fuel_type=fuel_type)


def _all_fields_flat(farms: dict) -> list:
    out = []
    for farm_id, farm in farms.items():
        for fid, field in farm.get("fields", {}).items():
            f = field.copy()
            f["farm_id"]   = farm_id
            f["farm_name"] = farm["name"]
            out.append(f)
    return out


def render(data: dict):
    st.title("Day Planner")

    contractor = data.get("contractor", {})
    farms      = data.get("farms", {})

    if not contractor.get("home_coords"):
        st.warning("Set your home base in **Contractor Setup** first.")
        return
    if not farms:
        st.warning("Add farms and fields in **Farms & Fields** first.")
        return

    home_lat = contractor["home_coords"]["lat"]
    home_lon = contractor["home_coords"]["lon"]

    # ── Plan controls — on main page ──────────────────────────────────────────
    st.subheader("1. Plan Settings")
    with st.container(border=True):
        row1 = st.columns([2, 2, 1.5, 1.5])
        op_type   = row1[0].selectbox(
            "Operation Type",
            OPERATION_TYPES,
            help="Select the type of operation you are planning for today",
        )
        plan_date = row1[1].date_input("Date", value=date.today() + timedelta(days=1))
        start_hr  = row1[2].number_input(
            "Start time (hr)",
            value=float(data.get("default_start_hr", 7)),
            min_value=4.0, max_value=12.0, step=0.5,
        )
        max_hrs   = row1[3].number_input(
            "Max hours in day",
            value=float(data.get("max_day_hours", 10)),
            min_value=2.0, max_value=16.0, step=0.5,
        )

        row2 = st.columns([2, 2, 1.5, 1.5, 1.5])
        work_rate = row2[0].number_input(
            "Work rate (ha/hr)",
            value=float(data.get("work_rates", DEFAULT_WORK_RATES).get(op_type, 10)),
            min_value=0.5, step=0.5,
            help="Your effective field work rate for this operation",
        )
        cost_per_ha = row2[1].number_input(
            "Charge (£/ha)",
            value=float(data.get("costs", DEFAULT_COSTS).get(op_type, 10)),
            min_value=0.0, step=1.0,
        )
        setup_time = row2[2].number_input(
            "Setup time (min/field)",
            value=float(data.get("setup_times", DEFAULT_SETUP_TIMES).get(op_type, 20)),
            min_value=0.0, max_value=120.0, step=5.0,
            help="Fixed time per field: filling tank/hopper, pre-work checks, getting into field",
        )
        avg_speed = row2[3].number_input(
            "Road speed (km/h)",
            value=float(data.get("avg_speed_kmh", 50)),
            min_value=10.0, max_value=120.0, step=5.0,
        )
        min_score = row2[4].slider("Min priority score", 0, 100, 0)

    all_fields = _all_fields_flat(farms)

    # Score fields
    for f in all_fields:
        f["_priority_score"] = calc_priority_score(f, op_type)

    eligible = [f for f in all_fields if f["_priority_score"] >= min_score]

    if not eligible:
        st.info(f"No fields meet the minimum priority score of {min_score} for {op_type}.")
        return

    # ── Field selection ───────────────────────────────────────────────────────
    st.subheader("Select Fields for Today")

    score_df = pd.DataFrame([{
        "": True,
        "Farm":     f["farm_name"],
        "Field":    f["name"],
        "Crop":     f.get("crop_type", ""),
        "Ha":       f.get("hectares", 0),
        "BBCH":     f.get("bbch_stage", 0),
        "Disease":  f.get("disease_risk", "Low"),
        "Score":    round(f["_priority_score"], 1),
    } for f in sorted(eligible, key=lambda x: -x["_priority_score"])])

    edited = st.data_editor(score_df, use_container_width=True, hide_index=True,
                             column_config={"": st.column_config.CheckboxColumn("Include", default=True)})

    selected_names = set(edited[edited[""] == True]["Field"].tolist())
    selected_fields = [f for f in eligible if f["name"] in selected_names]

    if not selected_fields:
        st.info("Select at least one field.")
        return

    # ── Weather check ─────────────────────────────────────────────────────────
    st.subheader("Weather Check")
    date_str = str(plan_date)
    # Use first field's coords as representative
    rep = selected_fields[0]
    wx = check_operation_window(rep["lat"], rep["lon"], op_type,
                                 start_hour=int(start_hr),
                                 duration_hours=int(max_hrs),
                                 target_date=date_str)
    if wx["ok"]:
        st.success(" | ".join(wx["warnings"]))
    else:
        for w in wx["warnings"]:
            st.warning(w)

    if wx.get("summary"):
        s = wx["summary"]
        wc1, wc2, wc3, wc4 = st.columns(4)
        wc1.metric("Max Wind", f"{s['max_wind_ms']} m/s ({s['max_wind_mph']} mph)")
        wc2.metric("Rainfall", f"{s['total_rain_mm']} mm")
        wc3.metric("Min Temp", f"{s['min_temp']} °C")
        wc4.metric("Max Temp", f"{s['max_temp']} °C")

    if not wx["ok"]:
        proceed = st.checkbox("Weather warning — proceed anyway?", value=False)
        if not proceed:
            st.stop()

    # ── Build plan ────────────────────────────────────────────────────────────
    if st.button("Build Day Plan", type="primary"):
        with st.spinner("Optimising route..."):
            result = build_day_plan(
                home_lat=home_lat, home_lon=home_lon,
                fields=selected_fields,
                operation=op_type,
                work_rate_ha_hr=work_rate,
                cost_per_ha=cost_per_ha,
                start_time_hr=start_hr,
                max_hours=max_hrs,
                avg_speed_kmh=avg_speed,
                setup_time_min=setup_time,
            )
        st.session_state["day_plan"] = result
        st.session_state["day_plan_op"] = op_type
        st.session_state["plan_date"] = date_str

    if "day_plan" not in st.session_state:
        return

    result   = st.session_state["day_plan"]
    plan     = result["plan"]
    op_label = st.session_state.get("day_plan_op", op_type)

    st.markdown("---")
    st.subheader(f"Day Plan — {op_label} — {st.session_state.get('plan_date', date_str)}")

    # ── Fuel calculations ─────────────────────────────────────────────────────
    fuel_cfg      = data.get("fuel", {})
    fuel_price    = float(fuel_cfg.get("price_per_litre",       DEFAULT_FUEL["price_per_litre"]))
    road_l100     = float(fuel_cfg.get("road_litres_per_100km", DEFAULT_FUEL["road_litres_per_100km"]))
    op_lpha       = float(fuel_cfg.get("op_litres_per_ha", {}).get(
                        op_label, DEFAULT_FUEL["op_litres_per_ha"].get(op_label, 10.0)))

    total_road_km   = sum(s["distance_km"] for s in plan) + result.get("return_dist_km", 0)
    total_road_l    = total_road_km * road_l100 / 100
    total_road_cost = total_road_l * fuel_price

    total_op_l      = result["total_ha"] * op_lpha
    total_op_cost   = total_op_l * fuel_price

    total_fuel_cost = total_road_cost + total_op_cost
    net_margin      = result["total_revenue"] - total_fuel_cost

    # Summary metrics
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Fields",          result["fields_count"])
    m2.metric("Total Ha",        f"{result['total_ha']} ha")
    m3.metric("Revenue",         f"£{result['total_revenue']:,.2f}")
    m4.metric("Fuel Cost",       f"£{total_fuel_cost:,.2f}",
              delta=f"-£{total_fuel_cost:,.2f}", delta_color="inverse")
    m5.metric("Net (after fuel)", f"£{net_margin:,.2f}")
    m6.metric("Finish / Return", f"{result['finish_time']} / {result['return_time']}")

    # ── Over / under day indicator ────────────────────────────────────────────
    total_travel_min = sum(s["travel_min"] for s in plan)
    total_setup_min  = sum(s.get("setup_min", 0) for s in plan)
    total_work_min   = sum(s.get("work_min", 0) for s in plan)
    total_planned_hr = (total_travel_min + total_setup_min + total_work_min) / 60
    return_travel_hr = result.get("return_dist_km", 0) / max(avg_speed, 1)
    total_day_hr     = total_planned_hr + return_travel_hr
    budget_hr        = max_hrs
    over_under_hr    = total_day_hr - budget_hr

    ind1, ind2, ind3, ind4 = st.columns(4)
    ind1.metric("Working time",   f"{total_work_min:.0f} min ({total_work_min/60:.1f} hr)")
    ind2.metric("Setup time",     f"{total_setup_min:.0f} min")
    ind3.metric("Travel time",    f"{total_travel_min + return_travel_hr*60:.0f} min")
    if over_under_hr > 0.25:
        ind4.metric("Day vs budget", f"+{over_under_hr:.1f} hr OVER",
                    delta=f"{total_day_hr:.1f} hr of {budget_hr:.1f} hr", delta_color="inverse")
        st.warning(
            f"Plan is **{over_under_hr:.1f} hr over** your {budget_hr:.0f}-hour day budget "
            f"({total_day_hr:.1f} hr total incl. return). Consider removing lower-priority fields."
        )
    elif over_under_hr < -0.5:
        ind4.metric("Day vs budget", f"{abs(over_under_hr):.1f} hr spare",
                    delta=f"{total_day_hr:.1f} hr of {budget_hr:.1f} hr", delta_color="normal")
        st.info(f"Plan uses {total_day_hr:.1f} hr — **{abs(over_under_hr):.1f} hr spare** in your {budget_hr:.0f}-hour day.")
    else:
        ind4.metric("Day vs budget", "On track",
                    delta=f"{total_day_hr:.1f} hr of {budget_hr:.1f} hr", delta_color="normal")
        st.success(f"Plan fits well within your {budget_hr:.0f}-hour day ({total_day_hr:.1f} hr total).")

    # Fuel breakdown
    with st.expander("Fuel Breakdown", expanded=False):
        fb1, fb2, fb3, fb4 = st.columns(4)
        fb1.metric("Road distance",      f"{total_road_km:.1f} km")
        fb2.metric("Road fuel",          f"{total_road_l:.1f} L  (£{total_road_cost:.2f})")
        fb3.metric("In-field fuel",      f"{total_op_l:.1f} L  (£{total_op_cost:.2f})")
        fb4.metric("Fuel price used",    f"£{fuel_price:.2f}/L")
        st.caption(
            f"Road: {road_l100} L/100km | In-field ({op_label}): {op_lpha} L/ha — "
            f"update rates in **Contractor Setup → Fuel & Running Costs**"
        )

    # Detailed schedule table
    plan_rows = []
    for i, stop in enumerate(plan, 1):
        stop_road_l    = stop["distance_km"] * road_l100 / 100
        stop_op_l      = stop["hectares"] * op_lpha
        stop_fuel_cost = (stop_road_l + stop_op_l) * fuel_price
        s_min  = stop.get("setup_min", 0)
        w_min  = stop.get("work_min", round(stop["hectares"] / work_rate * 60, 0))
        plan_rows.append({
            "#":            i,
            "Farm":         stop["farm_name"],
            "Field":        stop["field_name"],
            "Crop":         stop["crop_type"],
            "Ha":           stop["hectares"],
            "Priority":     stop["priority_score"],
            "Travel":       f"{stop['travel_min']} min ({stop['distance_km']} km)",
            "Setup":        f"{s_min:.0f} min",
            "Work":         f"{w_min:.0f} min",
            "Arrive":       stop["arrive_time"],
            "Work Start":   stop.get("work_start_time", stop["arrive_time"]),
            "Finish":       stop["finish_time"],
            "Revenue":      f"£{stop['revenue']:,.2f}",
            "Travel Fuel":  f"{stop_road_l:.1f} L",
            "Field Fuel":   f"{stop_op_l:.1f} L",
            "Fuel Cost":    f"£{stop_fuel_cost:.2f}",
            "Net":          f"£{stop['revenue'] - stop_fuel_cost:,.2f}",
            "Full":         "Yes" if stop["full_field"] else "Partial",
        })

    df_plan = pd.DataFrame(plan_rows)
    st.dataframe(df_plan, use_container_width=True, hide_index=True)

    # ── Refuel on Route ───────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("Refuel on Route?")

    needs_refuel = st.checkbox("I need to fill up today", value=False,
                               help="Find the best fuel station on your route based on price vs detour cost")

    if needs_refuel:
        rf1, rf2, rf3 = st.columns(3)
        litres_needed = rf1.number_input(
            "Litres needed",
            value=200.0, min_value=10.0, max_value=1000.0, step=10.0,
            help="How many litres do you need to fill up?",
        )
        fuel_type = rf2.selectbox(
            "Fuel type",
            ["diesel", "petrol"],
            index=0,
            help="Diesel (B7) for most agricultural vehicles",
        )
        search_radius = rf3.number_input(
            "Search radius (km)",
            value=25.0, min_value=5.0, max_value=60.0, step=5.0,
            help="How far from your route centre to search for stations",
        )

        # Route centre for searching
        waypoints = result.get("waypoints", [(home_lat, home_lon)])
        route_centre_lat = sum(w[0] for w in waypoints) / len(waypoints)
        route_centre_lon = sum(w[1] for w in waypoints) / len(waypoints)

        fetch_col, info_col = st.columns([1, 3])
        if fetch_col.button("Fetch Live Prices", type="primary"):
            st.session_state.pop("fuel_station_data", None)  # force refresh

        # Auto-fetch on first view or after button press
        if "fuel_station_data" not in st.session_state:
            with st.spinner("Fetching live UK fuel prices from retailer feeds..."):
                price_data = _cached_fuel_prices(
                    route_centre_lat, route_centre_lon,
                    radius_km=search_radius, fuel_type=fuel_type,
                )
            st.session_state["fuel_station_data"] = price_data
        else:
            price_data = st.session_state["fuel_station_data"]

        stations      = price_data.get("stations", [])
        sources_ok    = price_data.get("sources_ok", [])
        sources_failed= price_data.get("sources_failed", [])
        updated_at    = price_data.get("last_updated", "—")

        # ── Determine which station list and price source to use ──────────────
        using_live_prices = bool(stations)

        if using_live_prices:
            info_col.caption(
                f"Live prices at {updated_at} from: {', '.join(sources_ok)}."
                + (f" Unavailable: {', '.join(sources_failed)}." if sources_failed else "")
            )
        else:
            # Fall back to Overpass stations already found during route build
            overpass_stations = result.get("fuel_stations", [])
            if sources_ok or sources_failed:
                info_col.caption(
                    "No live prices returned from retailer feeds"
                    + (f" (tried: {', '.join(sources_ok + sources_failed)})" if sources_ok or sources_failed else "")
                    + ". Using map-sourced stations — enter price manually below."
                )
            else:
                info_col.caption("Live price feeds unavailable. Using map-sourced stations — enter price manually.")

            if not overpass_stations:
                st.info(
                    "No fuel stations found near your route. "
                    "Try rebuilding the day plan (which searches for nearby stations) "
                    "or increase the search radius and try Fetch Live Prices again."
                )
            else:
                # Manual price entry — default to setup page fuel price
                setup_ppl = round(fuel_price * 100, 1)  # £/L → pence/L
                manual_ppl = st.number_input(
                    "Fuel price (pence per litre) — enter today's pump price",
                    value=setup_ppl,
                    min_value=50.0, max_value=300.0, step=0.1, format="%.1f",
                    help=f"Defaulting to your Setup page rate (£{fuel_price:.3f}/L = {setup_ppl:.1f}p/L). "
                         "Update to today's actual pump price.",
                )
                # Convert Overpass stations to the same format as live-price stations
                for s in overpass_stations:
                    s["diesel_ppl"] = manual_ppl
                    s["petrol_ppl"] = manual_ppl
                    s["distance_from_centre_km"] = s.get("distance_km", 0)
                stations = overpass_stations

        if not stations:
            pass  # message already shown above
        else:
            # ── Shared scoring + display for both live-price and fallback ─────
            scored = [
                score_refuel_stop(
                    s, waypoints,
                    litres_needed=litres_needed,
                    work_rate_ha_hr=work_rate,
                    cost_per_ha=cost_per_ha,
                    avg_speed_kmh=avg_speed,
                    fuel_type=fuel_type,
                )
                for s in stations[:20]
            ]
            scored.sort(key=lambda s: s["net_roi_impact"])

            best_station  = scored[0]
            cheapest_price = min(s["ppl"] for s in scored)
            price_label   = f"{cheapest_price:.1f}p/L" if using_live_prices else f"{cheapest_price:.1f}p/L (manual)"

            st.markdown(
                f"**{len(scored)} stations found** — price: **{price_label}** | "
                f"Best ROI stop: **{best_station['brand']} "
                f"{best_station.get('postcode', best_station.get('address', ''))}** "
                f"(£{best_station['net_roi_impact']:.2f} total cost incl. detour)"
            )

            # Comparison table
            table_rows = []
            for i, s in enumerate(scored):
                ppl      = s["ppl"]
                is_best  = (i == 0)
                is_cheap = (ppl == cheapest_price) and not is_best
                label    = "Best ROI" if is_best else ("Cheapest price" if is_cheap else "")
                table_rows.append({
                    "":               label,
                    "Brand":          s["brand"],
                    "Address":        s.get("postcode", s.get("address", "")),
                    "Price (p/L)":    f"{ppl:.1f}" + ("" if using_live_prices else " *"),
                    "Fill cost":      f"£{s['fill_cost']:.2f}",
                    "Detour":         f"{s['detour_km']:.1f} km",
                    "Time lost":      f"{s['time_lost_min']:.0f} min",
                    "Ha lost":        f"{s['ha_lost']:.1f} ha",
                    "Revenue lost":   f"£{s['revenue_lost']:.2f}",
                    "Total ROI cost": f"£{s['net_roi_impact']:.2f}",
                    "Dist (km)":      f"{s.get('distance_from_centre_km', s.get('distance_km', '?'))}",
                })

            df_stations = pd.DataFrame(table_rows)

            def _highlight_best(row):
                if row[""] == "Best ROI":
                    return ["background-color: #d4edda"] * len(row)
                if row[""] == "Cheapest price":
                    return ["background-color: #d0eaff"] * len(row)
                return [""] * len(row)

            st.dataframe(
                df_stations.style.apply(_highlight_best, axis=1),
                use_container_width=True, hide_index=True,
            )

            if not using_live_prices:
                st.caption("* Price entered manually above — update if you know this station's actual price.")

            # Station selector + live impact view
            st.markdown("**Select a station to see the impact on your day:**")
            station_options = [
                f"{s['brand']} — {s.get('postcode', s.get('address', ''))} — "
                f"{s['ppl']:.1f}p/L — £{s['net_roi_impact']:.2f} total cost"
                for s in scored
            ]
            selected_idx = st.selectbox(
                "Choose fuel station",
                range(len(station_options)),
                format_func=lambda i: station_options[i],
                index=0,
                key="selected_fuel_station_idx",
            )

            sel  = scored[selected_idx]
            best = scored[0]

            st.markdown(f"**Impact of stopping at {sel['brand']} {sel.get('postcode', sel.get('address', ''))}:**")
            ic1, ic2, ic3, ic4, ic5 = st.columns(5)
            ic1.metric("Fuel price",    f"{sel['ppl']:.1f} p/L",
                       delta="Best ROI stop" if selected_idx == 0 else f"{sel['ppl'] - best['ppl']:+.1f}p vs best ROI",
                       delta_color="off" if selected_idx == 0 else "inverse")
            ic2.metric("Fill cost",     f"£{sel['fill_cost']:.2f}",
                       delta=f"£{sel['fill_cost'] - best['fill_cost']:+.2f}" if selected_idx != 0 else None,
                       delta_color="inverse")
            ic3.metric("Detour / time", f"{sel['detour_km']:.1f} km / {sel['time_lost_min']:.0f} min",
                       delta=f"{sel['detour_km'] - best['detour_km']:+.1f} km vs best" if selected_idx != 0 else None,
                       delta_color="inverse")
            ic4.metric("Revenue lost",  f"£{sel['revenue_lost']:.2f}",
                       delta=f"£{sel['revenue_lost'] - best['revenue_lost']:+.2f}" if selected_idx != 0 else None,
                       delta_color="inverse")
            ic5.metric("Total ROI cost",f"£{sel['net_roi_impact']:.2f}",
                       delta=f"£{sel['net_roi_impact'] - best['net_roi_impact']:+.2f} vs best" if selected_idx != 0 else None,
                       delta_color="inverse")

            adjusted_net = net_margin - sel["net_roi_impact"]
            if selected_idx == 0:
                st.success(
                    f"With this stop: net margin £{net_margin:.2f} → "
                    f"**£{adjusted_net:.2f}** after fill-up "
                    f"({sel['detour_km']:.1f} km detour, {sel['time_lost_min']:.0f} min lost)"
                )
            else:
                extra = sel["net_roi_impact"] - best["net_roi_impact"]
                st.info(
                    f"With this stop: net margin → **£{adjusted_net:.2f}**. "
                    f"Costs **£{extra:.2f} more** than the Best ROI option "
                    f"({best['brand']} {best.get('postcode', '')} at {best['ppl']:.1f}p/L)."
                )

            if using_live_prices:
                st.caption(
                    "Prices from official UK retailer feeds (CMA transparency scheme). "
                    "Always verify at the pump. Total ROI cost = fill cost + revenue lost to detour time."
                )
            else:
                st.caption(
                    "Stations sourced via OpenStreetMap. Prices are manually entered — "
                    "fetch live prices above for retailer-reported rates. "
                    "Total ROI cost = fill cost + revenue lost to detour time."
                )

    # ── Route Map ─────────────────────────────────────────────────────────────
    st.subheader("Route Map")
    try:
        import folium
        from streamlit_folium import st_folium

        waypoints = result.get("waypoints", [])
        mid_lat = sum(w[0] for w in waypoints) / len(waypoints)
        mid_lon = sum(w[1] for w in waypoints) / len(waypoints)
        m = folium.Map(location=[mid_lat, mid_lon], zoom_start=11, tiles="OpenStreetMap")

        # OSRM route line
        osrm = get_osrm_route(waypoints)
        if osrm and osrm.get("geometry"):
            line_coords = [[lat, lon] for lon, lat in osrm["geometry"]]
            folium.PolyLine(line_coords, color="#2D6A4F", weight=4, opacity=0.8,
                            tooltip=f"Route: {osrm['distance_km']:.1f} km, {osrm['duration_min']:.0f} min").add_to(m)

        # Home base
        folium.Marker(
            [home_lat, home_lon],
            popup="Home Base",
            tooltip="Home Base (Start/End)",
            icon=folium.Icon(color="red", icon="home", prefix="fa"),
        ).add_to(m)

        # Field stops
        for i, stop in enumerate(plan, 1):
            col = "red" if stop["priority_score"] >= 70 else ("orange" if stop["priority_score"] >= 40 else "green")
            popup_html = (
                f"<b>#{i} {stop['field_name']}</b><br>"
                f"{stop['farm_name']}<br>"
                f"{stop['crop_type']} | {stop['hectares']} ha<br>"
                f"Arrive: {stop['arrive_time']} | Finish: {stop['finish_time']}<br>"
                f"Revenue: £{stop['revenue']:,.2f}"
            )
            folium.CircleMarker(
                [stop["lat"], stop["lon"]],
                radius=10, color=col, fill=True, fill_color=col, fill_opacity=0.8,
                popup=folium.Popup(popup_html, max_width=220),
                tooltip=f"#{i} {stop['field_name']}",
            ).add_to(m)
            folium.Marker(
                [stop["lat"], stop["lon"]],
                icon=folium.DivIcon(
                    html=f'<div style="font-size:11px;font-weight:bold;color:white;'
                         f'background:{col};border-radius:50%;width:22px;height:22px;'
                         f'display:flex;align-items:center;justify-content:center;">{i}</div>',
                    icon_size=(22, 22), icon_anchor=(11, 11),
                ),
            ).add_to(m)

        # Fuel stations
        fuel_fg = folium.FeatureGroup(name="Fuel Stations", show=True)
        for fs in result.get("fuel_stations", [])[:5]:
            folium.Marker(
                [fs["lat"], fs["lon"]],
                popup=f"<b>{fs['brand']}</b><br>{fs.get('address','')}<br>{fs['distance_km']} km from route",
                tooltip=f"Fuel: {fs['brand']}",
                icon=folium.Icon(color="gray", icon="tint", prefix="fa"),
            ).add_to(fuel_fg)
        fuel_fg.add_to(m)

        folium.LayerControl().add_to(m)
        st_folium(m, width=None, height=500, use_container_width=True)

        if osrm:
            st.caption(f"Road distance: {osrm['distance_km']:.1f} km | Est. drive: {osrm['duration_min']:.0f} min")

    except ImportError:
        st.info("Install streamlit-folium for the route map.")

    # ── Fuel Stations ─────────────────────────────────────────────────────────
    fuel_stations = result.get("fuel_stations", [])
    if fuel_stations:
        st.subheader("Fuel Stations Near Route")
        st.caption("Check current prices before visiting. Displayed nearest to route midpoint.")
        fuel_rows = [{
            "Brand":    fs["brand"],
            "Name":     fs["name"],
            "Address":  fs.get("address", ""),
            "Dist (km)": fs["distance_km"],
        } for fs in fuel_stations]
        st.dataframe(pd.DataFrame(fuel_rows), use_container_width=True, hide_index=True)
    else:
        st.info("No fuel stations found near route (Overpass API may be unavailable).")

    # ── Save to log ────────────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("Mark Operations as Complete")
    st.markdown("After completing a field, mark it done to update the operations log.")

    for stop in plan:
        col_a, col_b = st.columns([4, 1])
        col_a.markdown(f"**{stop['field_name']}** ({stop['farm_name']}) — {stop['hectares']} ha")
        if col_b.button("Mark Done", key=f"done_{stop['field_id']}"):
            from utils.data_models import new_operation_log
            log_entry = new_operation_log(
                farm_id=stop["farm_id"], field_id=stop["field_id"],
                farm_name=stop["farm_name"], field_name=stop["field_name"],
                operation=op_label,
                date=st.session_state.get("plan_date", date_str),
                operator=contractor.get("operators", [""])[0],
                hectares=stop["hectares"],
                revenue=stop["revenue"],
            )
            data.setdefault("operations_log", []).append(log_entry)
            # Update days_since_last_op
            fid   = stop["field_id"]
            fmid  = stop["farm_id"]
            if fmid in data["farms"] and fid in data["farms"][fmid]["fields"]:
                data["farms"][fmid]["fields"][fid]["days_since_last_op"][op_label] = 0
                data["farms"][fmid]["fields"][fid]["completed_operations"].append(log_entry["id"])
            save_data(data)
            st.success(f"{stop['field_name']} marked as complete.")
            st.rerun()
