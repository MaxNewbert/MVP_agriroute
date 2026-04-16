"""ROI Tracker — revenue and cost analysis across completed operations."""
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from collections import defaultdict
from utils.data_models import OPERATION_TYPES, DEFAULT_COSTS, DEFAULT_WORK_RATES, DEFAULT_FUEL


def render(data: dict):
    st.title("ROI Tracker")

    ops_log = data.get("operations_log", [])
    costs   = data.get("costs",      DEFAULT_COSTS.copy())
    rates   = data.get("work_rates", DEFAULT_WORK_RATES.copy())

    if not ops_log:
        st.info("No completed operations yet. Use the **Day Planner** to mark fields as done.")
        return

    df = pd.DataFrame(ops_log)
    df["date"]    = pd.to_datetime(df["date"], errors="coerce")
    df["revenue"] = pd.to_numeric(df["revenue"], errors="coerce").fillna(0)
    df["hectares"]= pd.to_numeric(df["hectares"], errors="coerce").fillna(0)

    # ── Summary Metrics ───────────────────────────────────────────────────────
    total_rev = df["revenue"].sum()
    total_ha  = df["hectares"].sum()
    total_jobs = len(df)
    avg_rev_ha = total_rev / total_ha if total_ha > 0 else 0

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Revenue",   f"£{total_rev:,.2f}")
    m2.metric("Total Hectares",  f"{total_ha:,.1f} ha")
    m3.metric("Jobs Completed",  total_jobs)
    m4.metric("Avg Revenue/ha",  f"£{avg_rev_ha:.2f}")

    st.markdown("---")

    # ── Revenue by operation type ─────────────────────────────────────────────
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Revenue by Operation")
        rev_by_op = df.groupby("operation")["revenue"].sum().reset_index()
        rev_by_op.columns = ["Operation", "Revenue (£)"]
        fig_op = px.bar(rev_by_op, x="Operation", y="Revenue (£)",
                        color="Operation", color_discrete_sequence=px.colors.sequential.Greens_r)
        fig_op.update_layout(showlegend=False, height=300, margin=dict(t=20, b=20))
        st.plotly_chart(fig_op, use_container_width=True)

    with col2:
        st.subheader("Hectares by Operation")
        ha_by_op = df.groupby("operation")["hectares"].sum().reset_index()
        ha_by_op.columns = ["Operation", "Hectares"]
        fig_ha = px.pie(ha_by_op, values="Hectares", names="Operation",
                        color_discrete_sequence=px.colors.sequential.Greens_r)
        fig_ha.update_layout(height=300, margin=dict(t=20, b=20))
        st.plotly_chart(fig_ha, use_container_width=True)

    # ── Revenue over time ─────────────────────────────────────────────────────
    if df["date"].notna().any():
        st.subheader("Revenue Over Time")
        df_sorted = df.dropna(subset=["date"]).sort_values("date")
        df_sorted["cumulative_revenue"] = df_sorted["revenue"].cumsum()
        fig_time = go.Figure()
        fig_time.add_trace(go.Bar(
            x=df_sorted["date"], y=df_sorted["revenue"],
            name="Daily Revenue", marker_color="#2D6A4F", opacity=0.7,
        ))
        fig_time.add_trace(go.Scatter(
            x=df_sorted["date"], y=df_sorted["cumulative_revenue"],
            name="Cumulative", mode="lines+markers", line=dict(color="#1B4332", width=2),
            yaxis="y2",
        ))
        fig_time.update_layout(
            yaxis=dict(title="Revenue (£)"),
            yaxis2=dict(title="Cumulative (£)", overlaying="y", side="right"),
            height=350, margin=dict(t=30, b=30),
            legend=dict(orientation="h"),
        )
        st.plotly_chart(fig_time, use_container_width=True)

    # ── Revenue by farm / client ───────────────────────────────────────────────
    col3, col4 = st.columns(2)

    with col3:
        st.subheader("Revenue by Farm")
        rev_farm = df.groupby("farm_name")["revenue"].sum().sort_values(ascending=False).reset_index()
        rev_farm.columns = ["Farm", "Revenue (£)"]
        fig_farm = px.bar(rev_farm, x="Farm", y="Revenue (£)",
                          color_discrete_sequence=["#2D6A4F"])
        fig_farm.update_layout(showlegend=False, height=300, margin=dict(t=20, b=20))
        st.plotly_chart(fig_farm, use_container_width=True)

    with col4:
        st.subheader("Ha by Farm")
        ha_farm = df.groupby("farm_name")["hectares"].sum().sort_values(ascending=False).reset_index()
        ha_farm.columns = ["Farm", "Hectares"]
        fig_haf = px.bar(ha_farm, x="Farm", y="Hectares",
                         color_discrete_sequence=["#52B788"])
        fig_haf.update_layout(showlegend=False, height=300, margin=dict(t=20, b=20))
        st.plotly_chart(fig_haf, use_container_width=True)

    # ── Profitability estimate ─────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("Profitability Estimate")
    st.markdown("Costs pulled from your setup (fuel auto-calculated). Override any value below.")

    fuel_cfg   = data.get("fuel", {})
    fuel_price = float(fuel_cfg.get("price_per_litre",       DEFAULT_FUEL["price_per_litre"]))
    road_l100  = float(fuel_cfg.get("road_litres_per_100km", DEFAULT_FUEL["road_litres_per_100km"]))
    op_fuel    = fuel_cfg.get("op_litres_per_ha",            DEFAULT_FUEL["op_litres_per_ha"])

    # Estimate avg travel distance per job from log (or default 15 km round trip)
    avg_travel_km = 15.0
    if len(ops_log) > 0:
        # Use a rough 15 km default — planner stores distance per stop but log doesn't yet
        avg_travel_km = 15.0

    with st.expander("Cost Inputs (edit to override)", expanded=True):
        with st.form("cost_inputs"):
            st.markdown("**Other costs per ha (labour, machinery depreciation, etc.)**")
            input_cols = st.columns(4)
            op_other_costs = {}
            for i, op in enumerate(OPERATION_TYPES):
                op_other_costs[op] = input_cols[i].number_input(
                    f"{op} other (£/ha)",
                    value=float(costs.get(op, DEFAULT_COSTS[op])) * 0.5,
                    min_value=0.0, step=1.0, key=f"other_cost_{op}",
                )

            st.markdown("**Fuel settings** (pulled from Contractor Setup)")
            fc1, fc2, fc3 = st.columns(3)
            fp_in  = fc1.number_input("Fuel price (£/L)", value=fuel_price,
                                       min_value=0.5, step=0.01, format="%.2f")
            rl_in  = fc2.number_input("Road use (L/100km)", value=road_l100,
                                       min_value=1.0, step=0.5)
            at_in  = fc3.number_input("Avg travel per job (km)", value=avg_travel_km,
                                       min_value=0.0, step=1.0,
                                       help="Average total road km per completed job (to/from field)")

            if st.form_submit_button("Calculate", type="primary"):
                st.session_state["roi_inputs"] = {
                    "other_costs": op_other_costs,
                    "fuel_price":  fp_in,
                    "road_l100":   rl_in,
                    "avg_travel":  at_in,
                }

    saved = st.session_state.get("roi_inputs", {
        "other_costs": {op: costs.get(op, DEFAULT_COSTS[op]) * 0.5 for op in OPERATION_TYPES},
        "fuel_price":  fuel_price,
        "road_l100":   road_l100,
        "avg_travel":  avg_travel_km,
    })
    pc        = saved["other_costs"]
    s_fp      = saved["fuel_price"]
    s_rl      = saved["road_l100"]
    s_travel  = saved["avg_travel"]

    profit_rows = []
    for op in OPERATION_TYPES:
        sub = df[df["operation"] == op]
        if sub.empty:
            continue
        rev    = sub["revenue"].sum()
        ha_op  = sub["hectares"].sum()
        jobs   = len(sub)

        # Fuel costs
        road_fuel_cost = jobs * s_travel * s_rl / 100 * s_fp
        op_lpha        = float(op_fuel.get(op, DEFAULT_FUEL["op_litres_per_ha"].get(op, 10)))
        field_fuel_cost = ha_op * op_lpha * s_fp
        total_fuel     = road_fuel_cost + field_fuel_cost

        # Other costs
        other_cost = ha_op * pc.get(op, 0)

        total_cost = total_fuel + other_cost
        profit     = rev - total_cost
        margin     = (profit / rev * 100) if rev > 0 else 0

        profit_rows.append({
            "Operation":       op,
            "Jobs":            jobs,
            "Ha":              round(ha_op, 1),
            "Revenue (£)":     round(rev, 2),
            "Fuel Cost (£)":   round(total_fuel, 2),
            "Other Cost (£)":  round(other_cost, 2),
            "Total Cost (£)":  round(total_cost, 2),
            "Profit (£)":      round(profit, 2),
            "Margin %":        round(margin, 1),
        })

    # Fuel summary card
    if profit_rows:
        total_fuel_all  = sum(r["Fuel Cost (£)"] for r in profit_rows)
        total_other_all = sum(r["Other Cost (£)"] for r in profit_rows)
        total_rev_all   = sum(r["Revenue (£)"] for r in profit_rows)
        total_profit    = total_rev_all - total_fuel_all - total_other_all
        fs1, fs2, fs3, fs4 = st.columns(4)
        fs1.metric("Total Revenue",    f"£{total_rev_all:,.2f}")
        fs2.metric("Total Fuel Cost",  f"£{total_fuel_all:,.2f}",
                   delta=f"£{total_fuel_all/total_rev_all*100:.1f}% of revenue" if total_rev_all else None,
                   delta_color="inverse")
        fs3.metric("Other Costs",      f"£{total_other_all:,.2f}")
        fs4.metric("Net Profit",       f"£{total_profit:,.2f}")

    if profit_rows:
        pdf = pd.DataFrame(profit_rows)
        def colour_profit(val):
            return "background-color: #d4edda" if val >= 0 else "background-color: #ffd6d6"
        st.dataframe(
            pdf.style.map(colour_profit, subset=["Profit (£)", "Margin %"]),
            use_container_width=True, hide_index=True,
        )

    # ── Full log ──────────────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("Operations Log")
    display_cols = ["date", "operation", "farm_name", "field_name", "hectares", "revenue", "operator"]
    available = [c for c in display_cols if c in df.columns]
    df_display = df[available].copy()
    df_display.columns = [c.replace("_", " ").title() for c in df_display.columns]
    df_display = df_display.sort_values("Date", ascending=False) if "Date" in df_display.columns else df_display
    st.dataframe(df_display, use_container_width=True, hide_index=True)

    # Download
    csv = df_display.to_csv(index=False).encode()
    st.download_button("Download Log as CSV", csv, "agriroute_operations_log.csv", "text/csv")
