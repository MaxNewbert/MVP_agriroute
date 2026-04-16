"""
AgriRoute — Contractor Field Operations Planning & Reporting
Run with:  streamlit run app.py
"""
import streamlit as st
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from utils.data_models import load_data, save_data

st.set_page_config(
    page_title="AgriRoute",
    page_icon="🌾",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Session state ─────────────────────────────────────────────────────────────
if "data" not in st.session_state:
    st.session_state.data = load_data()

if "page" not in st.session_state:
    st.session_state.page = "dashboard"

# ── Global CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    [data-testid="stSidebar"] { background-color: #1B4332; }
    [data-testid="stSidebar"] * { color: white !important; }
    [data-testid="stSidebar"] .stSelectbox label { color: #D8F3DC !important; }
    [data-testid="stSidebar"] .stButton > button {
        background-color: #2D6A4F; color: white; border: none;
        border-radius: 4px; width: 100%; margin-bottom: 2px;
        text-align: left; padding: 8px 12px;
    }
    [data-testid="stSidebar"] .stButton > button:hover { background-color: #52B788; }
    h1 { color: #1B4332; }
    h2 { color: #2D6A4F; }
    .stButton > button { border-radius: 4px; }
    div[data-testid="metric-container"] {
        background: #f8f9fa; border-left: 4px solid #2D6A4F;
        padding: 8px 12px; border-radius: 6px;
    }
</style>
""", unsafe_allow_html=True)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🌾 AgriRoute")
    st.markdown("---")

    contractor = st.session_state.data.get("contractor", {})
    name = contractor.get("name", "Set up contractor →")
    st.markdown(f"**{name}**")
    home = contractor.get("home_location", "")
    if home:
        st.caption(f"📍 {home}")
    st.markdown("---")

    pages = {
        "🏠  Dashboard":         "dashboard",
        "⚙️  Contractor Setup":  "setup",
        "🗺️  Farms & Fields":    "farms",
        "📅  Day Planner":        "planner",
        "🌤️  Weather":            "weather",
        "📊  ROI Tracker":        "roi",
        "📄  Completion Reports": "reports",
        "📁  Field Files":        "files",
    }

    for label, key in pages.items():
        if st.button(label, key=f"nav_{key}", use_container_width=True):
            st.session_state.page = key
            st.rerun()

    st.markdown("---")
    st.caption("AgriRoute v1.0 MVP")

# ── Route ─────────────────────────────────────────────────────────────────────
page = st.session_state.page
data = st.session_state.data

if page == "dashboard":
    from pages.pg_dashboard import render
    render(data)

elif page == "setup":
    from pages.pg_setup import render
    render(data)

elif page == "farms":
    from pages.pg_farms import render
    render(data)

elif page == "planner":
    from pages.pg_planner import render
    render(data)

elif page == "weather":
    from pages.pg_weather import render
    render(data)

elif page == "roi":
    from pages.pg_roi import render
    render(data)

elif page == "reports":
    from pages.pg_reports import render
    render(data)

elif page == "files":
    from pages.pg_files import render
    render(data)
