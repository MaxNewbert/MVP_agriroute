"""Field Files — upload as-applied maps, harvest maps, and link documents per field."""
import streamlit as st
import os
import json
import pandas as pd
from datetime import datetime
from utils.data_models import save_data

UPLOADS_DIR = os.path.join(os.path.dirname(__file__), "..", "uploads")


def _field_upload_dir(farm_id: str, field_id: str) -> str:
    path = os.path.join(UPLOADS_DIR, farm_id, field_id)
    os.makedirs(path, exist_ok=True)
    return path


def _save_file(farm_id: str, field_id: str, uploaded_file) -> str:
    folder = _field_upload_dir(farm_id, field_id)
    safe_name = uploaded_file.name.replace(" ", "_")
    dest = os.path.join(folder, safe_name)
    with open(dest, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return dest


def _list_files(farm_id: str, field_id: str) -> list:
    folder = _field_upload_dir(farm_id, field_id)
    if not os.path.exists(folder):
        return []
    return [
        {
            "filename": fn,
            "path":     os.path.join(folder, fn),
            "size_kb":  round(os.path.getsize(os.path.join(folder, fn)) / 1024, 1),
            "modified": datetime.fromtimestamp(
                os.path.getmtime(os.path.join(folder, fn))
            ).strftime("%Y-%m-%d %H:%M"),
        }
        for fn in sorted(os.listdir(folder))
        if not fn.startswith(".")
    ]


def _try_parse_csv_map(path: str) -> dict:
    """Attempt basic stats from an as-applied or harvest CSV."""
    try:
        df = pd.read_csv(path, nrows=5000)
        df.columns = [c.strip().lower() for c in df.columns]
        stats = {"rows": len(df), "columns": list(df.columns)}

        # Try to find rate / yield columns
        rate_cols  = [c for c in df.columns if any(k in c for k in ["rate","dose","application"])]
        yield_cols = [c for c in df.columns if any(k in c for k in ["yield","harvest","moisture"])]

        for col in rate_cols[:2]:
            num = pd.to_numeric(df[col], errors="coerce").dropna()
            if not num.empty:
                stats[f"{col}_mean"] = round(float(num.mean()), 2)
                stats[f"{col}_min"]  = round(float(num.min()),  2)
                stats[f"{col}_max"]  = round(float(num.max()),  2)

        for col in yield_cols[:2]:
            num = pd.to_numeric(df[col], errors="coerce").dropna()
            if not num.empty:
                stats[f"{col}_mean"] = round(float(num.mean()), 2)
                stats[f"{col}_min"]  = round(float(num.min()),  2)
                stats[f"{col}_max"]  = round(float(num.max()),  2)

        return stats
    except Exception:
        return {}


def render(data: dict):
    st.title("Field Files")
    st.markdown(
        "Upload and manage files per field: as-applied maps, harvest maps, "
        "soil samples, VRA prescriptions, and any other supporting documents."
    )

    farms = data.get("farms", {})
    if not farms:
        st.info("Add farms and fields first.")
        return

    # ── Farm / Field selector ─────────────────────────────────────────────────
    c1, c2 = st.columns(2)
    farm_options  = {f["name"]: fid for fid, f in farms.items()}
    sel_farm_name = c1.selectbox("Farm", list(farm_options.keys()))
    sel_farm_id   = farm_options[sel_farm_name]
    farm          = farms[sel_farm_id]
    fields        = farm.get("fields", {})

    if not fields:
        st.warning("No fields in this farm.")
        return

    field_options  = {f["name"]: fid for fid, f in fields.items()}
    sel_field_name = c2.selectbox("Field", list(field_options.keys()))
    sel_field_id   = field_options[sel_field_name]
    field          = fields[sel_field_id]

    st.markdown(f"**{sel_farm_name} / {sel_field_name}** — {field.get('crop_type','')} {field.get('variety','')} | {field.get('hectares','')} ha")
    st.markdown("---")

    tab_upload, tab_links, tab_view = st.tabs(["Upload Files", "Link External Documents", "View All Files"])

    # ── UPLOAD ────────────────────────────────────────────────────────────────
    with tab_upload:
        st.subheader("Upload Files")
        file_type = st.selectbox("File Category", [
            "As-Applied Map",
            "Harvest Map",
            "Soil Sample Results",
            "VRA Prescription Map",
            "Remote Sensing Report",
            "Field Boundary (GeoJSON/SHP)",
            "Other",
        ])
        note = st.text_input("Description / Note", placeholder="e.g. T2 fungicide as-applied, 12/05/2025")
        uploaded = st.file_uploader(
            "Choose file(s)",
            type=["csv", "xlsx", "json", "geojson", "shp", "zip", "pdf", "png", "jpg", "kml"],
            accept_multiple_files=True,
        )

        if uploaded and st.button("Save Files", type="primary"):
            for uf in uploaded:
                saved_path = _save_file(sel_farm_id, sel_field_id, uf)
                # Record in field metadata
                file_meta = {
                    "filename":   uf.name,
                    "path":       saved_path,
                    "category":   file_type,
                    "note":       note,
                    "uploaded":   datetime.now().isoformat(),
                }
                data["farms"][sel_farm_id]["fields"][sel_field_id].setdefault("files", []).append(file_meta)
            save_data(data)
            st.success(f"{len(uploaded)} file(s) saved.")
            st.rerun()

        # ── Auto-parse CSV maps ────────────────────────────────────────────────
        st.markdown("---")
        st.subheader("As-Applied / Harvest Map Analysis")
        st.markdown("Upload a CSV export from your controller to extract key stats.")

        csv_up = st.file_uploader("Upload CSV map", type=["csv"], key="csv_analysis")
        if csv_up:
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
                tmp.write(csv_up.getbuffer())
                tmp_path = tmp.name
            stats = _try_parse_csv_map(tmp_path)
            if stats:
                st.markdown(f"**Rows:** {stats.pop('rows', '?')}  |  **Columns:** {', '.join(stats.pop('columns', []))}")
                if stats:
                    stat_df = pd.DataFrame([{"Metric": k, "Value": v} for k, v in stats.items()])
                    st.dataframe(stat_df, use_container_width=True, hide_index=True)
                else:
                    st.info("No rate or yield columns detected automatically. Check column names.")

                # Try map visualisation
                try:
                    raw_df = pd.read_csv(tmp_path, nrows=5000)
                    raw_df.columns = [c.strip() for c in raw_df.columns]
                    lat_cols = [c for c in raw_df.columns if c.lower() in ["lat","latitude","y"]]
                    lon_cols = [c for c in raw_df.columns if c.lower() in ["lon","lng","longitude","x"]]
                    if lat_cols and lon_cols:
                        raw_df["_lat"] = pd.to_numeric(raw_df[lat_cols[0]], errors="coerce")
                        raw_df["_lon"] = pd.to_numeric(raw_df[lon_cols[0]], errors="coerce")
                        raw_df = raw_df.dropna(subset=["_lat","_lon"])
                        if not raw_df.empty:
                            rate_cols = [c for c in raw_df.columns
                                         if any(k in c.lower() for k in ["rate","dose","yield","harvest"])]
                            color_col = rate_cols[0] if rate_cols else None
                            if color_col:
                                raw_df["_color_val"] = pd.to_numeric(raw_df[color_col], errors="coerce")
                                raw_df = raw_df.dropna(subset=["_color_val"])

                            import folium
                            from streamlit_folium import st_folium
                            import numpy as np

                            mid_lat = raw_df["_lat"].mean()
                            mid_lon = raw_df["_lon"].mean()
                            m = folium.Map([mid_lat, mid_lon], zoom_start=14, tiles="OpenStreetMap")

                            if color_col and "_color_val" in raw_df.columns:
                                vmin = raw_df["_color_val"].quantile(0.05)
                                vmax = raw_df["_color_val"].quantile(0.95)
                                sample = raw_df.sample(min(2000, len(raw_df)))
                                for _, row in sample.iterrows():
                                    norm = (row["_color_val"] - vmin) / (vmax - vmin + 1e-9)
                                    norm = max(0.0, min(1.0, norm))
                                    r = int(255 * (1 - norm))
                                    g = int(200 * norm)
                                    color = f"#{r:02x}{g:02x}00"
                                    folium.CircleMarker(
                                        [row["_lat"], row["_lon"]],
                                        radius=4, color=color, fill=True,
                                        fill_color=color, fill_opacity=0.8, weight=0,
                                        tooltip=f"{color_col}: {row['_color_val']:.2f}",
                                    ).add_to(m)
                                st.caption(f"Map coloured by **{color_col}** (red = low, green = high)")
                            else:
                                sample = raw_df.sample(min(2000, len(raw_df)))
                                for _, row in sample.iterrows():
                                    folium.CircleMarker([row["_lat"], row["_lon"]],
                                                         radius=3, color="#2D6A4F", fill=True,
                                                         fill_opacity=0.6, weight=0).add_to(m)
                            st_folium(m, width=None, height=400, use_container_width=True)
                except Exception as e:
                    st.info(f"Could not render map: {e}")
            else:
                st.warning("Could not parse this CSV. Check the file format.")
            os.unlink(tmp_path)

    # ── LINK EXTERNAL DOCUMENTS ────────────────────────────────────────────────
    with tab_links:
        st.subheader("Link External Documents or Evidence")
        st.markdown(
            "Link to model outputs, remote sensing reports, advisor emails, or any "
            "external URL relevant to this field."
        )

        field_links = field.get("external_links", [])

        with st.form("form_add_link"):
            lc1, lc2 = st.columns([2, 2])
            link_label = lc1.text_input("Description", placeholder="AHDB Septoria Risk — T2 decision")
            link_type  = lc2.selectbox("Type", [
                "Disease model output",
                "VRA / remote sensing report",
                "Advisor email / recommendation",
                "Soil sample report",
                "Satellite / NDVI image",
                "Weather record",
                "Other",
            ])
            link_url = st.text_input("URL or file path",
                                      placeholder="https://... or \\\\server\\share\\report.pdf")
            lc3, lc4, lc5 = st.columns(3)
            link_adv_name  = lc3.text_input("Advisor / Source Name")
            link_adv_email = lc4.text_input("Advisor Email")
            link_date      = lc5.date_input("Date", value=None)

            if st.form_submit_button("Add Link", type="primary"):
                entry = {
                    "label":         link_label,
                    "type":          link_type,
                    "url":           link_url,
                    "advisor_name":  link_adv_name,
                    "advisor_email": link_adv_email,
                    "date":          str(link_date) if link_date else "",
                    "added":         datetime.now().isoformat(),
                }
                data["farms"][sel_farm_id]["fields"][sel_field_id].setdefault("external_links", []).append(entry)
                save_data(data)
                st.success("Link saved.")
                st.rerun()

        if field_links:
            st.markdown("**Saved Links**")
            for i, lnk in enumerate(field_links):
                lca, lcb = st.columns([5, 1])
                url = lnk.get("url", "")
                if url.startswith("http"):
                    lca.markdown(f"**[{lnk['label']}]({url})** — {lnk['type']} | {lnk.get('date','')}")
                else:
                    lca.markdown(f"**{lnk['label']}** — {lnk['type']} | `{url}` | {lnk.get('date','')}")
                if lnk.get("advisor_name"):
                    lca.caption(f"Source: {lnk['advisor_name']}  {lnk.get('advisor_email','')}")
                if lcb.button("Remove", key=f"rm_link_{i}"):
                    data["farms"][sel_farm_id]["fields"][sel_field_id]["external_links"].pop(i)
                    save_data(data)
                    st.rerun()

    # ── VIEW ALL FILES ─────────────────────────────────────────────────────────
    with tab_view:
        st.subheader("All Files for this Field")
        disk_files = _list_files(sel_farm_id, sel_field_id)
        meta_files = field.get("files", [])

        if not disk_files and not meta_files:
            st.info("No files uploaded yet.")
        else:
            if disk_files:
                st.markdown("**Uploaded Files**")
                df_files = pd.DataFrame([{
                    "Filename":  f["filename"],
                    "Size (KB)": f["size_kb"],
                    "Modified":  f["modified"],
                } for f in disk_files])
                st.dataframe(df_files, use_container_width=True, hide_index=True)

                # Download any file
                sel_fn = st.selectbox("Download file", [f["filename"] for f in disk_files])
                if sel_fn:
                    fp = next((f["path"] for f in disk_files if f["filename"] == sel_fn), None)
                    if fp and os.path.exists(fp):
                        with open(fp, "rb") as fh:
                            st.download_button("Download", fh.read(), file_name=sel_fn)

            if meta_files:
                st.markdown("**File Records**")
                meta_df = pd.DataFrame([{
                    "Filename": m["filename"],
                    "Category": m.get("category", ""),
                    "Note":     m.get("note", ""),
                    "Uploaded": m.get("uploaded", "")[:10],
                } for m in meta_files])
                st.dataframe(meta_df, use_container_width=True, hide_index=True)
