"""ROI Tracker — revenue and cost analysis across completed operations."""
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from collections import defaultdict
from utils.data_models import OPERATION_TYPES, DEFAULT_COSTS, DEFAULT_WORK_RATES


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
    st.markdown("Enter your estimated cost per ha per operation to see profit margin.")

    with st.expander("Set Cost Inputs"):
        with st.form("cost_inputs"):
            input_cols = st.columns(4)
            op_costs_in = {}
            for i, op in enumerate(OPERATION_TYPES):
                op_costs_in[op] = input_cols[i].number_input(
                    f"{op} (£/ha cost)",
                    value=float(costs.get(op, DEFAULT_COSTS[op])) * 0.6,
                    min_value=0.0, step=1.0, key=f"input_cost_{op}",
                )
            if st.form_submit_button("Calculate"):
                st.session_state["profit_costs"] = op_costs_in

    pc = st.session_state.get("profit_costs", {op: costs.get(op, DEFAULT_COSTS[op]) * 0.6 for op in OPERATION_TYPES})

    profit_rows = []
    for op in OPERATION_TYPES:
        sub = df[df["operation"] == op]
        if sub.empty:
            continue
        rev    = sub["revenue"].sum()
        ha_op  = sub["hectares"].sum()
        cost_t = ha_op * pc.get(op, 0)
        profit = rev - cost_t
        margin = (profit / rev * 100) if rev > 0 else 0
        profit_rows.append({
            "Operation":   op,
            "Revenue (£)": round(rev, 2),
            "Cost (£)":    round(cost_t, 2),
            "Profit (£)":  round(profit, 2),
            "Margin %":    round(margin, 1),
        })

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
